import json
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.providers.budget import BudgetLedger
from app.providers.errors import ProviderError
from app.providers.qwen import QwenProvider, QwenSettings, CompactCandidate, expand_candidate

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'diagnostic-fingerstyle.json'


def settings(**overrides):
    return replace(QwenSettings('sk-test-not-a-real-key', 'qwen-plus',
                               'https://dashscope.aliyuncs.com/compatible-mode/v1',
                               Decimal('0.8'), Decimal('2')), **overrides)


def provider(tmp_path, handler, **overrides):
    ledger = BudgetLedger(tmp_path / 'budget.json', 200)
    return QwenProvider(settings(**overrides), ledger, httpx.Client(transport=httpx.MockTransport(handler)),
                        sleep=lambda _: None), ledger


def valid_response(request):
    payload = json.loads(request.content)
    data = json.loads(FIXTURE.read_text())
    if payload.get('stream'):
        content = json.dumps({'creative_plan': '测试创作替身', 'title': data['title'],
                              'tempo_bpm': data['tempo_bpm'], 'key_signature': data['key_signature'],
                              'bars': [{'chord': b['chord'], 'notes': [
                                  {'voice': e['voice'], 'offset_tick': e['onset_tick'] - b['start_tick'],
                                   'duration_ticks': e['duration_ticks'], 'midi_pitch': e['midi_pitch']}
                                  for e in b['events'] if e['kind'] == 'note']} for b in data['measures']]})
    else:
        data.update(origin='ai', generator_version='qwen-candidate-1', prompt=payload['messages'][1]['content'],
                    composition_id=re.search(r'composition_id必须为([a-f0-9-]+)', payload['messages'][0]['content']).group(1))
        content = json.dumps({'creative_plan': '仅供单元测试的模拟响应，不用于真实 API 验收。', 'composition': data})
    body = {
        'model': 'qwen-plus', 'usage': {'prompt_tokens': 100, 'completion_tokens': 200},
        'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
    if payload.get('stream'):
        content = body['choices'][0]['message']['content']
        chunks = [{'model': 'qwen-plus', 'choices': [{'delta': {'content': content[:80]}, 'finish_reason': None}]},
                  {'model': 'qwen-plus', 'choices': [{'delta': {'content': content[80:]}, 'finish_reason': 'stop'}]},
                  {'choices': [], 'usage': body['usage']}]
        text = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
        return httpx.Response(200, headers={'x-request-id': 'provider-test-123', 'content-type': 'text/event-stream'}, text=text)
    return httpx.Response(200, headers={'x-request-id': 'provider-test-123'}, json=body)


def test_parses_response_and_records_usage_without_secret(tmp_path):
    p, ledger = provider(tmp_path, valid_response)
    candidate, metadata = p.generate_candidate('温暖安静')
    assert candidate.composition.origin == 'ai'
    assert metadata['provider_request_id'] == 'provider-test-123'
    state = json.loads(ledger.path.read_text())
    assert state['attempts'][0]['status'] == 'candidate_ready'
    assert Decimal(state['attempts'][0]['accounted_cny']) == Decimal('0.00048')
    assert 'sk-test-not-a-real-key' not in ledger.path.read_text()


def test_zero_budget_does_not_send_http(tmp_path):
    calls = []
    p = QwenProvider(settings(), BudgetLedger(tmp_path / 'budget.json', 0),
                     httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r))))
    with pytest.raises(ProviderError, match='预算不足') as error:
        p.generate_candidate('温暖安静')
    assert error.value.code == 'budget_exceeded'
    assert not calls


def test_authentication_failure_is_not_retried_and_not_echoed(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={'error': {'message': 'echo sk-test-not-a-real-key'}})
    p, ledger = provider(tmp_path, handler)
    with pytest.raises(ProviderError) as error:
        p.generate_candidate('轻快明亮')
    assert error.value.code == 'authentication_error'
    assert len(calls) == 1 and 'sk-test-not-a-real-key' not in str(error.value)
    assert Decimal(json.loads(ledger.path.read_text())['attempts'][0]['accounted_cny']) > 0


