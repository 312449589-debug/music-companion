"""Export and independently reread task08 diagnostic MIDI."""
import argparse
import json
import sys
from pathlib import Path

import mido
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.music.midi import export_midi
from app.music.validation import MusicValidationError, validate_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=BACKEND / 'fixtures' / 'diagnostic-fingerstyle.json')
    args = parser.parse_args()
    try:
        piece, summary = validate_json(args.file.read_text(encoding='utf-8'))
        output = BACKEND.parent / 'runtime' / 'diagnostics' / 'composition-check.mid'
        export_midi(piece, output)
        restored = mido.MidiFile(output, charset='utf-8')
        print(f'MIDI已导出并重新读取：{output}')
        print(f'实际长度：{restored.length:.6f}秒；主数据演奏长度：{summary.performance_seconds:.6f}秒')
        for index, track in enumerate(restored.tracks):
            tick = 0
            for message in track:
                if message.time < 0:
                    raise ValueError('不能有负时间差')
                tick += message.time
                if message.type in ('note_on', 'note_off', 'set_tempo', 'program_change'):
                    print(f'轨道{index} tick={tick} {message}')
    except (OSError, ValueError) as error:
        print('MIDI检查失败：' + str(error))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
