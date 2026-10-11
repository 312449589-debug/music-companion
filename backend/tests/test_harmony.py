from pathlib import Path
import pytest
from app.schemas.composition import Composition
from app.music.harmony import validate_harmony
from app.music.validation import MusicValidationError
from app.music.fingering import assign_fingering


def piece():
    return Composition.model_validate_json((Path(__file__).parents[1]/'fixtures/functional-fingerstyle.json').read_text())


def rejected(item, rule):
    with pytest.raises(MusicValidationError) as failure: validate_harmony(item)
    assert rule in [issue.rule for issue in failure.value.issues]


def test_actual_functional_phrase_and_tonic_closure_survive_fingering():
    item=piece(); report=validate_harmony(item)
    assert report['functions']==['T','S','D','T'] and report['actual_final_tonic_triad']
    assigned,_=assign_fingering(item)
    assert validate_harmony(assigned)==report


def test_fake_chord_labels_and_unresolved_melody_are_rejected():
    item=piece();item.measures[1].chord='C'
    rejected(item,'harmonic_support')
    item=piece();item.measures[0].events[2].midi_pitch=66
    rejected(item,'nonchord_resolution')


def test_ending_root_alone_does_not_count_as_tonic_triad():
    item=piece();item.measures[-1].events=[item.measures[-1].events[0],item.measures[-1].events[-1]]
    rejected(item,'final_sonority')
    item=piece();item.measures[-1].events[-1].midi_pitch=64
    rejected(item,'final_melody_tonic')


def test_tonic_without_dominant_preparation_and_shortened_ending_rejected():
    item=piece();item.measures[-2].chord='F'
    rejected(item,'closing_cadence')
    item=piece();item.measures[-1].events[1].duration_ticks=480
    rejected(item,'final_sustain')


def test_real_neighbor_tone_can_resolve_instead_of_forbidding_all_nonchord_tones():
    item=piece();item.measures[0].events[2].midi_pitch=65
    # E-F-E: a weak-beat neighbor, returning to E at the next adjacent attack.
    item.measures[0].events[4].midi_pitch=64
    validate_harmony(item)


def test_bad_chord_and_unknown_key_are_clear_errors():
    item=piece();item.measures[0].chord='made-up'
    rejected(item,'chord_symbol')
    item=piece();item.key_signature='not-a-key'
    rejected(item,'harmony_key')


def test_minor_uses_major_dominant_and_minor_final_triad():
    item=piece();item.key_signature='A minor'
    chords=['Am','Dm','E7','Am']
    for bi,bar in enumerate(item.measures):
        for e in bar.events:
            adjust=8 if (bi in (0,3) and e.midi_pitch%12==4) or (bi==1 and e.midi_pitch%12==9) else 9
            e.midi_pitch+=adjust
        bar.chord=chords[bi]
    assert validate_harmony(item)['cadence']=='V–i'
    item.measures[-2].chord='Em'
    rejected(item,'functional_chord')


def test_seventh_label_requires_seventh_and_leading_tone_resolves_in_register():
    item=piece()
    for e in item.measures[-2].events:
        if e.midi_pitch%12==5:e.midi_pitch=67
    rejected(item,'seventh_evidence')
    item=piece();item.measures[-2].events[1].midi_pitch+=24
    rejected(item,'leading_tone_resolution')
