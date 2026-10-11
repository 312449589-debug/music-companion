"""Isolated stage doubles; never used by production."""
import json
from decimal import Decimal
import pytest
from app.providers.staged import StagedQwenProvider, HarmonyPlan, BarChoice, build_bar, catalog, compatible
from app.providers.errors import ProviderError
from app.music.pipeline import check_content
from app.music.fingering import assign_fingering
from app.schemas.composition import RegenerationConstraints


class StageDouble(StagedQwenProvider):
    def __init__(self,key='C',fail_bar=False):
        self.progress=None;self.calls=[];self.key=key;self.fail_bar=fail_bar;self.failed=False

    def generate_structure(self,prompt,instruction,schema):
        self.calls.append((prompt,instruction,schema.__name__))
        receipt={'estimated_cost_cny':'0.001','provider_model':'test-double'}
        if schema is HarmonyPlan:
            return HarmonyPlan(title='isolated test',creative_plan='test motif and return',tempo_bpm=72.0,
                               key_signature=self.key,degrees=[1,4,5,1]),receipt
        options,_=json.JSONDecoder().raw_decode(instruction.split('可选指型与旋律音：',1)[1])
        tones=options[0]['melody_tones']
        cells=[{'pattern':'ee','tones':[0,1]} for _ in range(4)]
        if self.fail_bar and not self.failed:
            self.failed=True;cells[0]['tones']=[20,1]
        if '旋律最后用属和弦根音或五音' in instruction:
            root='E' if self.key=='A minor' else 'G'
            cells[-1]['tones'][-1]=next(t['tone_index'] for t in tones if t['name'].startswith(root))
        if '最后旋律音必须选择主音' in instruction:
            root='A' if self.key=='A minor' else 'C'
            cells[-1]={'pattern':'q','tones':[next(t['tone_index'] for t in tones if t['name'].startswith(root))]}
        return BarChoice.model_validate_json(json.dumps({'voicing_index':0,'development':'test development','cells':cells})),receipt


@pytest.mark.parametrize('key',['C','A minor'])
def test_actual_generated_choices_pass_harmony_and_fingering(key):
    p=StageDouble(key);c,r=p.generate_candidate('test prompt',production=True)
    piece,summary=assign_fingering(c.composition);check_content(piece)
    assert piece.origin=='ai' and piece.prompt=='test prompt' and piece.generator_version=='qwen-staged-2'
    assert len(p.calls)==5 and len(r['steps'])==5 and summary.high_fret_count==0
    assert Decimal(r['estimated_cost_cny'])==Decimal('0.005')
    assert '此前实际小节' in p.calls[-1][1] and '此前旋律实际音高' in p.calls[-1][1]


def test_bad_bar_corrects_only_this_bar_and_counts_receipt():
    p=StageDouble(fail_bar=True);c,r=p.generate_candidate('test',production=True)
    assert len(p.calls)==6 and len(r['steps'])==6
    assert r['steps'][1]['status']=='rejected'
    assert 'tone_index must be' in p.calls[2][1]
    check_content(assign_fingering(c.composition)[0])


def test_rhythm_cells_preserve_selected_pitch_and_exact_time_without_rounding():
    data={'voicing_index':0,'development':'test','cells':[
        {'pattern':'ess','tones':[0,1,0]}, {'pattern':'sse','tones':[1,0,1]},
        {'pattern':'ds','tones':[0,1]}, {'pattern':'q','tones':[0]}]}
    choice=BarChoice.model_validate_json(json.dumps(data));before=choice.model_dump()
    bar,option=build_bar(choice,list(catalog(0,False,1)))
    melody=[n for n in bar.notes if n.voice=='melody']
    assert [n.duration_ticks for n in melody]==[240,120,120,120,120,240,360,120,480]
    assert [n.offset_tick for n in melody]==[0,240,360,480,600,720,960,1320,1440]
    assert melody[-1].midi_pitch==option['tones'][0]
    assert choice.model_dump()==before


@pytest.mark.parametrize('cells',[
    [{'pattern':'ee','tones':[0]}]*4,
    [{'pattern':'q','tones':[0]}]*3,
    [{'pattern':'unknown','tones':[0]}]*4,
])
def test_invalid_rhythm_choices_rejected_not_padded(cells):
    with pytest.raises(ValueError):
        BarChoice.model_validate_json(json.dumps({'voicing_index':0,'development':'test','cells':cells}))


