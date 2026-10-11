"""Task11: one source, verified artifacts, bounded correction, atomic delivery."""
import hashlib
import json
import os
import shutil
import uuid
import time
from dataclasses import asdict
from pathlib import Path

from app.providers.errors import ProviderError
from app.providers.control import GenerationControl, JOB_TIMEOUT_SECONDS
from app.schemas.composition import Composition, RegenerationConstraints
from app.providers.qwen import QwenSettings
from app.providers.staged import StagedQwenProvider
from app.music.validation import MusicIssue, MusicValidationError, validate_composition
from app.music.fingering import assign_fingering
from app.music.phrasing import phrase_diagnostics
from app.music.harmony import validate_harmony
from app.music.limits import MIN_BPM, MAX_BPM
from app.music.alphatex import to_alphatex
from app.music.midi import export_midi
from app.music.audio import AudioExportError, TAIL_RESERVE_SECONDS, export_mp3
from app.music.pdf import PdfExportError, export_pdf, inspect_pdf

ROOT = Path(__file__).resolve().parents[3]


class PipelineError(ValueError):
    def __init__(self, job_id, stage, code, message):
        self.job_id, self.stage, self.code = job_id, stage, code
        super().__init__(message)


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def check_content(piece):
    summary = validate_composition(piece)
    issues = []
    if not MIN_BPM <= piece.tempo_bpm <= MAX_BPM:
        issues.append(MusicIssue('tempo_bpm', 'tempo_range', '首版速度必须在60–120 BPM之间，包含边界'))
    if summary.performance_seconds + TAIL_RESERVE_SECONDS > 60:
        issues.append(MusicIssue('measures', 'tail_budget', '演奏时长最多57秒，为尾音留3秒'))
    melody = [e for b in piece.measures for e in b.events if e.kind == 'note' and e.voice == 'melody']
    bass = [e for b in piece.measures for e in b.events if e.kind == 'note' and e.voice == 'accompaniment']
    if not melody or not bass or not any(
            max(a.onset_tick, b.onset_tick) < min(a.onset_tick + a.duration_ticks, b.onset_tick + b.duration_ticks)
            for a in melody for b in bass):
        issues.append(MusicIssue('measures', 'two_voices', '需要旋律和和声伴奏音符，且部分同时发声'))
    if issues:
        raise MusicValidationError(issues)
    validate_harmony(piece)
    return summary


def note_signature(piece):
    return sorted((e.onset_tick, e.duration_ticks, e.midi_pitch, e.tie)
                  for bar in piece.measures for e in bar.events if e.kind == 'note')


def check_replacement(piece, source):
    issues = []
    if piece.tempo_bpm != source.tempo_bpm or piece.key_signature != source.key_signature:
        issues.append(MusicIssue('constraints', 'tempo_key_changed',
                                 '重新生成必须保持速度%s BPM、调性%s，不可改写字段来绕过检查' %
                                 (source.tempo_bpm, source.key_signature)))
    if piece.composition_id == source.composition_id or note_signature(piece) == note_signature(source):
        issues.append(MusicIssue('measures', 'music_unchanged', '请实际改变音符或节奏，不只更换标题或作品编号'))
    if issues:
        raise MusicValidationError(issues)


