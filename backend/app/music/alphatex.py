"""Convert the single music source into independent alphaTex notation voices."""
import json
import math
from fractions import Fraction
from itertools import groupby

from app.music.validation import MusicIssue, MusicValidationError, validate_composition


def _error(path, message):
    raise MusicValidationError([MusicIssue(path, 'alphatex', message)])


def _quoted(value):
    return json.dumps(' '.join(value.split()), ensure_ascii=False)


def _key(value):
    key = value.lower().replace(' ', '').replace('♯', '#').replace('♭', 'b')
    majors = ['cb', 'gb', 'db', 'ab', 'eb', 'bb', 'f', 'c', 'g', 'd', 'a', 'e', 'b', 'f#', 'c#']
    minors = ['ab', 'eb', 'bb', 'f', 'c', 'g', 'd', 'a', 'e', 'b', 'f#', 'c#', 'g#', 'd#', 'a#']
    if key in majors or key in [root + 'major' for root in majors]:
        return key
    if key.endswith('m') and key[:-1] in minors:
        return key[:-1] + 'minor'
    if key in [root + 'minor' for root in minors]:
        return key
    _error('key_signature', '当前谱面无法识别此调性，请使用C、C major、A minor等明确调性')


def _rests(ticks, ppq):
    durations = sorted([(Fraction(ppq * 4, denominator) * (Fraction(3, 2) if dotted else 1), denominator, dotted)
                        for denominator in [1, 2, 4, 8, 16] for dotted in [False, True]], reverse=True)
    durations = [item for item in durations if item[0].denominator == 1]
    unit = 0
    for length, _, _ in durations:
        unit = math.gcd(unit, int(length))
    if ticks % unit:
        _error('timeline', '空白时长无法用本版支持的休止时值表示，未移动音符位置')
    target = ticks // unit
    best = [None] * (target + 1)
    best[0] = []
    for position in range(1, target + 1):
        for length, denominator, dotted in durations:
            before = position - int(length) // unit
            if before >= 0 and best[before] is not None:
                candidate = best[before] + [f'r.{denominator}' + (' {d}' if dotted else '')]
                if best[position] is None or len(candidate) < len(best[position]):
                    best[position] = candidate
    if best[target] is None:
        _error('timeline', '空白时长无法用本版支持的休止时值表示，未移动音符位置')
    return best[target]


def to_alphatex(piece):
    validate_composition(piece)
    lanes = []
    assigned = {}
    all_notes = [e for bar in piece.measures for e in bar.events if e.kind == 'note']
    # Logical voices may contain overlapping sustained bass/arpeggios. Allocate
    # extra notation voices instead of shortening notes or serializing playback.
    for voice in ['melody', 'accompaniment']:
        events = sorted([e for bar in piece.measures for e in bar.events if e.voice == voice],
                        key=lambda e: (e.onset_tick, e.duration_ticks, e.notation_duration, e.dotted, e.kind, e.id))
        voice_lanes = []
        for _, group_iter in groupby(events, key=lambda e: (e.onset_tick, e.duration_ticks, e.notation_duration, e.dotted, e.kind)):
            group = list(group_iter)
            first = group[0]
            required_lanes = set()
            for event in group:
                if event.tie in ('continue', 'stop'):
                    predecessor = next(e for e in all_notes if e.voice == event.voice and e.string == event.string
                        and e.midi_pitch == event.midi_pitch and e.onset_tick + e.duration_ticks == event.onset_tick
                        and e.tie in ('start', 'continue'))
                    required_lanes.add(assigned[predecessor.id])
            if len(required_lanes) > 1:
                _error('events.' + first.id, '此连音和弦连接了不同谱面声部，无法无损表示')
            selected = next(iter(required_lanes)) if required_lanes else next(
                (index for index in voice_lanes if not lanes[index] or
                 lanes[index][-1][0].onset_tick + lanes[index][-1][0].duration_ticks <= first.onset_tick), None)
            if selected is None:
                selected = len(lanes)
                lanes.append([])
                voice_lanes.append(selected)
            elif lanes[selected] and lanes[selected][-1][0].onset_tick + lanes[selected][-1][0].duration_ticks > first.onset_tick:
                _error('events.' + first.id, '连音声部发生重叠，无法无损表示')
            lanes[selected].append(group)
            for event in group:
                assigned[event.id] = selected

    lines = [r'\title ' + _quoted(piece.title), r'\tempo ' + str(piece.tempo_bpm),
             r'\track "指弹吉他"', r'\staff {tabs}', r'\tuning (E4 B3 G3 D3 A2 E2)', r'\instrument 24', '.']
    for lane_index, lane in enumerate(lanes):
        # Separate voice metadata from a leading chord; otherwise alphaTab
        # consumes its parenthesized notes as arguments to the voice command.
        lines.append(r'\voice .')
        for bar_index, bar in enumerate(piece.measures):
            parts = []
            if lane_index == 0 and bar_index == 0:
                parts += [f'\\ts ({piece.time_signature.numerator} {piece.time_signature.denominator})', '\\ks ' + _key(piece.key_signature)]
            position = bar.start_tick
            for group in lane:
                first = group[0]
                if not bar.start_tick <= first.onset_tick < bar.start_tick + bar.duration_ticks:
                    continue
                parts.extend(_rests(first.onset_tick - position, piece.ppq))
                if first.kind == 'rest':
                    content = 'r'
                else:
                    notes = [f'{e.fret}.{e.string}' + ('{t}' if e.tie in ('continue', 'stop') else '') for e in group]
                    content = notes[0] if len(notes) == 1 else '(' + ' '.join(notes) + ')'
                parts.append(content + f'.{first.notation_duration}' + (' {d}' if first.dotted else ''))
                position = first.onset_tick + first.duration_ticks
            parts.extend(_rests(bar.start_tick + bar.duration_ticks - position, piece.ppq))
            lines.append(' '.join(parts) + (' |' if bar_index < len(piece.measures) - 1 else ''))
    return '\n'.join(lines) + '\n'
