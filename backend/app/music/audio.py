"""Task09: real FluidSynth/FFmpeg rendering, with atomic verified MP3 output."""
import json
import math
import os
import subprocess
import tempfile
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values
from app.music.midi import export_midi
from app.music.validation import validate_composition

ROOT = Path(__file__).resolve().parents[3]
TAIL_RESERVE_SECONDS = 3.0


class AudioExportError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AudioTools:
    fluidsynth: Path
    ffmpeg: Path
    ffprobe: Path
    soundfont: Path

    @classmethod
    def load(cls):
        config = dotenv_values(ROOT / '.env')
        def path(key, fallback):
            value = os.getenv(key) or config.get(key) or fallback
            result = Path(value)
            return result if result.is_absolute() else ROOT / result
        ffmpeg = path('FFMPEG_PATH', '.tools/audio/bin/ffmpeg')
        return cls(path('FLUIDSYNTH_PATH', '.tools/audio/bin/fluidsynth'), ffmpeg,
                   ffmpeg.with_name('ffprobe'), path('SOUNDFONT_PATH', '.tools/soundfonts/FluidR3Mono_GM.sf3'))

    def check(self):
        for name, path in [('FluidSynth', self.fluidsynth), ('FFmpeg', self.ffmpeg), ('FFprobe', self.ffprobe)]:
            if not path.is_file() or not os.access(path, os.X_OK):
                raise AudioExportError('tool_missing', name + '路径不存在或不可执行，请检查本机配置')
        try:
            with self.soundfont.open('rb') as handle:
                header = handle.read(12)
        except OSError:
            raise AudioExportError('soundfont_missing', '吉他音色文件不存在或不可读取') from None
        if not header.startswith(b'RIFF') or header[8:12] != b'sfbk':
            raise AudioExportError('soundfont_invalid', '音色文件不是有效SoundFont')


def _run(arguments, label):
    try:
        return subprocess.run([str(a) for a in arguments], check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Don't dump raw external-tool logs or environment values.
        raise AudioExportError('tool_failed', label + '失败或超时，未交付新的MP3') from None


def _wav_stats(path):
    try:
        with wave.open(str(path), 'rb') as audio:
            channels, rate, count = audio.getnchannels(), audio.getframerate(), audio.getnframes()
            if audio.getsampwidth() != 2 or count <= 0 or rate <= 0:
                raise ValueError('PCM')
            samples = array('h', audio.readframes(count))
        if os.sys.byteorder != 'little':
            samples.byteswap()
        peak = max(abs(sample) for sample in samples)
        if peak == 0:
            raise AudioExportError('silent_audio', '合成音频完全静音，未交付MP3')
        return {'wav_seconds': count / rate, 'sample_rate': rate, 'channels': channels, 'peak_pcm': peak}
    except (OSError, ValueError, wave.Error):
        raise AudioExportError('invalid_wav', '合成结果不是有效的16位PCM WAV') from None


def export_mp3(piece, destination: Path, tools=None):
    summary = validate_composition(piece)
    if summary.performance_seconds + TAIL_RESERVE_SECONDS > 60:
        raise AudioExportError('tail_budget', '演奏时长未给尾音与编码留足3秒空间；请生成较短作品，不能截掉末尾音符')
    tools = tools or AudioTools.load()
    tools.check()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.audio-', dir=str(destination.parent)) as temporary:
        folder = Path(temporary)
        midi, wav, mp3 = folder / 'music.mid', folder / 'music.wav', folder / 'music.mp3'
        export_midi(piece, midi)
        _run([tools.fluidsynth, '-ni', '-T', 'wav', '-O', 's16', '-F', wav, '-r', '44100', tools.soundfont, midi], '吉他音频合成')
        stats = _wav_stats(wav)
        if stats['wav_seconds'] < summary.performance_seconds:
            raise AudioExportError('truncated_audio', '合成音频短于作品演奏时间，不能交付截断结果')
        _run([tools.ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', wav,
              '-map', '0:a:0', '-vn', '-c:a', 'libmp3lame', '-b:a', '192k', '-ar', '44100', mp3], 'MP3编码')
        result = _run([tools.ffprobe, '-v', 'error', '-show_entries',
                       'stream=codec_name,codec_type:format=duration', '-of', 'json', mp3], 'MP3格式检查')
        try:
            info = json.loads(result.stdout)
            streams = info['streams']
            seconds = float(info['format']['duration'])
            if len(streams) != 1 or streams[0]['codec_type'] != 'audio' or streams[0]['codec_name'] != 'mp3':
                raise ValueError('codec')
            if not math.isfinite(seconds) or seconds <= 0 or mp3.stat().st_size <= 0:
                raise ValueError('duration')
        except (KeyError, TypeError, ValueError, OSError):
            raise AudioExportError('invalid_mp3', '编码结果不是可交付的真实MP3文件') from None
        if seconds > 60:
            raise AudioExportError('audio_duration', f'MP3含尾音长{seconds:.3f}秒，超过60秒，未交付也未截断')
        if seconds < summary.performance_seconds:
            raise AudioExportError('truncated_audio', 'MP3短于作品演奏时间，未交付截断结果')
        # Decode the entire file, rather than treating a readable header as playable.
        _run([tools.ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', mp3, '-f', 'null', '-'], '完整MP3解码')
        os.replace(mp3, destination)
        return dict(stats, performance_seconds=summary.performance_seconds,
                    mp3_seconds=seconds, codec='mp3', bytes=destination.stat().st_size)
