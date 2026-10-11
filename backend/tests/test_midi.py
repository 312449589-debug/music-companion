import io
from pathlib import Path

import mido
import pytest
from app.music.midi import midi_bytes
from app.music.validation import MusicValidationError
from app.schemas.composition import Composition


def fixture():
    return Composition.model_validate_json((Path(__file__).parents[1] / 'fixtures' / 'diagnostic-fingerstyle.json').read_text())


def read_notes(data):
    file = mido.MidiFile(file=io.BytesIO(data), charset='utf-8')
    notes, events, active = [], [], {}
    tick = 0
    for message in file.tracks[1]:
        assert message.time >= 0
        tick += message.time
        if message.type in ('note_on', 'note_off'):
            identity = (message.channel, message.note)
            events.append((tick, message.type, identity))
            if message.type == 'note_on':
                assert identity not in active
                active[identity] = tick
            else:
                start = active.pop(identity)
                notes.append((message.channel + 1, message.note, start, tick - start))
    assert not active
    return file, sorted(notes), events


def test_roundtrip_matches_parallel_source_and_open_strings():
    piece = fixture()
    file, actual, events = read_notes(midi_bytes(piece))
    expected = sorted((e.string, e.midi_pitch, e.onset_tick, e.duration_ticks)
                      for bar in piece.measures for e in bar.events if e.kind == 'note')
    assert actual == expected
    assert file.length == 6.0
    assert file.ticks_per_beat == piece.ppq
    assert len([e for e in events if e[0] == 0 and e[1] == 'note_on']) == 2
    programs = [m for m in file.tracks[1] if m.type == 'program_change']
    assert all(m.program == 24 and m.channel != 9 for m in programs)


def test_repeated_note_off_precedes_next_on():
    _, _, events = read_notes(midi_bytes(fixture()))
    boundary = [kind for tick, kind, identity in events if tick == 3360 and identity == (0, 64)]
    assert boundary == ['note_off']
    boundary = [kind for tick, kind, identity in events if tick == 2880 and identity == (0, 64)]
    assert boundary == ['note_off', 'note_on']


def test_same_pitch_different_strings_keeps_independent_channels():
    piece = fixture()
    piece.measures[0].events[0].string = 2
    piece.measures[0].events[0].fret = 5
    piece.measures[0].events[0].midi_pitch = 64
    _, notes, _ = read_notes(midi_bytes(piece))
    assert (2, 64, 0, 960) in notes and (1, 64, 0, 480) in notes


def test_tie_is_one_sustained_attack():
    piece = fixture()
    first, second = piece.measures[0].events[0], piece.measures[0].events[3]
    first.tie, second.tie = 'start', 'stop'
    second.string, second.fret, second.midi_pitch = first.string, first.fret, first.midi_pitch
    _, notes, _ = read_notes(midi_bytes(piece))
    assert (5, 48, 0, 1920) in notes
    assert len(notes) == 11


def test_overlapping_same_channel_pitch_is_rejected():
    piece = fixture()
    piece.measures[0].events[1].string = 5
    piece.measures[0].events[1].fret = 3
    piece.measures[0].events[1].midi_pitch = 48
    with pytest.raises(MusicValidationError) as failure:
        midi_bytes(piece)
    assert failure.value.issues[0].rule == 'midi_overlap'


def test_expression_adds_voice_balance_without_changing_pitch_or_timing():
    piece=fixture();before=piece.model_dump_json()
    file,actual,_=read_notes(midi_bytes(piece))
    expected=sorted((e.string,e.midi_pitch,e.onset_tick,e.duration_ticks) for b in piece.measures for e in b.events if e.kind=='note')
    assert actual==expected and piece.model_dump_json()==before
    tick=0; velocities={}
    for message in file.tracks[1]:
        tick+=message.time
        if message.type=='note_on':velocities[(tick,message.note)]=message.velocity
    assert velocities[(0,64)]>velocities[(0,48)]
    assert len(set(velocities.values()))>2