def test_timeout_is_bounded_and_each_retry_reserves_budget(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('simulated', request=request)
    p, ledger = provider(tmp_path, handler)
    with pytest.raises(ProviderError) as error:
        p.generate_candidate('轻快明亮')
    assert error.value.code == 'network_error' and len(calls) == 2
    entries = json.loads(ledger.path.read_text())['attempts']
    assert len(entries) == 2 and all(x['status'] == 'network_error_unknown_charge' for x in entries)
    assert all(Decimal(x['accounted_cny']) > 0 for x in entries)


def test_retry_rechecks_remaining_budget(tmp_path):
    calls = []
    ledger = BudgetLedger(tmp_path / 'budget.json', 200)
    def handler(request):
        calls.append(request)
        # Another request has consumed the available limit before this retry.
        ledger.limit = Decimal(0)
        return httpx.Response(503)
    p = QwenProvider(settings(), ledger, httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None)
    with pytest.raises(ProviderError) as error:
        p.generate_candidate('温暖安静')
    assert error.value.code == 'budget_exceeded' and len(calls) == 1


@pytest.mark.parametrize('finish,content', [('length', '{}'), ('stop', 'not JSON'), ('stop', '{}')])
def test_incomplete_or_wrong_structure_never_becomes_candidate(tmp_path, finish, content):
    def handler(request):
        return httpx.Response(200, json={'usage': {'prompt_tokens': 100, 'completion_tokens': 200},
                                       'choices': [{'finish_reason': finish, 'message': {'content': content}}]})
    p, ledger = provider(tmp_path, handler)
    with pytest.raises(ProviderError) as error:
        p.generate_candidate('温暖安静')
    assert error.value.code == 'structure_error'
    assert json.loads(ledger.path.read_text())['attempts'][0]['status'] == 'invalid_music_structure'


def test_budget_reservations_survive_reopening(tmp_path):
    path = tmp_path / 'budget.json'
    BudgetLedger(path, 1).reserve(Decimal('0.8'), 'test', 'first', 1)
    with pytest.raises(ProviderError) as error:
        BudgetLedger(path, 1).reserve(Decimal('0.3'), 'test', 'second', 1)
    assert error.value.code == 'budget_exceeded'


def test_corrupt_budget_is_not_reset(tmp_path):
    path = tmp_path / 'budget.json'
    path.write_text('broken')
    with pytest.raises(ProviderError) as error:
        BudgetLedger(path, 200).reserve(Decimal('0.1'), 'test', 'first', 1)
    assert error.value.code == 'budget_error' and path.read_text() == 'broken'


def test_secret_cannot_be_sent_to_unapproved_host(tmp_path):
    with pytest.raises(ProviderError) as error:
        QwenProvider(settings(base_url='https://example.com/compatible-mode/v1'))
    assert error.value.code == 'config_error'


def test_production_prompt_includes_confirmed_rules_and_correction_without_changing_user_prompt(tmp_path):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return valid_response(request)
    p, ledger = provider(tmp_path, handler)
    p.generate_candidate('温暖安静', production=True, correction_feedback='measures.0.events.0.midi_pitch错误')
    instructions = seen[0]['messages'][0]['content']
    assert '演奏时长最多57秒' in instructions and '最高第7品' in instructions
    assert 'midi_pitch错误' in instructions and '这个诊断不输出音频' not in instructions
    assert '生成2到4小节的短小候选' not in instructions
    assert '简洁旋律与稀疏伴奏' not in instructions
    assert '乐句起伏' in instructions and '统一留后两拍空白' in instructions
    assert seen[0]['messages'][1]['content'] == '温暖安静'
    assert seen[0]['stream'] is True and seen[0]['stream_options']['include_usage'] is True


@pytest.mark.parametrize('text', [
    'data: {broken}\n\n',
    'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n\n',
    'data: {"choices":[],"error":{"message":"never echo raw vendor errors"}}\n\n',
])
def test_broken_stream_never_becomes_candidate_and_unknown_usage_stays_reserved(tmp_path, text):
    p, ledger = provider(tmp_path, lambda request: httpx.Response(200, text=text))
    with pytest.raises(ProviderError) as failure:
        p.generate_candidate('温暖安静', production=True)
    assert failure.value.code == 'response_error'
    assert 'never echo' not in str(failure.value)
    entries = json.loads(ledger.path.read_text())['attempts']
    assert len(entries) == 1 and entries[0]['status'] == 'response_error_unknown_charge'
    assert Decimal(entries[0]['accounted_cny']) > 0


def test_completed_stream_reassembles_content_and_reports_safe_timing(tmp_path):
    progress = []
    p, ledger = provider(tmp_path, valid_response)
    p.progress = progress.append
    candidate, receipt = p.generate_candidate('温暖安静', production=True)
    assert candidate.composition.origin == 'ai'
    assert receipt['stream_chunks'] == 3 and receipt['first_content_seconds'] >= 0
    assert progress and 'sk-test' not in json.dumps(receipt)
    assert json.loads(ledger.path.read_text())['attempts'][0]['status'] == 'candidate_ready'


def test_stream_without_usage_is_not_a_free_success(tmp_path):
    text = ('data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n')
    p, ledger = provider(tmp_path, lambda request: httpx.Response(200, text=text))
    with pytest.raises(ProviderError) as failure:
        p.generate_candidate('温暖安静', production=True)
    assert failure.value.code == 'response_error'
    entry = json.loads(ledger.path.read_text())['attempts'][0]
    assert entry['status'] == 'response_error_unknown_charge' and Decimal(entry['accounted_cny']) > 0


def test_stream_receive_limit_stops_without_parsing_large_partial_response(tmp_path, monkeypatch):
    from app.providers import qwen
    monkeypatch.setattr(qwen, 'MAX_STREAM_BYTES', 20)
    p, ledger = provider(tmp_path, valid_response)
    with pytest.raises(ProviderError, match='接收上限'):
        p.generate_candidate('温暖安静', production=True)
    assert len(json.loads(ledger.path.read_text())['attempts']) == 1


def test_compact_translation_preserves_ai_pitches_durations_and_absolute_times():
    data = {'creative_plan': '测试数据', 'title': '短乐句', 'tempo_bpm': 80.0, 'key_signature': 'C major',
            'bars': [{'notes': [{'voice': 'melody', 'offset_tick': 120, 'duration_ticks': 360, 'midi_pitch': 64},
                                {'voice': 'accompaniment', 'offset_tick': 0, 'duration_ticks': 960, 'midi_pitch': 48}]},
                     {'notes': [{'voice': 'melody', 'offset_tick': 480, 'duration_ticks': 120, 'midi_pitch': 67}]}]}
    plan = CompactCandidate.model_validate_json(json.dumps(data))
    result = expand_candidate(plan, '测试描述', 'server-id')
    events = [e for bar in result.composition.measures for e in bar.events]
    assert [(e.voice, e.onset_tick, e.duration_ticks, e.midi_pitch) for e in events] == [
        ('melody', 120, 360, 64), ('accompaniment', 0, 960, 48), ('melody', 2400, 120, 67)]
    assert events[0].notation_duration == 8 and events[0].dotted is True
    assert events[2].notation_duration == 16 and events[2].dotted is False
    assert result.composition.composition_id == 'server-id'
    assert result.composition.prompt == '测试描述'
    assert all(result.composition.tuning[e.string] + e.fret == e.midi_pitch for e in events)


def test_compact_translation_rejects_unrepresentable_duration_without_rounding():
    data = {'creative_plan': '测试数据', 'title': '错误节奏', 'tempo_bpm': 80.0, 'key_signature': 'C major',
            'bars': [{'notes': [{'voice': 'melody', 'offset_tick': 0, 'duration_ticks': 121, 'midi_pitch': 64}]}]}
    with pytest.raises(ValueError, match='duration_ticks'):
        expand_candidate(CompactCandidate.model_validate_json(json.dumps(data)), '测试', 'server-id')


def test_regeneration_constraints_are_in_system_prompt_and_do_not_rewrite_model(tmp_path):
    from app.schemas.composition import RegenerationConstraints
    seen = []
    def handler(request):
        seen.append(json.loads(request.content));return valid_response(request)
    p, ledger = provider(tmp_path, handler)
    item, _ = p.generate_candidate('想变慢并转D调', production=True,
                                   regeneration_constraints=RegenerationConstraints(tempo_bpm=100.0, key_signature='C'))
    text = seen[0]['messages'][0]['content']
    assert 'tempo_bpm=100.0' in text and 'key_signature="C"' in text
    assert seen[0]['messages'][1]['content'] == '想变慢并转D调'
    assert item.composition.tempo_bpm == 80.0  # Provider doesn't conceal a wrong model output.


@pytest.mark.parametrize('changes,expected', [
    ({'offset_tick': 1800, 'duration_ticks': 240}, 'note_boundary'),
    ({'tie': 'start'}, 'tie'),
    ({'offset_tick': 1}, 'offset_tick'),
])
def test_compact_note_rules_reject_boundary_and_unpaired_ties(changes, expected):
    note = {'voice': 'melody', 'offset_tick': 0, 'duration_ticks': 240, 'midi_pitch': 64}
    note.update(changes)
    data = {'creative_plan': 'test', 'title': 'test', 'tempo_bpm': 72, 'key_signature': 'C',
            'bars': [{'chord': 'C', 'notes': [note]}]}
    with pytest.raises(ValueError, match=expected):
        CompactCandidate.model_validate_json(json.dumps(data))


def test_schema_failure_reports_location_without_raw_input_and_bills_attempt(tmp_path):
    secret = 'do-not-echo-private-model-value'
    def handler(request):
        content = json.dumps({'creative_plan': 'test', 'title': 'test', 'tempo_bpm': 72,
                              'key_signature': 'C', 'bars': [{'notes': [{'voice': 'melody',
                                  'offset_tick': 0, 'duration_ticks': secret, 'midi_pitch': 64}]}]})
        chunks = [{'choices': [{'delta': {'content': content}, 'finish_reason': 'stop'}]},
                  {'choices': [], 'usage': {'prompt_tokens': 100, 'completion_tokens': 200}}]
        text = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
        return httpx.Response(200, text=text)
    p, ledger = provider(tmp_path, handler)
    with pytest.raises(ProviderError) as error:
        p.generate_candidate('test', production=True)
    assert 'bars.0.notes.0.duration_ticks' in error.value.correction_feedback
    assert 'duration_ticks' not in str(error.value)
    assert secret not in str(error.value) and secret not in error.value.correction_feedback
    assert json.loads(ledger.path.read_text())['attempts'][0]['status'] == 'invalid_music_structure'
