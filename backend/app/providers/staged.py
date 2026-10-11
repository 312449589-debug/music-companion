"""AI plans harmony, then selects playable pitches and rhythms one bar at a time.

Catalogs are instrument/theory constraints, not stored songs or fallback music.
Every chord degree, voicing, melody tone and rhythm is selected by the model.
"""
import itertools
import json
import re
import uuid
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, List, Literal, Optional, Tuple, Union

from pydantic import Field

from app.schemas.composition import ContractModel, STANDARD_TUNING
from app.music.harmony import tonal_key
from app.music.fingering import assign_fingering
from app.music.validation import MusicValidationError
from app.music.limits import MIN_BPM, MAX_BPM, require_tempo, check_prompt_tempo
from .errors import ProviderError
from .qwen import QwenProvider, MusicCandidate, CompactCandidate, PlannedBar, PlannedNote, expand_candidate

NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
MAJOR = [(0,''),(2,'m'),(4,'m'),(5,''),(7,''),(9,'m'),(11,'dim')]
MINOR = [(0,'m'),(2,'dim'),(3,''),(5,'m'),(7,''),(8,''),(11,'dim')]
INTERVALS = {'': (0,4,7), 'm': (0,3,7), 'dim': (0,3,6)}


def explicit_key(prompt):
    """Recognize explicit common key names; moods do not imply a key."""
    matches = re.findall(r'(降|升)?([A-Ga-g])([#b♯♭]?)[ \t]*(大调|小调|major|minor)', prompt)
    keys = set()
    for prefix, letter, accidental, mode in matches:
        pc = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[letter.upper()]
        pc += (1 if prefix == '升' else -1 if prefix == '降' else 0)
        pc += (1 if accidental in ('#','♯') else -1 if accidental in ('b','♭') else 0)
        keys.add((pc % 12, mode in ('小调','minor')))
    if len(keys) > 1:
        raise ProviderError('unsupported_key', '首版一首作品只使用一个调性，请明确一个大调或小调。')
    return next(iter(keys)) if keys else None


class HarmonyPlan(ContractModel):
    title: str = Field(min_length=1, max_length=80)
    creative_plan: str = Field(min_length=1, max_length=1500)
    tempo_bpm: float = Field(ge=MIN_BPM, le=MAX_BPM)
    key_signature: str = Field(min_length=1)
    degrees: List[Literal[1,2,3,4,5,6,7]] = Field(min_length=2, max_length=16)


Tone = Optional[int]


class QuarterCell(ContractModel):
    pattern: Literal['q']
    tones: Tuple[Tone]


class EighthCell(ContractModel):
    pattern: Literal['ee']
    tones: Tuple[Tone, Tone]


class ShortCell(ContractModel):
    pattern: Literal['ess', 'sse', 'ses']
    tones: Tuple[Tone, Tone, Tone]


class SixteenthCell(ContractModel):
    pattern: Literal['ssss']
    tones: Tuple[Tone, Tone, Tone, Tone]


class DottedCell(ContractModel):
    pattern: Literal['ds', 'sd']
    tones: Tuple[Tone, Tone]


BeatCell = Annotated[Union[QuarterCell, EighthCell, ShortCell, SixteenthCell, DottedCell], Field(discriminator='pattern')]
RHYTHMS = {'q':[480], 'ee':[240,240], 'ess':[240,120,120], 'sse':[120,120,240],
           'ses':[120,240,120], 'ssss':[120,120,120,120], 'ds':[360,120], 'sd':[120,360]}


class BarChoice(ContractModel):
    voicing_index: int = Field(ge=0, le=30)
    development: str = Field(min_length=1, max_length=400)
    cells: Tuple[BeatCell, BeatCell, BeatCell, BeatCell]


def positions(pitch):
    return [(s,pitch-open_pitch) for s,open_pitch in STANDARD_TUNING.items()
            if 0 <= pitch-open_pitch <= 5]


def valid_hand(shape):
    if len({s for s,f in shape}) != len(shape): return False
    pressed = [f for s,f in shape if f]
    return not pressed or (max(pressed)-min(pressed)<=3 and min(pressed)<=3)


