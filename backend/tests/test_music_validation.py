import json
from pathlib import Path

import pytest
from app.music.validation import MusicValidationError, validate_json


def fixture():
    return json.loads((Path(__file__).parents[1] / 'fixtures' / 'diagnostic-fingerstyle.json').read_text())


def test_parallel_voices_use_one_timeline():
    data = fixture()
    data['tempo_bpm'] = 120.0
    _, summary = validate_json(json.dumps(data))
    assert summary.end_tick == 3840
    assert summary.performance_seconds == 4.0
    assert summary.note_count == 12


@pytest.mark.parametrize('case,expected_path,rule', [
    ('too-long', 'measures', 'performance_duration'),
    ('wrong-pitch', 'measures.0.events.0.midi_pitch', 'pitch_mapping'),
    ('tuning', 'tuning', 'standard_tuning'),
    ('boundary', 'measures.0.events.0', 'event_boundary'),
    ('note-length', 'measures.0.events.0.duration_ticks', 'note_rhythm'),
    ('bar-length', 'measures.0.duration_ticks', 'bar_rhythm'),
    ('bar-start', 'measures.1.start_tick', 'bar_timeline'),
    ('local-tempo', 'measures.0.events.0.tempo_bpm', 'structure'),
    ('local-key', 'measures.0.key_signature', 'structure'),
    ('percussion', 'measures.0.events.0.technique', 'structure'),
    ('orphan-tie', 'measures.0.events.0.tie', 'tie'),
    ('duplicate', 'measures.0.events.1.id', 'unique_id'),
])
def test_rejects_locatable_music_errors(case, expected_path, rule):
    data = fixture()
    bar, event = data['measures'][0], data['measures'][0]['events'][0]
    if case == 'too-long': data['tempo_bpm'] = 7.0
    elif case == 'wrong-pitch': event['midi_pitch'] += 1
    elif case == 'tuning': data['tuning']['6'] = 38
    elif case == 'boundary': event['onset_tick'] = 1800
    elif case == 'note-length': event['duration_ticks'] = 900
    elif case == 'bar-length': bar['duration_ticks'] = 1800
    elif case == 'bar-start': data['measures'][1]['start_tick'] = 1900
    elif case == 'local-tempo': event['tempo_bpm'] = 90.0
    elif case == 'local-key': bar['key_signature'] = 'G'
    elif case == 'percussion': event['technique'] = 'percussion'
    elif case == 'orphan-tie': event['tie'] = 'stop'
    elif case == 'duplicate': bar['events'][1]['id'] = event['id']
    with pytest.raises(MusicValidationError) as failure:
        validate_json(json.dumps(data))
    assert any(i.path == expected_path and i.rule == rule for i in failure.value.issues)


def test_sixteenth_and_dotted_notation_without_serializing_voices():
    data = fixture()
    event = data['measures'][0]['events'][1]
    event.update(notation_duration=16, duration_ticks=180, dotted=True)
    _, result = validate_json(json.dumps(data))
    assert result.performance_seconds == 6.0


def test_nonfinite_tempo_fails_closed():
    data = fixture()
    data['tempo_bpm'] = float('inf')
    with pytest.raises(MusicValidationError) as failure:
        validate_json(json.dumps(data))
    assert any(i.rule == 'tempo' for i in failure.value.issues)


def test_sixty_seconds_is_performance_only_not_audio_acceptance():
    data = fixture()
    data['tempo_bpm'] = 8.0
    _, result = validate_json(json.dumps(data))
    assert result.performance_seconds == 60.0


def test_candidate_envelope_and_invalid_json():
    _, result = validate_json(json.dumps({'creative_plan': '诊断', 'composition': fixture()}))
    assert result.performance_seconds == 6.0
    with pytest.raises(MusicValidationError) as failure:
        validate_json('{')
    assert failure.value.issues[0].rule == 'json'
