"""Task06 diagnostic; no audio, score, AI request or human-review claim."""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.music.fingering import CONFIRMED_RULES, assign_fingering, validate_fingering
from app.music.validation import MusicValidationError, validate_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=BACKEND / 'fixtures' / 'diagnostic-fingerstyle.json')
    parser.add_argument('--assign', action='store_true', help='仅在内存重新分配弦位，不修改文件')
    parser.add_argument('--case', choices=['same-string', 'wide-span'])
    args = parser.parse_args()
    try:
        data = json.loads(args.file.read_text(encoding='utf-8'))
        piece = data.get('composition', data)
        event = piece['measures'][0]['events'][1]
        if args.case == 'same-string':
            event.update(string=5, fret=0, midi_pitch=45)
        elif args.case == 'wide-span':
            event.update(string=1, fret=7, midi_pitch=71)
        composition, _ = validate_json(json.dumps(data))
        if args.assign:
            composition, summary = assign_fingering(composition)
        else:
            summary = validate_fingering(composition)
    except MusicValidationError as error:
        print('指型检查失败：')
        for issue in error.issues:
            print(f'{issue.path} [{issue.rule}]：{issue.message}')
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('读取诊断文件失败：' + str(error))
        return 1
    print('自动指型规则通过；仍需懂指弹的人审阅，不代表真实演奏已验收。')
    print(json.dumps({'rules': asdict(CONFIRMED_RULES), 'summary': asdict(summary)}, ensure_ascii=False, indent=2))
    for bar in composition.measures:
        print(f'小节{bar.order} {bar.chord or ""}')
        for event in sorted(bar.events, key=lambda e: (e.onset_tick, e.id)):
            if event.kind == 'note':
                print(f'  {event.id} {event.voice} tick={event.onset_tick} 长度={event.duration_ticks} '
                      f'{event.string}弦{event.fret}品 MIDI={event.midi_pitch} 时值=1/{event.notation_duration}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
