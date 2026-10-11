"""Task06: bounded fingering search; never claims human playability from BPM alone."""
from dataclasses import dataclass
from itertools import groupby
from typing import Optional

from app.music.validation import MusicIssue, MusicValidationError, validate_composition
from app.schemas.composition import Composition, STANDARD_TUNING


@dataclass(frozen=True)
class FingeringRules:
    max_fret: int = 7
    preferred_max_fret: int = 5
    high_fret_percent: int = 10
    max_pressed_span: int = 3
    max_position_shift: int = 3


CONFIRMED_RULES = FingeringRules()


@dataclass(frozen=True)
class FingeringSummary:
    note_count: int
    high_fret_count: int
    maximum_pressed_span: int
    maximum_position_shift: int
    difficulty_reference_bpm: float


def _notes(piece):
    return [(event, f'measures.{bi}.events.{ei}')
            for bi, bar in enumerate(piece.measures) for ei, event in enumerate(bar.events)
            if event.kind == 'note']


def validate_fingering(piece: Composition, rules=CONFIRMED_RULES):
    validate_composition(piece)
    notes = _notes(piece)
    issues = []
    high_count = sum(e.fret > rules.preferred_max_fret for e, _ in notes)
    for event, path in notes:
        if event.fret > rules.max_fret:
            issues.append(MusicIssue(path + '.fret', 'max_fret', f'不能超过第{rules.max_fret}品'))
    if high_count * 100 > len(notes) * rules.high_fret_percent:
        issues.append(MusicIssue('measures', 'high_fret_ratio',
                                 f'高于第{rules.preferred_max_fret}品的音符为{high_count}/{len(notes)}，超过{rules.high_fret_percent}%'))
    moments = sorted({value for e, _ in notes for value in (e.onset_tick, e.onset_tick + e.duration_ticks)})
    previous_base = None
    max_span = max_shift = 0
    for tick in moments:
        active = [(e, p) for e, p in notes if e.onset_tick <= tick < e.onset_tick + e.duration_ticks]
        strings = {}
        for event, path in active:
            if event.string in strings:
                issues.append(MusicIssue(path + '.string', 'same_string_overlap',
                                         f'tick {tick}与{strings[event.string]}同时占用同一根弦'))
            strings[event.string] = path
        pressed = [e.fret for e, _ in active if e.fret > 0]
        if not pressed:
            # Open strings don't require a fret or establish a new hand position.
            continue
        low, high = min(pressed), max(pressed)
        span = high - low
        max_span = max(max_span, span)
        if span > rules.max_pressed_span:
            issues.append(MusicIssue(f'timeline.tick.{tick}', 'pressed_span',
                                     f'同时按住第{low}—{high}品，品位差{span}超过{rules.max_pressed_span}'))
        if previous_base is not None:
            shift = abs(low - previous_base)
            max_shift = max(max_shift, shift)
            if shift > rules.max_position_shift:
                issues.append(MusicIssue(f'timeline.tick.{tick}', 'position_shift',
                                         f'最低按弦品位从{previous_base}移到{low}，超过{rules.max_position_shift}品'))
        previous_base = low
    if issues:
        raise MusicValidationError(issues)
    return FingeringSummary(len(notes), high_count, max_span, max_shift, piece.tempo_bpm)


@dataclass
class _State:
    assignments: dict
    active: list
    previous_base: Optional[int]
    high_count: int
    fret_sum: int


def assign_fingering(piece: Composition, rules=CONFIRMED_RULES, beam_width=32, search_limit=50000):
    """Reposition notes without changing pitches, timing, voices, BPM, key or the source object.

    Bounded beam search prefers low frets; failing the search is explicit, not proof no
    human fingering exists. Only returned results pass all confirmed automatic rules.
    """
    validate_composition(piece)
    notes = sorted(_notes(piece), key=lambda item: (item[0].onset_tick, item[0].id))
    high_allowance = len(notes) * rules.high_fret_percent // 100
    tied_predecessors = {}
    for event, _ in notes:
        if event.tie in ('continue', 'stop'):
            tied_predecessors[event.id] = next(previous.id for previous, _ in notes
                if previous.voice == event.voice and previous.string == event.string
                and previous.midi_pitch == event.midi_pitch
                and previous.onset_tick + previous.duration_ticks == event.onset_tick
                and previous.tie in ('start', 'continue'))
    states = [_State({}, [], None, 0, 0)]
    visited = 0
    for tick, group_iter in groupby(notes, key=lambda item: item[0].onset_tick):
        group = list(group_iter)
        survivors = []
        for state in states:
            active = [item for item in state.active if item[1] > tick]

            def place(index, assignments, held, high_count, fret_sum):
                nonlocal visited
                visited += 1
                if visited > search_limit:
                    raise MusicValidationError([MusicIssue('measures', 'fingering_search_limit',
                        '指型搜索达到计算上限，未交付结果；这不代表不存在可弹指法')])
                if index == len(group):
                    pressed = [item[3] for item in held if item[3] > 0]
                    base = min(pressed) if pressed else state.previous_base
                    if pressed and state.previous_base is not None and abs(base - state.previous_base) > rules.max_position_shift:
                        return
                    survivors.append(_State(assignments, held, base, high_count, fret_sum))
                    return
                event, _ = group[index]
                choices = [(string, event.midi_pitch - pitch) for string, pitch in STANDARD_TUNING.items()
                           if 0 <= event.midi_pitch - pitch <= rules.max_fret]
                choices.sort(key=lambda choice: (choice[1] > rules.preferred_max_fret, choice[1], choice[0]))
                for string, fret in choices:
                    if any(item[2] == string for item in held):
                        continue
                    predecessor = tied_predecessors.get(event.id)
                    if predecessor and assignments[predecessor][0] != string:
                        continue
                    new_high = high_count + int(fret > rules.preferred_max_fret)
                    if new_high > high_allowance:
                        continue
                    pressed = [item[3] for item in held if item[3] > 0] + ([fret] if fret > 0 else [])
                    if pressed and max(pressed) - min(pressed) > rules.max_pressed_span:
                        continue
                    updated = dict(assignments)
                    updated[event.id] = (string, fret)
                    place(index + 1, updated,
                          held + [(event.id, event.onset_tick + event.duration_ticks, string, fret)],
                          new_high, fret_sum + fret)

            place(0, state.assignments, active, state.high_count, state.fret_sum)
        if not survivors:
            raise MusicValidationError([MusicIssue(f'timeline.tick.{tick}', 'fingering_unresolved',
                '本轮搜索未找到满足同弦、跨度、换把和高品位限制的指型；没有修改音高或放宽规则')])
        survivors.sort(key=lambda state: (state.high_count, state.fret_sum))
        states = survivors[:beam_width]
    # Recheck every timeline boundary, including held-note release positions.
    for state in states:
        result = piece.model_copy(deep=True)
        for event, _ in _notes(result):
            event.string, event.fret = state.assignments[event.id]
        try:
            summary = validate_fingering(result, rules)
            return result, summary
        except MusicValidationError:
            continue
    raise MusicValidationError([MusicIssue('measures', 'fingering_unresolved', '搜索候选未通过最终指型检查，未交付作品')])