@lru_cache(maxsize=128)
def catalog(tonic, minor, degree):
    offset, quality = (MINOR if minor else MAJOR)[degree-1]
    root = (tonic+offset)%12
    pcs = {(root+x)%12 for x in INTERVALS[quality]}
    third = (root+INTERVALS[quality][1])%12
    chord = NAMES[root]+quality
    pitches = [p for p in range(40,61) if p%12 in pcs]
    options = []
    for count in (2,3,4):
        for notes in itertools.combinations(pitches,count):
            if notes[0]%12!=root or third not in {p%12 for p in notes}: continue
            complete = {p%12 for p in notes} == pcs
            for shape in itertools.product(*(positions(p) for p in notes)):
                if not valid_hand(shape): continue
                tones = [p for p in range(55,72) if p%12 in pcs and p not in notes
                         and any(valid_hand(shape+(position,)) for position in positions(p))]
                if len(tones)<2: continue
                options.append({'pitches':list(notes),'tones':tones,'complete':complete,
                                'shape':shape,'chord':chord})
    # Keep a diverse bounded set, retaining pitches needed for exact cadence connections.
    unique = {}
    for option in sorted(options,key=lambda o:(not o['complete'],len(o['pitches']),sum(f for s,f in o['shape']))):
        key = tuple(option['pitches'])
        if key not in unique or len(option['tones'])>len(unique[key]['tones']): unique[key]=option
    return tuple(unique.values())


def compatible(dominant, tonic_options, tonic_pc):
    leading = [p for p in dominant['pitches'] if p%12==(tonic_pc-1)%12]
    return [o for o in tonic_options if o['complete'] and leading
            and all(p+1 in o['pitches'] for p in leading)
            and any(p%12==tonic_pc for p in o['tones'])]


