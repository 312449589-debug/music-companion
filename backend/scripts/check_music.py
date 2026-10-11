"""Task05 diagnostic: no model request, fingering assignment or exports."""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.music.validation import MusicValidationError, validate_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=BACKEND / 'fixtures' / 'diagnostic-fingerstyle.json')
    parser.add_argument('--case', choices=['four-seconds', 'too-long', 'wrong-pitch', 'local-tempo', 'local-key', 'percussion'])
    args = parser.parse_args()
    try:
        data = json.loads(args.file.read_text(encoding='utf-8'))
        piece = data.get('composition', data)
        event = piece['measures'][0]['events'][0]
        if args.case == 'four-seconds':
            piece['tempo_bpm'] = 120.0
        elif args.case == 'too-long':
            piece['tempo_bpm'] = 7.0
        elif args.case == 'wrong-pitch':
            event['midi_pitch'] += 1
        elif args.case == 'local-tempo':
            event['tempo_bpm'] = 100.0
        elif args.case == 'local-key':
            piece['measures'][0]['key_signature'] = 'G major'
        elif args.case == 'percussion':
            event['technique'] = 'percussion'
        composition, summary = validate_json(json.dumps(data))
    except MusicValidationError as error:
        print('音乐基础检查失败（文件未修改）：')
        for issue in error.issues:
            print(f'{issue.path} [{issue.rule}]：{issue.message}')
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('读取诊断文件失败：' + str(error))
        return 1
    print('音乐基础检查通过（尚不代表指型、听感或最终MP3通过）')
    print(json.dumps({'composition_id': composition.composition_id, 'tempo_bpm': composition.tempo_bpm,
                      'end_tick': summary.end_tick, 'quarter_beats': summary.end_tick / composition.ppq,
                      'performance_seconds': summary.performance_seconds, 'notes': summary.note_count},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
