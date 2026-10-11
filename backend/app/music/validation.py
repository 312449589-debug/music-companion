"""Task 05: musical consistency, not fingering or audio-file acceptance."""
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import List

from pydantic import ValidationError
from app.schemas.composition import Composition, STANDARD_TUNING


@dataclass(frozen=True)
class MusicIssue:
    path: str
    rule: str
    message: str


class MusicValidationError(ValueError):
    def __init__(self, issues: List[MusicIssue]):
        self.issues = issues
        super().__init__('音乐基础检查失败：' + '; '.join(i.path + ': ' + i.message for i in issues))


@dataclass(frozen=True)
class MusicSummary:
    performance_seconds: float
    end_tick: int
    note_count: int


def validate_json(raw: str):
    """Accept either a Composition JSON or task04's candidate envelope."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and 'composition' in data:
            data = data['composition']
        piece = Composition.model_validate_json(json.dumps(data))
    except (ValueError, TypeError) as error:
        if isinstance(error, ValidationError):
            issues = []
            for item in error.errors(include_input=False, include_url=False):
                path = '.'.join(map(str, item['loc']))
                field = str(item['loc'][-1]) if item['loc'] else ''
                if field in ('tempo_bpm', 'key_signature') and len(item['loc']) > 1:
                    message = '速度和调性只能在作品层设置，不支持局部变化'
                elif field in ('technique', 'techniques') or item.get('input') == 'percussion':
                    message = '本版不支持打板或其他特殊技巧'
                else:
                    message = item['msg']
                issues.append(MusicIssue(path, 'structure', message))
        else:
            issues = [MusicIssue('$', 'json', '不是可读取的音乐JSON')]
        raise MusicValidationError(issues) from None
    return piece, validate_composition(piece)


def validate_composition(piece: Composition) -> MusicSummary:
    issues = []

    def fail(path, rule, message):
        issues.append(MusicIssue(path, rule, message))

    finite_tempo = math.isfinite(piece.tempo_bpm) and piece.tempo_bpm > 0
    if not finite_tempo:
        fail('tempo_bpm', 'tempo', 'BPM必须是有限的正数')
    if not piece.key_signature.strip():
        fail('key_signature', 'key', '调性不能为空白')
    if piece.tuning != STANDARD_TUNING:
        fail('tuning', 'standard_tuning', '必须采用标准定弦：一弦64、二弦59、三弦55、四弦50、五弦45、六弦40')

    bar_ticks = Fraction(piece.ppq * 4 * piece.time_signature.numerator, piece.time_signature.denominator)
    cursor = 0
    last_event_end = 0
    note_count = 0
    seen_bar_ids, seen_event_ids = set(), set()
    notes = []
    for bar_index, bar in enumerate(piece.measures):
        path = f'measures.{bar_index}'
        if bar.id in seen_bar_ids:
            fail(path + '.id', 'unique_id', '小节编号重复')
        seen_bar_ids.add(bar.id)
        if bar.order != bar_index + 1:
            fail(path + '.order', 'bar_order', '小节顺序必须从1开始连续编号')
        if bar.start_tick != cursor:
            fail(path + '.start_tick', 'bar_timeline', f'小节应从绝对位置{cursor}开始，不能重叠或跳空')
        if bar.duration_ticks != bar_ticks:
            fail(path + '.duration_ticks', 'bar_rhythm', f'小节长度与拍号不符，应为{bar_ticks} ticks')
        bar_end = bar.start_tick + bar.duration_ticks
        cursor = bar_end
        for event_index, event in enumerate(bar.events):
            event_path = path + f'.events.{event_index}'
            if event.id in seen_event_ids:
                fail(event_path + '.id', 'unique_id', '音符/休止事件编号重复')
            seen_event_ids.add(event.id)
            end = event.onset_tick + event.duration_ticks
            last_event_end = max(last_event_end, end)
            if event.onset_tick < bar.start_tick or end > bar_end:
                fail(event_path, 'event_boundary', '事件必须位于所属小节内；跨小节延音需拆为连音事件')
            duration = Fraction(piece.ppq * 4, event.notation_duration)
            if event.dotted:
                duration *= Fraction(3, 2)
            if event.duration_ticks != duration:
                fail(event_path + '.duration_ticks', 'note_rhythm', f'实际长度与谱面时值不符，应为{duration} ticks')
            if event.kind == 'note':
                note_count += 1
                expected = STANDARD_TUNING[event.string] + event.fret
                if event.midi_pitch != expected:
                    fail(event_path + '.midi_pitch', 'pitch_mapping', f'弦号和品位对应MIDI {expected}，与声明音高不符')
                notes.append((event, event_path))
            elif event.tie != 'none':
                fail(event_path + '.tie', 'tie', '休止符不能使用延音连线')

    # A tie joins identical sounding notes on the same string/voice at exact boundaries.
    for event, path in notes:
        same_lane = [(other, other_path) for other, other_path in notes
                     if other.id != event.id and other.voice == event.voice
                     and other.string == event.string and other.midi_pitch == event.midi_pitch]
        if event.tie in ('start', 'continue'):
            following = [other for other, _ in same_lane
                         if other.onset_tick == event.onset_tick + event.duration_ticks
                         and other.tie in ('continue', 'stop')]
            if len(following) != 1:
                fail(path + '.tie', 'tie', '延音起点必须连接唯一、同音同弦且紧邻的继续/终点')
        if event.tie in ('continue', 'stop'):
            preceding = [other for other, _ in same_lane
                         if other.onset_tick + other.duration_ticks == event.onset_tick
                         and other.tie in ('start', 'continue')]
            if len(preceding) != 1:
                fail(path + '.tie', 'tie', '延音继续/终点缺少唯一、紧邻的起点')

    # Parallel voices occupy one timeline. Include complete bars/trailing silence.
    end_tick = max(cursor, last_event_end)
    seconds = end_tick / piece.ppq * 60 / piece.tempo_bpm if finite_tempo else 0
    if seconds > 60:
        fail('measures', 'performance_duration', f'演奏时长{seconds:.3f}秒，超过60秒上限')
    if not note_count:
        fail('measures', 'empty_music', '作品至少需要一个可发声音符')
    if issues:
        raise MusicValidationError(issues)
    return MusicSummary(seconds, end_tick, note_count)
