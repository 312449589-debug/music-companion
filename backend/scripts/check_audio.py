"""Task09 synthesis diagnostic, no AI request or product player."""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.music.audio import AudioExportError, AudioTools, export_mp3
from app.music import audio as audio_module
from app.music.validation import validate_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=BACKEND / 'fixtures' / 'diagnostic-fingerstyle.json')
    parser.add_argument('--case', choices=['missing-ffmpeg', 'missing-font', 'tail-overflow', 'encoded-overflow', 'failing-ffmpeg'])
    args = parser.parse_args()
    try:
        piece, _ = validate_json(args.file.read_text(encoding='utf-8'))
        tools = AudioTools.load()
        if args.case == 'missing-ffmpeg': tools = replace(tools, ffmpeg=BACKEND / 'missing-ffmpeg')
        elif args.case == 'missing-font': tools = replace(tools, soundfont=BACKEND / 'missing-soundfont.sf3')
        elif args.case == 'tail-overflow': piece.tempo_bpm = 8.0
        elif args.case == 'encoded-overflow':
            # Isolated diagnostic process: exercise the post-encoding guard.
            piece.tempo_bpm = 8.0
            audio_module.TAIL_RESERVE_SECONDS = 0.0
        elif args.case == 'failing-ffmpeg': tools = replace(tools, ffmpeg=Path('/usr/bin/false'))
        folder = BACKEND.parent / 'runtime' / 'diagnostics'
        name = ('audio-failure-' + args.case) if args.case else 'composition-check'
        output = folder / (name + '.mp3')
        print('开始真实吉他合成与MP3编码，不请求AI…', flush=True)
        report = export_mp3(piece, output, tools)
        (folder / (name + '-audio.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('真实MP3生成、格式与完整解码检查通过：' + str(output))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('浏览器试听：http://127.0.0.1:8000/diagnostics/audio-check.mp3')
        return 0
    except (OSError, ValueError) as error:
        print('音频导出失败 [' + getattr(error, 'code', 'music_error') + ']：' + str(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
