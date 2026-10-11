"""Isolated orchestration tests. Fake provider/exporters never used by live CLI."""
import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.music import pipeline
from app.music.audio import AudioExportError
from app.music.pdf import PdfExportError
from app.providers.errors import ProviderError
from app.providers.qwen import MusicCandidate
from app.schemas.composition import Composition


def candidate():
    piece = Composition.model_validate_json((Path(__file__).parents[1] / 'fixtures/functional-fingerstyle.json').read_text())
    piece.origin = 'ai'
    piece.prompt = '测试描述'
    return MusicCandidate(creative_plan='测试替身，不是真实模型验收', composition=piece)


class TestProvider:
    __test__ = False

    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def generate_candidate(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        item = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item, {'local_request_id': 'isolated-test', 'estimated_cost_cny': '0'}


def fake_audio(piece, destination):
    destination.write_bytes(b'isolated audio test double')
    return {'mp3_seconds': 8.6}


def fake_pdf(piece, destination, base_url):
    destination.write_bytes(b'isolated PDF test double')
    return {'pages': 1}


def run(tmp_path, provider, **kwargs):
    return pipeline.generate_work('测试描述', jobs_root=tmp_path, provider=provider,
                                  audio_exporter=kwargs.get('audio_exporter', fake_audio),
                                  pdf_exporter=kwargs.get('pdf_exporter', fake_pdf))


def accept_test_pdf(monkeypatch):
    monkeypatch.setattr(pipeline, 'inspect_pdf', lambda path, piece: {'pages': 1})


def test_ready_only_after_every_file_and_single_source(tmp_path, monkeypatch):
    accept_test_pdf(monkeypatch)
    seen = []
    def pdf(piece, destination, base_url):
        manifest = json.loads((destination.parent.parent / 'manifest.json').read_text())
        assert manifest['status'] == 'running' and not manifest['files']
        assert not (destination.parent.parent / 'artifacts').exists()
        seen.append(piece.composition_id)
        return fake_pdf(piece, destination, base_url)
    result = run(tmp_path, TestProvider([candidate()]), pdf_exporter=pdf)
    folder = tmp_path / result['job_id']
    assert result['status'] == 'ready' and seen == [result['composition_id']]
    source = json.loads((folder / 'artifacts/composition.json').read_text())
    assert source['composition_id'] == result['composition_id']
    assert not (folder / '.staging').exists()
    assert len(result['files']) == 6
    for name, item in result['files'].items():
        data = (folder / item['path']).read_bytes()
        assert data and hashlib.sha256(data).hexdigest() == item['sha256']


@pytest.mark.parametrize('stage,error', [('audio', AudioExportError('tool_failed', 'test')),
                                       ('pdf', PdfExportError('score_render', 'test'))])
def test_export_failure_removes_all_partial_files_without_model_retry(tmp_path, stage, error):
    def fail(*args):
        args[1].write_bytes(b'partial')
        raise error
    p = TestProvider([candidate()])
    with pytest.raises(pipeline.PipelineError) as failure:
        run(tmp_path, p, **{stage + '_exporter': fail})
    folder = tmp_path / failure.value.job_id
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert manifest['status'] == 'failed' and manifest['files'] == {}
    assert manifest['error']['stage'] == stage
    assert not (folder / '.staging').exists() and not (folder / 'artifacts').exists()
    assert len(p.calls) == 1


def test_wrong_pitch_feedback_then_fresh_valid_candidate(tmp_path, monkeypatch):
    accept_test_pdf(monkeypatch)
    broken = candidate()
    broken.composition.measures[0].events[0].midi_pitch += 1
    p = TestProvider([broken, candidate()])
    result = run(tmp_path, p)
    assert result['status'] == 'ready' and len(p.calls) == 2
    assert 'midi_pitch' in p.calls[1][1]['correction_feedback']
    assert p.calls[0][1]['production'] is True
    assert broken.composition.measures[0].events[0].midi_pitch != candidate().composition.measures[0].events[0].midi_pitch


def test_malformed_model_structure_gets_one_correction(tmp_path, monkeypatch):
    accept_test_pdf(monkeypatch)
    p = TestProvider([ProviderError('structure_error', 'bars.0.notes.0.duration_ticks:literal_error'), candidate()])
    assert run(tmp_path, p)['status'] == 'ready'
    assert len(p.calls) == 2 and 'duration_ticks' in p.calls[1][1]['correction_feedback']


def test_bad_music_exhausts_two_attempts_without_export(tmp_path):
    broken = candidate()
    broken.composition.measures[0].events[0].midi_pitch += 1
    p = TestProvider([broken])
    with pytest.raises(pipeline.PipelineError) as failure:
        run(tmp_path, p)
    assert len(p.calls) == 2 and failure.value.stage == 'validation'
    manifest = json.loads((tmp_path / failure.value.job_id / 'manifest.json').read_text())
    assert manifest['status'] == 'failed' and not manifest['files']


@pytest.mark.parametrize('code', ['authentication_error', 'budget_exceeded', 'network_error'])
def test_non_music_provider_failure_never_triggers_extra_composition_call(tmp_path, code):
    p = TestProvider([ProviderError(code, 'safe test failure')])
    with pytest.raises(pipeline.PipelineError) as failure:
        run(tmp_path, p)
    assert len(p.calls) == 1 and failure.value.code == code


def test_blank_actual_pdf_is_rejected_even_when_exporter_reports_success(tmp_path):
    def blank(piece, destination, base_url):
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.write(destination)
        return {'pages': 1}
    with pytest.raises(pipeline.PipelineError) as failure:
        run(tmp_path, TestProvider([candidate()]), pdf_exporter=blank)
    assert failure.value.stage == 'verification' and failure.value.code == 'invalid_pdf'


def test_two_jobs_never_overwrite_previous_ready_work(tmp_path, monkeypatch):
    accept_test_pdf(monkeypatch)
    first = run(tmp_path, TestProvider([candidate()]))
    before = (tmp_path / first['job_id'] / 'manifest.json').read_bytes()
    with pytest.raises(pipeline.PipelineError):
        run(tmp_path, TestProvider([ProviderError('budget_exceeded', 'test')]))
    assert (tmp_path / first['job_id'] / 'manifest.json').read_bytes() == before


def test_missing_accompaniment_and_tail_budget_are_rejected():
    piece = candidate().composition
    for bar in piece.measures:
        bar.events = [e for e in bar.events if e.voice == 'melody']
    with pytest.raises(pipeline.MusicValidationError, match='旋律和和声伴奏'):
        pipeline.check_content(piece)
    piece = candidate().composition
    piece.tempo_bpm = 16.0
    with pytest.raises(pipeline.MusicValidationError, match='57秒'):
        pipeline.check_content(piece)


def test_queued_job_uses_same_id_and_cannot_overwrite_ready_work(tmp_path, monkeypatch):
    import uuid
    accept_test_pdf(monkeypatch)
    job_id = str(uuid.uuid4())
    folder = tmp_path / job_id
    folder.mkdir()
    pipeline.write_json(folder / 'manifest.json', {'job_id': job_id, 'status': 'queued'})
    result = pipeline.generate_work('测试描述', jobs_root=tmp_path, job_id=job_id, provider=TestProvider([candidate()]),
                                    audio_exporter=fake_audio, pdf_exporter=fake_pdf)
    assert result['job_id'] == job_id and result['status'] == 'ready'
    original = (folder / 'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='不能覆盖'):
        pipeline.generate_work('测试描述', jobs_root=tmp_path, job_id=job_id)
    assert (folder / 'manifest.json').read_bytes() == original


def replacement_candidate():
    import uuid
    item = candidate()
    item.composition.composition_id = str(uuid.uuid4())
    event = item.composition.measures[0].events[2]
    event.midi_pitch = 64
    event.fret = 0
    return item


def test_regeneration_passes_trusted_constraints_and_assigns_relationship(tmp_path, monkeypatch):
    accept_test_pdf(monkeypatch)
    source = candidate().composition
    provider = TestProvider([replacement_candidate()])
    result = pipeline.generate_work('测试描述', jobs_root=tmp_path, provider=provider, source_piece=source,
                                    audio_exporter=fake_audio, pdf_exporter=fake_pdf)
    piece = Composition.model_validate_json((tmp_path / result['job_id'] / 'artifacts/composition.json').read_text())
    assert piece.source_composition_id == source.composition_id
    assert piece.constraints.tempo_bpm == piece.tempo_bpm == source.tempo_bpm
    assert piece.key_signature == source.key_signature
    assert pipeline.note_signature(piece) != pipeline.note_signature(source)
    assert provider.calls[0][1]['regeneration_constraints'].key_signature == source.key_signature


@pytest.mark.parametrize('field,value', [('tempo_bpm', 100.0), ('key_signature', 'D major')])
def test_regeneration_wrong_tempo_or_key_gets_one_model_correction(tmp_path, monkeypatch, field, value):
    accept_test_pdf(monkeypatch)
    source = candidate().composition
    broken = replacement_candidate()
    setattr(broken.composition, field, value)
    provider = TestProvider([broken, replacement_candidate()])
    result = pipeline.generate_work('测试描述', jobs_root=tmp_path, provider=provider, source_piece=source,
                                    audio_exporter=fake_audio, pdf_exporter=fake_pdf)
    assert result['status'] == 'ready' and len(provider.calls) == 2
    assert '重新生成必须保持速度' in provider.calls[1][1]['correction_feedback']
    # The rejected model output is not quietly rewritten.
    assert getattr(broken.composition, field) == value


def test_regeneration_repeated_mismatch_fails_without_export_or_modifying_source(tmp_path):
    source = candidate().composition
    before = source.model_dump_json()
    broken = replacement_candidate();broken.composition.tempo_bpm = 100.0
    provider = TestProvider([broken])
    with pytest.raises(pipeline.PipelineError):
        pipeline.generate_work('测试描述', jobs_root=tmp_path, provider=provider, source_piece=source,
                               audio_exporter=lambda *a: pytest.fail('must not export'))
    assert len(provider.calls) == 2 and source.model_dump_json() == before
    assert all(json.loads(p.read_text())['files'] == {} for p in tmp_path.glob('*/manifest.json'))


def test_regeneration_title_and_id_changes_do_not_count_as_changed_music():
    source = candidate().composition
    clone = source.model_copy(deep=True)
    clone.composition_id = 'different-id';clone.title = 'different-title'
    with pytest.raises(pipeline.MusicValidationError, match='实际改变音符'):
        pipeline.check_replacement(clone, source)
