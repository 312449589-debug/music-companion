from pathlib import Path
from app.schemas.composition import Composition
from app.music.phrasing import phrase_diagnostics


def piece_with_rhythm(offsets, sustain=False):
    piece = Composition.model_validate_json((Path(__file__).parents[1] / 'fixtures/diagnostic-fingerstyle.json').read_text())
    original = piece.measures[0].events[0]
    for bar in piece.measures:
        bar.events = [original.model_copy(update={'id': f'{bar.order}-{i}', 'kind': 'note', 'voice': 'melody',
                     'onset_tick': bar.start_tick + offset, 'duration_ticks': 480}) for i, offset in enumerate(offsets)]
        if sustain:
            bar.events.append(original.model_copy(update={'id': f'{bar.order}-bass', 'kind': 'note', 'voice': 'accompaniment',
                              'onset_tick': bar.start_tick, 'duration_ticks': bar.duration_ticks}))
    return piece


def test_detects_previous_mechanical_half_bar_structure_without_mutating_notes():
    piece = piece_with_rhythm([0, 480]); before = piece.model_dump_json()
    result = phrase_diagnostics(piece)
    assert result['repeated_half_bar_silence'] is True
    assert result['all_melody_rhythms_identical'] is True
    assert all(b['silent_tail_ticks'] == 960 and b['sounding_ticks'] == 960 for b in result['bars'])
    assert piece.model_dump_json() == before


def test_sustained_accompaniment_is_not_mistaken_for_silence_or_counted_twice():
    result = phrase_diagnostics(piece_with_rhythm([0, 480], sustain=True))
    assert result['repeated_half_bar_silence'] is False
    assert all(b['sounding_ticks'] == 1920 and b['silent_tail_ticks'] == 0 for b in result['bars'])


def test_continuous_or_varied_phrase_does_not_match_previous_failure_pattern():
    result = phrase_diagnostics(piece_with_rhythm([0, 480, 960, 1440]))
    assert result['all_melody_rhythms_identical'] is True
    assert result['repeated_half_bar_silence'] is False
    piece = piece_with_rhythm([0, 480]);piece.measures[1].events[1].onset_tick += 240
    result = phrase_diagnostics(piece)
    assert result['all_melody_rhythms_identical'] is False
    assert result['repeated_half_bar_silence'] is False
