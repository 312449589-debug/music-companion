"""Task08: absolute source events -> deterministic MIDI, no synthesis."""
import io
from pathlib import Path

import mido
from app.music.validation import MusicIssue, MusicValidationError, validate_composition


def attack_velocity(note, piece):
    # Deterministic phrasing affects attack strength only, never pitch or timing.
    melody = [e for b in piece.measures for e in b.events if e.kind == 'note' and e.voice == 'melody']
    beat = note.onset_tick % (piece.ppq * piece.time_signature.numerator)
    accent = 4 if beat == 0 else 2 if beat == piece.ppq * 2 else 0
    if note.voice == 'accompaniment': return 56 + accent
    peak = max((e.midi_pitch for e in melody), default=note.midi_pitch)
    lift = 5 if note.midi_pitch == peak else 0
    release = -7 if melody and note.onset_tick == max(e.onset_tick for e in melody) else 0
    return 76 + accent + lift + release


def midi_bytes(piece):
    summary = validate_composition(piece)
    if piece.ppq > 32767:
        raise MusicValidationError([MusicIssue('ppq', 'midi_resolution', 'MIDI的每拍tick数不能超过32767')])
    key = piece.key_signature.lower().replace(' ', '').replace('♯', '#').replace('♭', 'b')
    minor = key.endswith('minor') or key.endswith('m')
    if key.endswith('major'): key = key[:-5]
    elif key.endswith('minor'): key = key[:-5]
    elif minor: key = key[:-1]
    key = key[:1].upper() + key[1:] + ('m' if minor else '')
    try:
        key_message = mido.MetaMessage('key_signature', key=key)
        tempo_message = mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(piece.tempo_bpm))
    except (ValueError, KeyError) as error:
        raise MusicValidationError([MusicIssue('tempo_bpm/key_signature', 'midi_metadata',
                                               '速度或调性无法表示为标准MIDI元信息')]) from None
    file = mido.MidiFile(type=1, ticks_per_beat=piece.ppq, charset='utf-8')
    conductor = mido.MidiTrack()
    file.tracks.append(conductor)
    conductor.extend([mido.MetaMessage('track_name', name=piece.title), tempo_message,
                      mido.MetaMessage('time_signature', numerator=piece.time_signature.numerator,
                                       denominator=piece.time_signature.denominator), key_message,
                      mido.MetaMessage('end_of_track', time=summary.end_tick)])
    music = mido.MidiTrack()
    file.tracks.append(music)
    notes = [e for bar in piece.measures for e in bar.events if e.kind == 'note']
    for channel in sorted({e.string - 1 for e in notes}):
        music.append(mido.Message('program_change', channel=channel, program=24, time=0))
    events = []
    for note in notes:
        if note.tie in ('continue', 'stop'):
            continue
        end = note.onset_tick + note.duration_ticks
        continuation = note
        while continuation.tie in ('start', 'continue'):
            continuation = next(e for e in notes if e.voice == note.voice and e.string == note.string
                and e.midi_pitch == note.midi_pitch and e.onset_tick == end and e.tie in ('continue', 'stop'))
            end = continuation.onset_tick + continuation.duration_ticks
        channel = note.string - 1
        events.append((note.onset_tick, 1, note.id, mido.Message('note_on', channel=channel, note=note.midi_pitch, velocity=attack_velocity(note, piece))))
        events.append((end, 0, note.id, mido.Message('note_off', channel=channel, note=note.midi_pitch, velocity=0)))
    events.sort(key=lambda item: item[:3])  # off before on at the same tick
    active = set()
    previous = 0
    for tick, _, event_id, message in events:
        identity = (message.channel, message.note)
        if message.type == 'note_on':
            if identity in active:
                raise MusicValidationError([MusicIssue('events.' + event_id, 'midi_overlap',
                                                       '同弦同音重叠，不能可靠导出MIDI；需要先解决指型冲突')])
            active.add(identity)
        else:
            active.remove(identity)
        music.append(message.copy(time=tick - previous))
        previous = tick
    music.append(mido.MetaMessage('end_of_track', time=summary.end_tick - previous))
    output = io.BytesIO()
    file.save(file=output)
    return output.getvalue()


def export_midi(piece, destination: Path):
    data = midi_bytes(piece)  # fail before creating an output file
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination
