import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.composition import Composition, MusicEvent, STANDARD_TUNING

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "diagnostic-fingerstyle.json"


def test_fixture_retains_parallel_voices_and_tuning_after_round_trip():
    piece = Composition.model_validate_json(FIXTURE.read_text())
    assert piece.origin == "diagnostic"
    assert piece.tuning == STANDARD_TUNING
    assert piece.tuning[1] == 64 and piece.tuning[6] == 40
    first_notes = [x for x in piece.measures[0].events if x.onset_tick == 0]
    assert {x.voice for x in first_notes} == {"melody", "accompaniment"}
    assert Composition.model_validate_json(piece.model_dump_json()) == piece


@pytest.mark.parametrize("mutation,location", [
    ("string", ("measures", 0, "events", 0, "string")),
    ("missing", ("tempo_bpm",)),
    ("coercion", ("measures", 0, "events", 0, "duration_ticks")),
])
def test_structural_errors_are_localized(mutation, location):
    data = json.loads(FIXTURE.read_text())
    if mutation == "string":
        data["measures"][0]["events"][0]["string"] = 7
    elif mutation == "missing":
        data.pop("tempo_bpm")
    else:
        data["measures"][0]["events"][0]["duration_ticks"] = "960"
    with pytest.raises(ValidationError) as error:
        Composition.model_validate_json(json.dumps(data))
    assert location in [item["loc"] for item in error.value.errors()]


def test_note_requires_pitch_fields_and_rest_does_not_accept_them():
    event = json.loads(FIXTURE.read_text())["measures"][0]["events"][0]
    without_pitch = {k: v for k, v in event.items() if k not in {"string", "fret", "midi_pitch"}}
    with pytest.raises(ValidationError):
        MusicEvent.model_validate(without_pitch)
    rest = MusicEvent.model_validate({**without_pitch, "kind": "rest"})
    assert rest.string is None and rest.midi_pitch is None
    with pytest.raises(ValidationError):
        MusicEvent.model_validate({**event, "kind": "rest"})