def generate_work(prompt, *, jobs_root=None, provider=None, base_url='http://127.0.0.1:8000',
                  audio_exporter=export_mp3, pdf_exporter=export_pdf, job_id=None, source_piece=None, control=None):
    """Exporters are injectable for isolated failure tests, never CLI fallbacks.

    Legacy providers allow two whole candidates. Staged AI corrects each plan/bar
    at most once, without restarting completed steps. All network attempts
    recheck budget. Export failures do not cause more model calls.
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1000:
        raise ValueError('提示词需为1到1000个字符的非空文字')
    prompt = prompt.strip()
    if source_piece is not None and (not isinstance(source_piece, Composition) or source_piece.origin != 'ai'):
        raise ValueError('重新生成必须基于完整AI作品')
    constraints = (RegenerationConstraints(tempo_bpm=source_piece.tempo_bpm, key_signature=source_piece.key_signature)
                   if source_piece is not None else None)
    queued = job_id is not None
    job_id = str(uuid.UUID(job_id)) if queued else str(uuid.uuid4())
    folder = (jobs_root or ROOT / 'runtime' / 'jobs') / job_id
    if queued:
        previous = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if previous.get('job_id') != job_id or previous.get('status') != 'queued' or not set(p.name for p in folder.iterdir()).issubset({'manifest.json', '.cancel', '.control.lock'}):
            raise ValueError('只能执行新排队任务，不能覆盖已有作品')
    else:
        folder.mkdir(parents=True, exist_ok=False)
    deadline = previous.get('deadline_at', time.time() + JOB_TIMEOUT_SECONDS) if queued else time.time() + JOB_TIMEOUT_SECONDS
    control = control or GenerationControl(folder, deadline)
    deadline = control.deadline
    staging = folder / '.staging'
    staging.mkdir()
    manifest = {'job_id': job_id, 'status': 'running', 'stage': 'model', 'files': {}, 'attempts': [],
                'source_composition_id': source_piece.composition_id if source_piece is not None else None,
                'deadline_at': deadline}
    if queued:
        for name in ('request_hash', 'created_at'):
            if name in previous: manifest[name] = previous[name]
    manifest_path = folder / 'manifest.json'
    write_json(manifest_path, manifest)

    def stage(name):
        control.checkpoint()
        manifest['stage'] = name
        write_json(manifest_path, manifest)

    try:
        control.checkpoint()
        provider = provider or StagedQwenProvider(QwenSettings.load())
        def progress(message):
            control.checkpoint()
            manifest['progress'] = message
            write_json(manifest_path, manifest)
        def record(receipt):
            manifest['attempts'][-1]['request'] = receipt
            write_json(manifest_path, manifest)
        if isinstance(provider, StagedQwenProvider):
            provider.control = control
            provider.progress = progress
            provider.receipt_observer = record
        feedback = None
        max_candidates = 1 if isinstance(provider, StagedQwenProvider) else 2
        for attempt in range(1, max_candidates + 1):
            stage('model')
            entry = {'attempt': attempt}
            manifest['attempts'].append(entry)
            try:
                options = {'regeneration_constraints': constraints} if constraints is not None else {}
                candidate, receipt = provider.generate_candidate(prompt, production=True, correction_feedback=feedback, **options)
                entry['request'] = receipt
                if candidate.composition.origin != 'ai' or candidate.composition.prompt != prompt:
                    raise MusicValidationError([MusicIssue('origin', 'ai_source', '必须是真实AI候选且提示词一致')])
                stage('validation')
                if source_piece is not None:
                    check_replacement(candidate.composition, source_piece)
                    # Relationship metadata is assigned locally; musical tempo/key are never rewritten.
                    candidate = candidate.model_copy(update={'composition': candidate.composition.model_copy(update={
                        'source_composition_id': source_piece.composition_id, 'constraints': constraints})})
                check_content(candidate.composition)
                stage('fingering')
                piece, fingering = assign_fingering(candidate.composition)
                music = check_content(piece)
                stage('tablature')
                alphatex = to_alphatex(piece)
                entry['status'] = 'accepted'
                break
            except (MusicValidationError, ProviderError, ValueError) as error:
                # Only malformed music is correctable; auth/network/budget/export failures stop.
                if isinstance(error, ProviderError) and error.receipt:
                    entry['request'] = error.receipt
                if isinstance(error, ProviderError) and error.code != 'structure_error':
                    entry.update(status='failed', code=error.code)
                    write_json(manifest_path, manifest)
                    raise
                entry['status'] = 'rejected'
                if isinstance(error, ProviderError) and error.receipt:
                    entry['request'] = error.receipt
                if isinstance(error, MusicValidationError):
                    entry['issues'] = [asdict(i) for i in error.issues[:15]]
                    feedback = str(error)[:1800]
                else:
                    feedback = ((error.correction_feedback or str(error))[:1800] if isinstance(error, ProviderError)
                                else '音乐结构或谱面格式无效，请严格遵守JSON Schema和音乐规则。')
                    entry['code'] = getattr(error, 'code', 'music_format')
                    entry['message'] = feedback
                write_json(manifest_path, manifest)
                if attempt == max_candidates:
                    raise

        stage('source')
        (staging / 'composition.json').write_text(piece.model_dump_json(indent=2), encoding='utf-8')
        (staging / 'score.alphatex').write_text(alphatex, encoding='utf-8')
        write_json(staging / 'creation.json', {'creative_plan': candidate.creative_plan,
                                             'request': receipt, 'fingering': asdict(fingering),
                                             'phrase_diagnostics': phrase_diagnostics(piece),
                                             'harmony_checks': validate_harmony(piece),
                                             'performance': {'policy': 'phrase-velocity-v1',
                                                             'pitch_and_timing_preserved': True}})
        export_midi(piece, staging / 'music.mid')
        stage('audio')
        audio_report = audio_exporter(piece, staging / 'audio.mp3')
        stage('pdf')
        pdf_report = pdf_exporter(piece, staging / 'score.pdf', base_url)
        stage('verification')
        # Inspect the actual PDF again before publishing a common artifact directory.
        inspect_pdf(staging / 'score.pdf', piece)
        names = ['composition.json', 'score.alphatex', 'creation.json', 'music.mid', 'audio.mp3', 'score.pdf']
        files = {}
        for name in names:
            path = staging / name
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError('产物缺失或为空')
            files[name] = {'path': 'artifacts/' + name, 'bytes': path.stat().st_size,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        with control.publication():
            os.replace(staging, folder / 'artifacts')
            manifest.update(status='ready', stage='complete', composition_id=piece.composition_id,
                            files=files, tempo_bpm=piece.tempo_bpm, key_signature=piece.key_signature,
                            performance_seconds=music.performance_seconds, audio=audio_report, pdf=pdf_report)
            write_json(manifest_path, manifest)
        return manifest
    except Exception as error:
        # Remove all partial exports. Keep only a safe failure receipt, never "ready".
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(folder / 'artifacts', ignore_errors=True)
        code = getattr(error, 'code', 'music_invalid' if isinstance(error, MusicValidationError) else 'generation_failed')
        message = (str(error)[:1800] if isinstance(error, (ProviderError, MusicValidationError, AudioExportError, PdfExportError))
                   else '该阶段生成或检查失败，未交付半成品。')
        manifest.update(status='failed', files={}, error={'stage': manifest['stage'], 'code': code, 'message': message})
        write_json(manifest_path, manifest)
        raise PipelineError(job_id, manifest['stage'], code, message) from None
