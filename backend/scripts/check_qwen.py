"""Task 04 live API diagnostics; no scores, audio, generation endpoints or mock fallback."""
import argparse
import json
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.providers.budget import BudgetLedger
from app.providers.errors import ProviderError
from app.providers.qwen import QwenProvider, QwenSettings

PROMPTS = ['温暖安静，适合夜晚弹奏', '轻快明亮，简单和声加旋律']
OUTPUT = BACKEND.parent / 'runtime' / 'ai'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt', help='单次真实创作描述；默认依次验证两个固定描述')
    parser.add_argument('--budget-check', action='store_true', help='仅验证零预算，不发送模型请求')
    parser.add_argument('--invalid-key-check', action='store_true', help='用固定无效密钥验证认证失败')
    parser.add_argument('--status', action='store_true', help='只检查本机配置与预算，不调用供应商')
    args = parser.parse_args()
    try:
        settings = QwenSettings.load()
        if args.status:
            print('模型配置已齐全，密钥不显示；尚不代表真实调用成功。')
            print('模型：' + settings.model)
            print('本项目总预算上限：' + str(settings.budget) + ' 元')
            return 0
        if args.budget_check:
            # Real code path with a zero-limit isolated ledger; guard executes before HTTP.
            provider = QwenProvider(settings, ledger=BudgetLedger(OUTPUT / 'zero-budget-check.json', Decimal(0)))
            try:
                provider.generate_candidate(PROMPTS[0])
            except ProviderError as error:
                if error.code == 'budget_exceeded':
                    print('零预算验证通过：预算检查已拒绝调用，未发送模型请求。')
                    return 0
                raise
            raise ProviderError('diagnostic_error', '零预算不应返回音乐候选')
        if args.invalid_key_check:
            provider = QwenProvider(replace(settings, api_key='invalid-key-diagnostic', max_attempts=1))
            try:
                provider.generate_candidate(PROMPTS[0])
            except ProviderError as error:
                if error.code == 'authentication_error':
                    print('无效密钥验证通过：认证失败明确报错，没有模板结果。')
                    return 0
                raise
            raise ProviderError('diagnostic_error', '无效密钥不应返回音乐候选')
        provider = QwenProvider(settings)
        for prompt in ([args.prompt] if args.prompt else PROMPTS):
            print('正在请求真实千问候选：' + prompt, flush=True)
            candidate, metadata = provider.generate_candidate(prompt)
            folder = OUTPUT / metadata['local_request_id']
            folder.mkdir(parents=True, exist_ok=False)
            (folder / 'candidate.json').write_text(candidate.model_dump_json(indent=2), encoding='utf-8')
            (folder / 'request.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'status': 'candidate_ready', 'metadata': metadata,
                              'creative_plan': candidate.creative_plan,
                              'composition_id': candidate.composition.composition_id,
                              'tempo_bpm': candidate.composition.tempo_bpm,
                              'key_signature': candidate.composition.key_signature,
                              'measures': len(candidate.composition.measures),
                              'file': str(folder / 'candidate.json')}, ensure_ascii=False, indent=2))
        print('真实调用与结构检查通过。指型、时长、听感及成品导出仍由后续任务验证。')
        return 0
    except ProviderError as error:
        print('验证未通过 [' + error.code + ']：' + str(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
