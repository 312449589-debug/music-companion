"""Structural contract only; musical/playability checks belong to task 05/06."""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Actual sounding MIDI pitches, keyed by string number (1 = highest string).
STANDARD_TUNING = {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TimeSignature(ContractModel):
    numerator: int = Field(gt=0)
    denominator: Literal[1, 2, 4, 8, 16]


class MusicEvent(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["note", "rest"]
    voice: Literal["melody", "accompaniment"]
    onset_tick: int = Field(ge=0, description="Absolute position from the start of the piece")
    duration_ticks: int = Field(gt=0)
    notation_duration: Literal[1, 2, 4, 8, 16]
    dotted: bool = False
    tie: Literal["none", "start", "continue", "stop"] = "none"
    string: Optional[int] = Field(default=None, ge=1, le=6)
    fret: Optional[int] = Field(default=None, ge=0)
    midi_pitch: Optional[int] = Field(default=None, ge=0, le=127)

    @model_validator(mode="after")
    def note_or_rest_fields(self):
        pitches = (self.string, self.fret, self.midi_pitch)
        if self.kind == "note" and any(value is None for value in pitches):
            raise ValueError("note requires string, fret and midi_pitch")
        if self.kind == "rest" and any(value is not None for value in pitches):
            raise ValueError("rest cannot contain string, fret or midi_pitch")
        return self


class Measure(ContractModel):
    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    start_tick: int = Field(ge=0)
    duration_ticks: int = Field(gt=0)
    chord: Optional[str] = None
    events: List[MusicEvent] = Field(min_length=1)


class RegenerationConstraints(ContractModel):
    tempo_bpm: float = Field(gt=0)
    key_signature: str = Field(min_length=1)


class Composition(ContractModel):
    schema_version: Literal["1.0"]
    composition_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    origin: Literal["diagnostic", "ai"]
    prompt: str = Field(min_length=1)
    generator_version: str = Field(min_length=1)
    seed: Optional[int] = None
    source_composition_id: Optional[str] = None
    constraints: Optional[RegenerationConstraints] = None
    tempo_bpm: float = Field(gt=0)
    key_signature: str = Field(min_length=1)
    time_signature: TimeSignature
    ppq: int = Field(gt=0, description="Ticks per quarter note")
    tuning: Dict[int, int] = Field(description="String number -> actual sounding MIDI pitch")
    measures: List[Measure] = Field(min_length=1)

    # No trusted duration_seconds field: task 05 will derive it from event positions.