def public_options(options):
    return [{'voicing_index':i, 'accompaniment':[NAMES[p%12]+str(p//12-1) for p in o['pitches']],
             'melody_tones':[{'tone_index':j,'name':NAMES[p%12]+str(p//12-1)} for j,p in enumerate(o['tones'])]}
            for i,o in enumerate(options)]


def build_bar(choice, options):
    if choice.voicing_index>=len(options): raise ValueError('voicing_index is not in supplied options')
    option=options[choice.voicing_index]
    notes=[PlannedNote(voice='accompaniment',offset_tick=0,duration_ticks=1920,midi_pitch=p) for p in option['pitches']]
    tick=0
    for cell in choice.cells:
        for tone_index,duration in zip(cell.tones,RHYTHMS[cell.pattern]):
            if tone_index is not None:
                if not 0<=tone_index<len(option['tones']):
                    raise ValueError('tone_index must be 0..%s for selected voicing'%(len(option['tones'])-1))
                notes.append(PlannedNote(voice='melody',offset_tick=tick,duration_ticks=duration,
                                         midi_pitch=option['tones'][tone_index]))
            tick+=duration
    assert tick==1920
    if not any(n.voice=='melody' for n in notes): raise ValueError('bar needs actual melody')
    return PlannedBar(chord=option['chord'],notes=notes),option


class StagedQwenProvider(QwenProvider):
    def _receipt(self, receipts, failed_phase=None):
        value = {'mode': 'staged-ai-v1', 'steps': receipts,
                 'estimated_cost_cny': str(sum((Decimal(r.get('estimated_cost_cny', '0')) for r in receipts), Decimal('0')))}
        if failed_phase: value['failed_phase'] = failed_phase
        return value

    def _request_checked(self, prompt, instructions, schema, check, receipts):
        feedback = ''
        for attempt in range(2):
            try:
                control = getattr(self, 'control', None)
                if control: control.checkpoint()
                data, receipt = self.generate_structure(prompt, instructions + feedback, schema)
                receipt['phase'] = schema.__name__
                if schema is BarChoice: receipt['bar_number'] = getattr(self, 'current_bar', None)
                receipts.append(receipt)
                try:
                    result = check(data)
                except (ValueError, MusicValidationError):
                    receipt['status'] = 'rejected'
                    raise
                receipt['status'] = 'accepted'
                return data, result
            except ProviderError as error:
                if error.receipt:
                    receipts.append(dict(error.receipt, phase=schema.__name__, status='rejected',
                                         bar_number=getattr(self, 'current_bar', None) if schema is BarChoice else None))
                if error.code != 'structure_error':
                    receipts.append({'phase': schema.__name__, 'status': 'failed', 'code': error.code,
                                     'billing': 'see_budget_ledger',
                                     'bar_number': getattr(self, 'current_bar', None) if schema is BarChoice else None})
                    error.receipt = self._receipt(receipts, schema.__name__)
                    raise
                feedback = '\n请修正本步骤错误：' + (error.correction_feedback or str(error))
            except (ValueError, MusicValidationError) as error:
                feedback = '\n请修正本步骤错误：' + str(error)[:1500]
            finally:
                observer = getattr(self, 'receipt_observer', None)
                if observer: observer(self._receipt(receipts))
        raise ProviderError('structure_error', '本步骤两次生成仍未通过检查，未交付作品。',
                            correction_feedback=feedback, receipt=self._receipt(receipts, schema.__name__))

    def generate_candidate(self,prompt,*,production=False,correction_feedback=None,regeneration_constraints=None,**internal):
        # Generic JSON transport and original connection diagnostics remain unchanged.
        if not production or internal.get('_structured') is not None:
            return super().generate_candidate(prompt,production=production,correction_feedback=correction_feedback,
                                              regeneration_constraints=regeneration_constraints,**internal)
        receipts=[]
        if regeneration_constraints:
            require_tempo(regeneration_constraints.tempo_bpm, source=True)
        else:
            check_prompt_tempo(prompt)
        requested_key = explicit_key(prompt) if not regeneration_constraints else None
        if requested_key and not any(compatible(o, catalog(*requested_key, 1), requested_key[0])
                                     for o in catalog(*requested_key, 5)):
            raise ProviderError('unsupported_key', '指定调性暂不支持当前指型范围，请改用C大调或A小调；本次没有发送模型请求。')
        if regeneration_constraints:
            tonic, minor = tonal_key(regeneration_constraints.key_signature)
            if not any(compatible(o, catalog(tonic, minor, 1), tonic) for o in catalog(tonic, minor, 5)):
                raise ProviderError('unsupported_key', '原作品调性暂不支持当前生成指型范围，不能保持调性重新生成；请保留旧作品。')
        supported = []
        for tonic in range(12):
            for minor in (False, True):
                if any(compatible(o, catalog(tonic, minor, 1), tonic) for o in catalog(tonic, minor, 5)):
                    supported.append(NAMES[tonic] + (' minor' if minor else ''))
        plan_instruction=('先只规划原创指弹小品的标题、动机与发展、速度、调性和和声级数，不写音符。'
                          '常用清楚的大调或小调写法如C、A minor；每小节一个调内三和弦，用degrees列出级数。'
                          '大调1/3/6为主、2/4下属、5/7属；小调使用和声小调的5级大三和弦。'
                          '禁止属功能紧接下属功能。最后两个级数必须5、1。'
                          '用户未指定时优先4到8小节，演奏时长<=57秒，4/4。'
                          '首版速度必须在60–120 BPM之间，包含60和120，不得自行放宽或改写结果速度。'
                          '请按听感原创构思，以重复、变化重复、片段化、节奏变化和回归组织旋律，不照搬现成曲。')
        plan_instruction += '\n当前可生成调性清单：' + ', '.join(supported) + '。只从清单中选择；不要声称满足不支持的指定调性。'
        if regeneration_constraints:
            plan_instruction+='必须保持tempo_bpm=%s,key_signature=%s。'%(regeneration_constraints.tempo_bpm,regeneration_constraints.key_signature)
        def check_plan(plan):
            require_tempo(plan.tempo_bpm)
            tonic,minor=tonal_key(plan.key_signature)
            if requested_key and (tonic, minor) != requested_key:
                raise ValueError('key must match explicitly requested key; do not silently transpose')
            if plan.degrees[-2:]!=[5,1]: raise ValueError('last two degrees must be 5,1')
            if any(a in (5,7) and b in (2,4) for a,b in zip(plan.degrees,plan.degrees[1:])):
                raise ValueError('dominant cannot move directly to subdominant in current scope')
            if len(plan.degrees)*4*60/plan.tempo_bpm>57: raise ValueError('planned duration exceeds 57 seconds')
            if regeneration_constraints and (plan.tempo_bpm!=regeneration_constraints.tempo_bpm or plan.key_signature!=regeneration_constraints.key_signature):
                raise ValueError('tempo/key must match source exactly')
            for degree in plan.degrees:
                if not catalog(tonic,minor,degree): raise ValueError('no playable voicings for this degree/key')
            if not any(compatible(o,catalog(tonic,minor,1),tonic) for o in catalog(tonic,minor,5)):
                raise ProviderError('unsupported_key', '所选调性暂不支持当前指型范围，请改用C大调或A小调；未交付其他调性作品。')
            return tonic,minor
        plan,(tonic,minor)=self._request_checked(prompt,plan_instruction,HarmonyPlan,check_plan,receipts)
        if self.progress:self.progress('和声规划已通过，正在逐小节创作并检查旋律…')
        bars=[];choices=[];last_dominant=None
        for index,degree in enumerate(plan.degrees):
            self.current_bar = index + 1
            options=list(catalog(tonic,minor,degree))
            if index==len(plan.degrees)-2:
                options=[o for o in options if compatible(o,catalog(tonic,minor,1),tonic)]
            if index==len(plan.degrees)-1: options=compatible(last_dominant,options,tonic)
            options=options[:6]
            instruction=('只创作当前一小节，选一个给定voicing_index；每个旋律音选其melody_tones的tone_index。'
                         'tones是所选指型内旋律音的tone_index，null表示休止。不要写MIDI数字或另造音高。'
                         'cells必须恰好四个，每个cell是一拍；pattern选择q四分，ee两个八分，ess八分+两个十六分，'
                         'sse两个十六分+八分，ses十六分+八分+十六分，ssss四个十六分，ds附点八分+十六分，sd十六分+附点八分。'
                         '对应tones数量必须与该组合的音符数相同，程序计算起点与时值。'
                         '八分为主，适量成组十六分，旋律有动机和变化，避免机械音阶或整小节长音。'
                         '伴奏与音符时间由所选内容计算，不能编造或更改技术字段。'
                         '当前创作计划：'+plan.creative_plan+'；第%s/%s小节，和声%s。'%(index+1,len(plan.degrees),options[0]['chord'])+
                         '\n可选指型与旋律音：'+json.dumps(public_options(options),ensure_ascii=False))
            if choices:
                instruction+='\n此前实际小节，用于动机重复与发展：'+json.dumps([c.model_dump(mode='json') for c in choices[-2:]],ensure_ascii=False)
                instruction+='\n此前旋律实际音高：'+json.dumps([[n.midi_pitch for n in b.notes if n.voice=='melody'] for b in bars[-2:]])
            penultimate=index==len(plan.degrees)-2
            if penultimate: instruction+='\n旋律最后用属和弦根音或五音，避免最后的旋律导音悬在边界；伴奏导音将连接到下一小节主音。'
            final=index==len(plan.degrees)-1
            if final:instruction+='\n最后旋律音必须选择主音（音级%s），持续至小节末尾，需有前面的动机呼应与收束。'%NAMES[tonic]
            def check_choice(choice):
                bar,option=build_bar(choice,options)
                last_melody=[n for n in bar.notes if n.voice=='melody'][-1]
                if penultimate and last_melody.offset_tick+last_melody.duration_ticks==1920 and last_melody.midi_pitch%12==(tonic-1)%12:
                    raise ValueError('last melody cannot leave a leading tone unresolved at boundary; end on dominant root or fifth')
                if final and (last_melody.midi_pitch%12!=tonic or last_melody.offset_tick+last_melody.duration_ticks!=1920):
                    raise ValueError('last melody tone must be tonic and sustain to bar end; do not end with a rest')
                partial=CompactCandidate(creative_plan=plan.creative_plan,title=plan.title,tempo_bpm=plan.tempo_bpm,
                                         key_signature=plan.key_signature,bars=bars+[bar])
                piece=expand_candidate(partial,prompt,str(uuid.uuid4())).composition
                assign_fingering(piece)
                return bar,option
            choice,(bar,option)=self._request_checked(prompt,instruction,BarChoice,check_choice,receipts)
            choices.append(choice);bars.append(bar)
            if index==len(plan.degrees)-2:last_dominant=option
            if self.progress:self.progress('已检查第%s/%s小节，尚未完成导出…'%(index+1,len(plan.degrees)))
        compact=CompactCandidate(creative_plan=plan.creative_plan,title=plan.title,tempo_bpm=plan.tempo_bpm,
                                 key_signature=plan.key_signature,bars=bars)
        candidate=expand_candidate(compact,prompt,str(uuid.uuid4()))
        candidate=candidate.model_copy(update={'composition':candidate.composition.model_copy(update={'generator_version':'qwen-staged-2'})})
        receipt={'mode':'staged-ai-v1','steps':receipts,'bar_developments':[c.development for c in choices],
                 'estimated_cost_cny':str(sum((Decimal(r['estimated_cost_cny']) for r in receipts),Decimal('0')))}
        return candidate,receipt
