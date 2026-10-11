"""Generate two fixed source/alphaTex pairs for task07, never AI results."""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.music.alphatex import to_alphatex
from app.schemas.composition import Composition


def diagnostic_examples():
    original = Composition.model_validate_json((BACKEND / 'fixtures' / 'diagnostic-fingerstyle.json').read_text())
    long = original.model_copy(deep=True)
    long.composition_id = 'diagnostic-long-16-bars'
    long.title = '排谱诊断：16小节（固定样例，非AI）'
    long.measures = []
    for repetition in range(8):
        for bar in original.measures:
            new_bar = bar.model_copy(deep=True)
            new_bar.id = f'm{len(long.measures) + 1}'
            new_bar.order = len(long.measures) + 1
            offset = repetition * 3840
            new_bar.start_tick += offset
            for event in new_bar.events:
                event.id = f'{event.id}-repeat-{repetition}'
                event.onset_tick += offset
            long.measures.append(new_bar)
    return [{'name': name, 'composition': piece.model_dump(mode='json'), 'alphatex': to_alphatex(piece)}
            for name, piece in [('短样例：2小节', original), ('长样例：16小节', long)]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    destination = BACKEND.parent / 'frontend' / 'public' / 'diagnostics' / 'tablature.json'
    content = json.dumps(diagnostic_examples(), ensure_ascii=False, indent=2) + '\n'
    if args.check:
        if not destination.exists() or destination.read_text() != content:
            print('诊断谱面与主数据/转换器不同步，请重新导出')
            return 1
        print('两组诊断谱面与主数据同步')
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding='utf-8')
    print('已导出固定短/长诊断谱面：' + str(destination))
    return 0


if __name__ == '__main__':
    sys.exit(main())
