"""Task10: short/cross-page PDFs or deliberately failed score rendering."""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.music.pdf import export_pdf
from app.schemas.composition import Composition
from export_tablature_diagnostics import diagnostic_examples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failed-render', action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    folder = BACKEND.parent / 'runtime' / 'diagnostics'
    reports = []
    try:
        for name, example in zip(['short', 'long'], diagnostic_examples()):
            piece = Composition.model_validate_json(json.dumps(example['composition']))
            if args.failed_render:
                export_pdf(piece, folder / 'rejected-render.pdf', args.base_url, alphatex_override='invalid { !!!')
                raise ValueError('无效谱面不应返回成功')
            output = folder / ('score-check-' + name + '.pdf')
            print('正在导出' + name + '真实六线谱PDF…', flush=True)
            report = export_pdf(piece, output, args.base_url)
            report['file'] = str(output)
            if name == 'long' and report['pages'] < 2:
                raise ValueError('长样例未跨页，不能完成跨页验收')
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        (folder / 'pdf-check.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        print('短/跨页PDF生成及内容检查通过；仍需逐页检查视觉布局。')
        return 0
    except (OSError, ValueError) as error:
        if args.failed_render and getattr(error, 'code', '') == 'score_render':
            print('失败谱面诊断通过：明确拒绝，没有空白PDF。')
            return 0
        print('PDF诊断未通过 [' + getattr(error, 'code', 'pdf_error') + ']：' + str(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
