"""Confirmed tempo boundaries, including no-charge rejection of old sources."""
import json

import pytest

from app.music.limits import require_tempo, check_prompt_tempo
from app.music.pipeline import check_content
from app.music.validation import MusicValidationError
from app.providers.errors import ProviderError
from app.providers.staged import HarmonyPlan
from app.schemas.composition import RegenerationConstraints
from test_staged_provider import StageDouble


@pytest.mark.parametrize('bpm',[60.0,120.0])
def test_boundary_tempos_generate_real_note_data_and_pass_final_checks(bpm):
    provider=StageDouble();original=provider.generate_structure
    def generate(prompt,instruction,schema):
        value,receipt=original(prompt,instruction,schema)
        if schema is HarmonyPlan:
            data=value.model_dump(mode='json');data['tempo_bpm']=bpm
            value=HarmonyPlan.model_validate_json(json.dumps(data))
            assert '60–120 BPM' in instruction
        return value,receipt
    provider.generate_structure=generate
    candidate,_=provider.generate_candidate('test',production=True)
    check_content(candidate.composition)
    assert candidate.composition.tempo_bpm==bpm


@pytest.mark.parametrize('bpm',[59.999,120.001,float('inf'),float('nan')])
def test_schema_and_final_delivery_reject_out_of_range_tempos(bpm):
    provider=StageDouble();candidate,_=provider.generate_candidate('test',production=True)
    changed=candidate.composition.model_copy(update={'tempo_bpm':bpm})
    with pytest.raises(MusicValidationError):check_content(changed)
    with pytest.raises(ProviderError):require_tempo(bpm)
    with pytest.raises(ValueError):
        HarmonyPlan.model_validate_json(json.dumps({'title':'test','creative_plan':'test',
            'tempo_bpm':bpm,'key_signature':'C','degrees':[1,5,1]}))


@pytest.mark.parametrize('prompt',['600 BPM','BPM: 50','-80 bpm'])
def test_explicit_out_of_range_request_never_calls_model(prompt):
    provider=StageDouble()
    with pytest.raises(ProviderError) as error:provider.generate_candidate(prompt,production=True)
    assert error.value.code=='tempo_out_of_range' and not provider.calls


def test_regeneration_keeps_original_tempo_despite_conflicting_text():
    provider=StageDouble()
    candidate,_=provider.generate_candidate('改成600 BPM',production=True,
        regeneration_constraints=RegenerationConstraints(tempo_bpm=72.0,key_signature='C'))
    assert candidate.composition.tempo_bpm==72


@pytest.mark.parametrize('bpm',[50.0,130.0])
def test_out_of_range_source_rejected_without_charge_or_rewriting(bpm):
    provider=StageDouble();constraints=RegenerationConstraints(tempo_bpm=bpm,key_signature='C')
    with pytest.raises(ProviderError) as error:
        provider.generate_candidate('test',production=True,regeneration_constraints=constraints)
    assert error.value.code=='tempo_out_of_range' and not provider.calls
    assert constraints.tempo_bpm==bpm