def test_all_rest_bar_rejected_and_choice_unchanged():
    choice=BarChoice.model_validate_json(json.dumps({'voicing_index':0,'development':'test',
            'cells':[{'pattern':'q','tones':[None]}]*4}))
    before=choice.model_dump()
    with pytest.raises(ValueError,match='actual melody'):build_bar(choice,list(catalog(0,False,1)))
    assert choice.model_dump()==before


def test_cadence_catalog_contains_actual_leading_tone_resolution():
    pairs=[(d,t) for d in catalog(0,False,5) for t in compatible(d,catalog(0,False,1),0)]
    assert pairs
    assert all(all(p+1 in t['pitches'] for p in d['pitches'] if p%12==11) for d,t in pairs)
    assert all(t['complete'] and any(p%12==0 for p in t['tones']) for d,t in pairs)


def test_regeneration_tempo_key_not_silently_rewritten():
    p=StageDouble()
    with pytest.raises(ProviderError):
        p.generate_candidate('test',production=True,regeneration_constraints=RegenerationConstraints(tempo_bpm=90.0,key_signature='C'))
    assert len(p.calls)==2 and all(s=='HarmonyPlan' for _,_,s in p.calls)


def test_auth_budget_and_network_errors_do_not_retry_music_phase():
    p=StageDouble()
    def fail(*args):raise ProviderError('budget_exceeded','test exhausted budget')
    p.generate_structure=fail
    with pytest.raises(ProviderError) as error:p.generate_candidate('test',production=True)
    assert error.value.code=='budget_exceeded'


def test_failed_phase_keeps_receipts_and_does_not_restart_plan():
    p=StageDouble()
    original=p.generate_structure
    def fail_bar(prompt,instruction,schema):
        if schema is HarmonyPlan:return original(prompt,instruction,schema)
        p.calls.append((prompt,instruction,schema.__name__))
        raise ProviderError('structure_error','test',correction_feedback='invalid cells',
                            receipt={'estimated_cost_cny':'0.001'})
    p.generate_structure=fail_bar
    with pytest.raises(ProviderError) as error:p.generate_candidate('test',production=True)
    assert len(p.calls)==3 and len(error.value.receipt['steps'])==3
    assert error.value.receipt['failed_phase']=='BarChoice'
    assert error.value.receipt['steps'][-1]['status']=='rejected'


def test_failed_phase_is_not_restarted_by_pipeline(tmp_path):
    from app.music.pipeline import generate_work,PipelineError
    p=StageDouble()
    original=p.generate_structure
    def fail_bar(prompt,instruction,schema):
        if schema is HarmonyPlan:return original(prompt,instruction,schema)
        p.calls.append((prompt,instruction,schema.__name__))
        raise ProviderError('structure_error','test',correction_feedback='bad cells',receipt={'estimated_cost_cny':'0.001'})
    p.generate_structure=fail_bar
    with pytest.raises(PipelineError) as error:generate_work('test',jobs_root=tmp_path,provider=p)
    assert len(p.calls)==3
    m=json.loads((tmp_path/error.value.job_id/'manifest.json').read_text())
    assert len(m['attempts'])==1 and m['status']=='failed' and m['files']=={}
    assert len(m['attempts'][0]['request']['steps'])==3


def test_final_rest_corrected_locally_before_whole_piece_validation():
    p=StageDouble();original=p.generate_structure;sent=[False]
    def once(prompt,instruction,schema):
        choice,receipt=original(prompt,instruction,schema)
        if schema is BarChoice and '最后旋律音必须选择主音' in instruction and not sent[0]:
            sent[0]=True
            data=choice.model_dump(mode='json');data['cells'][-1]['tones']=[None]
            return BarChoice.model_validate_json(json.dumps(data)),receipt
        return choice,receipt
    p.generate_structure=once
    c,r=p.generate_candidate('test',production=True)
    assert len(p.calls)==6 and 'do not end with a rest' in p.calls[-1][1]
    check_content(assign_fingering(c.composition)[0])
