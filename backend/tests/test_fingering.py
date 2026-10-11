import json
from pathlib import Path

import pytest
from app.music.fingering import assign_fingering, validate_fingering
from app.music.validation import MusicValidationError, validate_json


def fixture():
    return json.loads((Path(__file__).parents[1] / 'fixtures' / 'diagnostic-fingerstyle.json').read_text())


def piece(data):
    return validate_json(json.dumps(data))[0]


def test_open_strings_do_not_expand_pressed_span():
    data = fixture()
    data['measures'][0]['events'][0].update(string=5, fret=4, midi_pitch=49)
    result = validate_fingering(piece(data))
    assert result.maximum_pressed_span <= 3
    assert result.difficulty_reference_bpm == 80


@pytest.mark.parametrize('case,rule', [('same-string', 'same_string_overlap'), ('wide-span', 'pressed_span'),
                                     ('max-fret', 'max_fret'), ('high-ratio', 'high_fret_ratio')])
def test_rejects_invalid_fingering(case, rule):
    data = fixture()
    event = data['measures'][0]['events'][1]
    if case == 'same-string': event.update(string=5, fret=0, midi_pitch=45)
    elif case == 'wide-span': event.update(string=1, fret=7, midi_pitch=71)
    elif case == 'max-fret': event.update(string=1, fret=8, midi_pitch=72)
    elif case == 'high-ratio':
        event.update(string=1, fret=6, midi_pitch=70)
        data['measures'][1]['events'][1].update(string=1, fret=6, midi_pitch=70)
    with pytest.raises(MusicValidationError) as error:
        validate_fingering(piece(data))
    assert any(issue.rule == rule for issue in error.value.issues)


def test_position_jump_is_checked_even_across_open_strings():
    data = fixture()
    for bar in data['measures']:
        for event in bar['events']:
            event.update(fret=0, midi_pitch={1:64, 2:59, 3:55, 4:50, 5:45, 6:40}[event['string']])
    data['measures'][0]['events'][0].update(fret=1, midi_pitch=46)
    data['measures'][1]['events'][4].update(fret=5, midi_pitch=69)
    with pytest.raises(MusicValidationError) as error:
        validate_fingering(piece(data))
    assert any(issue.rule == 'position_shift' for issue in error.value.issues)


def test_allocator_resolves_conflict_preserving_music_and_source():
    data = fixture()
    data['measures'][0]['events'][1].update(string=5, fret=5, midi_pitch=50)
    source = piece(data)
    before = source.model_dump()
    result, summary = assign_fingering(source)
    assert source.model_dump() == before
    assert result.tempo_bpm == source.tempo_bpm
    assert result.key_signature == source.key_signature
    for old_bar, new_bar in zip(source.measures, result.measures):
        for old, new in zip(old_bar.events, new_bar.events):
            assert (old.id, old.voice, old.onset_tick, old.duration_ticks, old.midi_pitch) == (
                new.id, new.voice, new.onset_tick, new.duration_ticks, new.midi_pitch)
    assert result.measures[0].events[1].string != result.measures[0].events[0].string
    assert summary.high_fret_count == 0


def test_insufficient_range_and_search_limit_fail_explicitly():
    data = fixture()
    data['measures'][0]['events'][1].update(string=1, fret=20, midi_pitch=84)
    with pytest.raises(MusicValidationError) as error:
        assign_fingering(piece(data))
    assert error.value.issues[0].rule == 'fingering_unresolved'
    with pytest.raises(MusicValidationError) as error:
        assign_fingering(piece(fixture()), search_limit=1)
    assert error.value.issues[0].rule == 'fingering_search_limit'


def test_tied_notes_keep_one_string_after_reassignment():
    data = fixture()
    data['measures'][0]['events'][0].update(string=5, fret=5, midi_pitch=50, tie='start')
    data['measures'][0]['events'][3].update(string=5, fret=5, midi_pitch=50, tie='stop')
    result, _ = assign_fingering(piece(data))
    assert result.measures[0].events[0].string == result.measures[0].events[3].string == 4


def test_one_high_note_in_twelve_is_allowed_and_bpm_stays_primary_reference():
    data = fixture()
    data['measures'][0]['events'][1].update(string=1, fret=6, midi_pitch=70)
    _, low_summary = assign_fingering(piece(data))
    data['tempo_bpm'] = 100.0
    _, fast_summary = assign_fingering(piece(data))
    assert low_summary.high_fret_count == fast_summary.high_fret_count == 1
    assert low_summary.difficulty_reference_bpm == 80.0
    assert fast_summary.difficulty_reference_bpm == 100.0
