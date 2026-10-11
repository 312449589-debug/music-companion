"""Task11: real prompt -> one complete work, or inspect saved ready manifests."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.music.pipeline import PipelineError, generate_work, check_content
from app.music.pdf import inspect_pdf
from app.music.fingering import validate_fingering
from app.music.alphatex import to_alphatex
from app.schemas.composition import Composition
from app.providers.qwen import QwenProvider, QwenSettings

JOBS = BACKEND.parent / 'runtime' / 'jobs'


def inspect_saved(job_id):
    import uuid
    job_id = str(uuid.UUID(job_id))
    folder = JOBS / job_id
    report = json.loads((folder / 'manifest.json').read_text())
    if report['status'] != 'ready' or report['job_id'] != job_id:
        raise ValueError('不是完整ready作品，不能验收为成功')
    expected = {'composition.json', 'score.alphatex', 'creation.json', 'music.mid', 'audio.mp3', 'score.pdf'}
    if set(report['files']) != expected:
        raise ValueError('产物清单不完整')
    for name, item in report['files'].items():
        path = folder / 'artifacts' / name
        if item['path'] != 'artifacts/' + name or path.stat().st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('产物清单与实际文件不一致：' + name)
    piece = Composition.model_validate_json((folder / 'artifacts/composition.json').read_text())
    check_content(piece)
    validate_fingering(piece)
    if piece.origin != 'ai' or piece.composition_id != report['composition_id']:
        raise ValueError('AI来源/作品编号不一致')
    if to_alphatex(piece) != (folder / 'artifacts/score.alphatex').read_text():
        raise ValueError('谱面与主数据不一致')
    inspect_pdf(folder / 'artifacts/score.pdf', piece)
    print('已保存完整作品检查通过：' + job_id)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt', help='一条真实创作描述；默认依次生成两首不同描述')
    parser.add_argument('--inspect', help='只核对已有任务编号，不调用模型')
    args = parser.parse_args()
    try:
        if args.inspect:
            report = inspect_saved(args.inspect)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        # Fail before paid AI calls when the local print page is not available.
        with httpx.Client(trust_env=False, timeout=10) as client:
            response = client.get('http://127.0.0.1:8000/diagnostics/print')
            if response.status_code != 200:
                raise ValueError('请先启动本机网页服务并构建打印页')
        reports = []
        for prompt in ([args.prompt] if args.prompt else ['温暖安静，适合夜晚弹奏', '轻快明亮，简单和声加旋律']):
            print('正在真实AI生成、检查并导出：' + prompt, flush=True)
            provider = QwenProvider(QwenSettings.load(), progress=lambda message: print(message, flush=True))
            report = generate_work(prompt, provider=provider)
            folder = JOBS / report['job_id']
            inspect_saved(report['job_id'])
            reports.append({'job_id': report['job_id'], 'composition_id': report['composition_id'],
                            'folder': str(folder / 'artifacts')})
            print(json.dumps({'status': report['status'], 'job_id': report['job_id'],
                              'composition_id': report['composition_id'], 'bpm': report['tempo_bpm'],
                              'performance_seconds': report['performance_seconds'], 'audio': report['audio'],
                              'pdf': report['pdf'], 'folder': str(folder / 'artifacts')}, ensure_ascii=False, indent=2), flush=True)
        diagnostics = BACKEND.parent / 'runtime' / 'diagnostics'
        diagnostics.mkdir(parents=True, exist_ok=True)
        (diagnostics / 'pipeline-check.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        print('任务11真实完整生成通过；仍需打开PDF和MP3核对，指弹人工审阅统一放在任务19。')
        return 0
    except PipelineError as error:
        print('整体生成失败：任务' + error.job_id + '，阶段' + error.stage + '，错误' + error.code + '：' + str(error), flush=True)
        print('没有交付半成品；manifest.json已记录失败阶段。')
        return 1
    except (OSError, ValueError, httpx.HTTPError):
        print('诊断未通过：本机服务未就绪或已有产物检查失败；未将结果视为成功。')
        return 1


if __name__ == '__main__':
    sys.exit(main())
