import json
from pathlib import Path

from app.music.alphatex import _rests, to_alphatex
from app.schemas.composition import Composition


def fixture():
    return Composition.model_validate_json((Path(__file__).parents[1] / 'fixtures' / 'diagnostic-fingerstyle.json').read_text())


def test_two_independent_voices_preserve_half_and_quarter_notes():
    tex = to_alphatex(fixture())
    assert tex.count('\\voice') == 2
    assert '0.1.4 3.1.4 1.2.4 0.1.4 |' in tex
    assert '3.5.2 2.4.2 |' in tex
    assert '\\tuning (E4 B3 G3 D3 A2 E2)' in tex
    assert '\\ks cmajor' in tex


def test_overlapping_bass_is_an_extra_notation_voice():
    piece = fixture()
    piece.measures[0].events[0].duration_ticks = 1920
    piece.measures[0].events[0].notation_duration = 1
    tex = to_alphatex(piece)
    assert tex.count('\\voice') == 3
    assert '3.5.1' in tex and 'r.2 2.4.2' in tex


def test_gap_rest_and_tie_are_explicit_without_modifying_source():
    piece = fixture()
    event = piece.measures[0].events[1]
    event.duration_ticks = 120
    event.notation_duration = 16
    before = piece.model_dump()
    tex = to_alphatex(piece)
    assert '0.1.16 r.8 {d}' in tex
    assert piece.model_dump() == before
    bass1, bass2 = piece.measures[0].events[0], piece.measures[0].events[3]
    bass1.tie, bass2.tie = 'start', 'stop'
    bass2.string, bass2.fret, bass2.midi_pitch = bass1.string, bass1.fret, bass1.midi_pitch
    assert '3.5.2 3.5{t}.2' in to_alphatex(piece)


def test_rests_can_combine_durations_when_greedy_choice_would_fail():
    assert sorted(_rests(300, 480)) == sorted(['r.16', 'r.16 {d}'])


def test_leading_chord_is_parsed_as_music_by_installed_alphatab():
    import shutil
    import subprocess
    import pytest

    root = Path(__file__).resolve().parents[2]
    module = root / 'frontend/node_modules/@coderline/alphatab/dist/alphaTab.mjs'
    node = shutil.which('node')
    if not node or not module.exists():
        pytest.skip('This integration check requires installed frontend dependencies and Node.js')
    piece = Composition.model_validate_json(
        (root / 'backend/fixtures/functional-fingerstyle.json').read_text())
    tex = to_alphatex(piece)
    script = (
        'import * as at from ' + json.dumps(module.as_uri()) + ';\n'
        'const importer = new at.importer.AlphaTexImporter();\n'
        'importer.initFromString(' + json.dumps(tex) + ', new at.Settings());\n'
        'const score = importer.readScore();\n'
        'const staff = score.tracks[0].staves[0];\n'
        'console.log(JSON.stringify(staff.bars.map(b => b.voices.map(v => '
        'v.beats.flatMap(beat => beat.notes.map(n => [n.string, n.fret]))))));\n'
    )
    result = subprocess.run([node, '--input-type=module'], input=script,
                            text=True, capture_output=True, check=True)
    notes = json.loads(result.stdout)
    assert len(notes) == 4
    # The first bass dyad must remain actual notes in a second voice.
    assert len(notes[0]) == 2
    # alphaTab internally numbers strings from the low E string.
    assert notes[0][1][:2] == [[2, 3], [3, 2]]
    assert len(notes[3][1]) == 3
