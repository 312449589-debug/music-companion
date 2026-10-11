"""Task 04: genuine Qwen content creation; no fallback, score/audio or playability logic."""
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Literal, Optional

import httpx
from dotenv import dotenv_values
from pydantic import Field, ValidationError, model_validator

from app.schemas.composition import Composition, ContractModel, STANDARD_TUNING, RegenerationConstraints
from .budget import BudgetLedger
from .errors import ProviderError

ROOT = Path(__file__).resolve().parents[3]
MAX_OUTPUT_TOKENS = 8192
MAX_INPUT_BYTES = 24000
MAX_STREAM_SECONDS = 300
MAX_STREAM_BYTES = 2_000_000


def receive_stream(client, url, headers, payload, progress=None, control=None):
    """Reassemble official SSE chunks; unfinished streams are never candidates."""
    started = time.monotonic()
    parts, usage, finish, model = [], None, None, None
    byte_count = chunks = 0
    first_content = None
    last_update = started
    done = False
    with client.stream('POST', url, headers=headers, json=payload,
                       timeout=httpx.Timeout(30, connect=15)) as response:
        if response.status_code != 200:
            return httpx.Response(response.status_code, headers=response.headers), {}
        for line in response.iter_lines():
            if control: control.checkpoint()
            now = time.monotonic()
            if now - started > MAX_STREAM_SECONDS:
                raise httpx.ReadTimeout('bounded stream deadline', request=response.request)
            byte_count += len(line.encode('utf-8'))
            if byte_count > MAX_STREAM_BYTES:
                raise ProviderError('response_error', '模型流式响应超出接收上限，未交付作品')
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                done = True
                break
            try:
                chunk = json.loads(data)
                if not isinstance(chunk, dict) or chunk.get('error'):
                    raise ValueError('chunk')
                model = chunk.get('model', model)
                if chunk.get('usage') is not None:
                    usage = chunk['usage']
                choices = chunk.get('choices', [])
                if choices:
                    choice = choices[0]
                    if choice.get('index', 0) != 0:
                        raise ValueError('choice index')
                    content = choice.get('delta', {}).get('content')
                    if content is not None:
                        if not isinstance(content, str):
                            raise ValueError('content')
                        parts.append(content)
                        if content and first_content is None:
                            first_content = now - started
                            if progress:
                                progress('模型已开始返回数据，正在接收完整音乐作品…')
                    if choice.get('finish_reason') is not None:
                        finish = choice['finish_reason']
                chunks += 1
                if progress and now - last_update >= 15:
                    progress('模型仍在返回数据，尚未完成作品检查与导出…')
                    last_update = now
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                raise ProviderError('response_error', '模型流式响应格式错误，未交付作品') from None
        if not done or finish is None:
            raise ProviderError('response_error', '模型流式响应未完整结束，未交付半成品')
        body = {'model': model, 'usage': usage, 'choices': [
            {'finish_reason': finish, 'message': {'content': ''.join(parts)}}]}
        return httpx.Response(200, headers=response.headers, json=body), {
            'stream_chunks': chunks, 'first_content_seconds': first_content,
            'response_seconds': time.monotonic() - started}


class MusicCandidate(ContractModel):
    creative_plan: str = Field(min_length=1, max_length=1500)
    composition: Composition


class PlannedNote(ContractModel):
    voice: Literal['melody', 'accompaniment']
    offset_tick: int = Field(ge=0, lt=1920, multiple_of=60)
    duration_ticks: Literal[120, 180, 240, 360, 480, 720, 960, 1440, 1920]
    midi_pitch: int = Field(ge=40, le=71)
    tie: Literal['none'] = 'none'


class PlannedBar(ContractModel):
    chord: Optional[str] = None
    notes: List[PlannedNote] = Field(min_length=1)


    @model_validator(mode='after')
    def check_timeline(self):
        if any(n.offset_tick + n.duration_ticks > 1920 for n in self.notes):
            raise ValueError('note_boundary: offset_tick + duration_ticks must be <= 1920')
        melody = sorted((n for n in self.notes if n.voice == 'melody'), key=lambda n: n.offset_tick)
        if any(a.offset_tick + a.duration_ticks > b.offset_tick for a, b in zip(melody, melody[1:])):
            raise ValueError('melody_overlap: melody notes must not overlap')
        return self


class CompactCandidate(ContractModel):
    creative_plan: str = Field(min_length=1, max_length=1500)
    title: str = Field(min_length=1)
    tempo_bpm: float = Field(gt=0)
    key_signature: str = Field(min_length=1)
    bars: List[PlannedBar] = Field(min_length=1)


def expand_candidate(plan, prompt, composition_id):
    """Calculate bookkeeping from AI notes; never invent/change musical content."""
    measures = []
    for bi, bar in enumerate(plan.bars):
        events = []
        for ei, note in enumerate(bar.notes):
            spellings = [(denominator, dotted) for denominator in (1, 2, 4, 8, 16)
                         for dotted in (False, True)
                         if (1920 // denominator) * (3 if dotted else 2) == note.duration_ticks * 2]
            positions = [(string, note.midi_pitch - pitch) for string, pitch in STANDARD_TUNING.items()
                         if 0 <= note.midi_pitch - pitch <= 7]
            if not spellings or not positions:
                raise ValueError('unrepresentable note')
            denominator, dotted = spellings[0]
            string, fret = min(positions, key=lambda item: (item[1], item[0]))
            events.append({'id': f'n-{bi + 1}-{ei + 1}', 'kind': 'note', 'voice': note.voice,
                           'onset_tick': bi * 1920 + note.offset_tick, 'duration_ticks': note.duration_ticks,
                           'notation_duration': denominator, 'dotted': dotted, 'tie': note.tie,
                           'string': string, 'fret': fret, 'midi_pitch': note.midi_pitch})
        measures.append({'id': f'bar-{bi + 1}', 'order': bi + 1, 'start_tick': bi * 1920,
                         'duration_ticks': 1920, 'chord': bar.chord, 'events': events})
    piece = Composition.model_validate_json(json.dumps({
        'schema_version': '1.0', 'composition_id': composition_id, 'origin': 'ai',
        'generator_version': 'qwen-candidate-1', 'prompt': prompt, 'title': plan.title,
        'tempo_bpm': plan.tempo_bpm, 'key_signature': plan.key_signature,
        'ppq': 480, 'time_signature': {'numerator': 4, 'denominator': 4},
        'tuning': STANDARD_TUNING, 'measures': measures}))
    return MusicCandidate(creative_plan=plan.creative_plan, composition=piece)


@dataclass(frozen=True, repr=False)
class QwenSettings:
    api_key: str
    model: str
    base_url: str
    input_price: Decimal
    output_price: Decimal
    budget: Decimal = Decimal('200')
    timeout_seconds: float = 90
    max_attempts: int = 2

    @classmethod
    def load(cls):
        local = dotenv_values(ROOT / '.env')
        def setting(name):
            return (os.environ.get(name) or local.get(name) or '').strip()
        missing = [x for x in ['DASHSCOPE_API_KEY', 'QWEN_MODEL', 'QWEN_BASE_URL',
                              'QWEN_INPUT_PRICE_PER_MILLION_CNY', 'QWEN_OUTPUT_PRICE_PER_MILLION_CNY']
                   if not setting(x)]
        if missing:
            raise ProviderError('config_missing', '未填写本机配置项：' + ', '.join(missing))
        try:
            settings = cls(setting('DASHSCOPE_API_KEY'), setting('QWEN_MODEL'), setting('QWEN_BASE_URL'),
                           Decimal(setting('QWEN_INPUT_PRICE_PER_MILLION_CNY')),
                           Decimal(setting('QWEN_OUTPUT_PRICE_PER_MILLION_CNY')),
                           Decimal(setting('AI_BUDGET_CNY') or '200'))
        except Exception:
            raise ProviderError('config_error', '模型费用或预算配置不是有效数字') from None
        settings.validate()
        return settings

    def validate(self):
        url = urlparse(self.base_url)
        host = url.hostname or ''
        approved_host = host in {'dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com'} or bool(
            re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com', host))
        if (url.scheme != 'https' or not approved_host or url.username or url.password
                or url.port not in (None, 443) or url.query or url.fragment
                or url.path.rstrip('/') != '/compatible-mode/v1'):
            raise ProviderError('config_error', '请使用百炼控制台对应地域的官方 HTTPS 兼容接口地址')
        if not self.api_key or not self.model or len(self.model) > 100:
            raise ProviderError('config_error', '密钥或模型配置为空/无效')
        if not all(x.is_finite() and x > 0 for x in [self.input_price, self.output_price]):
            raise ProviderError('config_error', '输入和输出单价必须是大于0的有效金额')
        if not self.budget.is_finite() or not (0 <= self.budget <= 200):
            raise ProviderError('config_error', '总预算不能超过200元')
        if self.max_attempts not in (1, 2) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ProviderError('config_error', '超时和重试配置无效')


def safe_request_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) else None


class QwenProvider:
    def __init__(self, settings, ledger=None, client=None, sleep=time.sleep, progress=None):
        settings.validate()
        self.settings = settings
        self.ledger = ledger or BudgetLedger(ROOT / 'runtime' / 'ai' / 'budget.json', settings.budget)
        self.client = client
        self.sleep = sleep
        self.progress = progress

    def generate_structure(self, prompt, instructions, schema):
        return self.generate_candidate(prompt, production=True, _structured=(instructions, schema))

    def generate_candidate(self, prompt, *, production=False, correction_feedback=None, regeneration_constraints=None, _structured=None):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1000:
            raise ProviderError('input_error', '提示词需为1到1000个字符的非空文字')
        prompt = prompt.strip()
        if type(production) is not bool or (correction_feedback is not None and
                (not isinstance(correction_feedback, str) or len(correction_feedback) > 2000)):
            raise ProviderError('input_error', '生成模式或修正说明无效')
        if regeneration_constraints is not None and (not production or not isinstance(regeneration_constraints, RegenerationConstraints)):
            raise ProviderError('input_error', '重新生成约束无效')
        local_id = str(uuid.uuid4())
        composition_id = str(uuid.uuid4())
        schema = MusicCandidate.model_json_schema()
        instructions = (
            '你是吉他指弹作曲助手。根据用户听感实际创作旋律与简单和声伴奏，不能只分类或返回固定模板。'
            '这是接入诊断，生成2到4小节的短小候选，不是产品默认长度。返回一个JSON对象，'
            '包含creative_plan和composition，严格遵循下面的数据结构。'
            '只用标准定弦，弦1到6的MIDI音高依次64,59,55,50,45,40；优先空弦和前五品，'
            '允许少量高品位及十六分音符。不要打板或特殊定弦；速度和调性全曲一致。'
            '音符音高等于对应弦空弦音高加品位；onset_tick从全曲起点累计，'
            '旋律和伴奏可同时发声，不要把它们串成单音旋律。ppq=480，使用4/4。'
            '为60秒音频上限预留自然尾音，这个诊断不输出音频。'
            f'composition_id必须为{composition_id}，schema_version为1.0，origin为ai，'
            'generator_version为qwen-candidate-1，prompt与用户文字一致，'
            'source_composition_id、constraints和seed填null；不要Markdown代码围栏。'
            'creative_plan简述如何用旋律、节奏和和声表达用户听感。JSON Schema：'
            + json.dumps(schema, ensure_ascii=False)
        )
        if production:
            instructions = (
                '你是吉他指弹作曲助手，根据用户文字真实创作旋律与简单和声，不能返回固定模板。'
                '返回紧凑JSON，不缩进，不输出说明或代码围栏，遵守下面Schema。'
                '先设计完整、可记忆的旋律乐句，再配支持旋律的简单和声；自主选择在4096token内能完整写完的作品，'
                '不为接近60秒堆叠小节。只输出创作字段，编号与谱面技术字段由程序计算。'
                '标准定弦，弦1到6空弦MIDI音高64,59,55,50,45,40，优先前五品。'
                '固定ppq480、4/4，每小节1920tick；offset_tick为该小节内起点，必须小于1920。'
                '所有offset_tick加duration_ticks必须<=1920。此次生成只用小节内音符，tie必须为none；不写跨小节连音。'
                '四分480、八分240、十六分120、二分960、全音1920；附点为对应长度乘1.5。'
                'notes只列音符，空白时间为休止；不要打板或特殊定弦，速度与调性全曲一致。'
                '创作目标：容易弹奏也要有歌唱性，旋律有方向、有呼吸，节奏灵动，不能像机械音阶练习。'
                '在creative_plan先明确用户听感、核心旋律动机、乐句起伏、节奏变化、伴奏织体和结尾，随后使notes实际体现这个计划。'
                '使用动机的重复与有意义的变化形成呼应，安排舒展与紧凑的对比；不要四小节都重复相同短节奏型。'
                '灵动可以来自八分、附点、弱起或适量切分的组织，不依赖提高BPM、增加大量音符或复杂技巧。'
                '伴奏支持旋律与和声走向，可交替低音与分解和声音，避免每个旋律音都配同节奏低音。'
                '休止用于呼吸、句尾和对比；不要每小节只写前两拍，再统一留后两拍空白来凑作品时长。'
                '乐句应跨小节有连续的方向，安排清楚的句尾和自然收束，而非突然停在和弦循环末端。'
                '按用户描述组织音乐：温暖安静可用舒展的线条与柔和呼应；轻快明亮可用有弹性的小节内节奏与向前发展的动机。'
                '这些是表达手段，必须创作原创音符内容；用户提到参考曲时提取其描述的音乐特点，不输出参考曲的现成旋律。'
                '\n正式生成规则：演奏时长最多57秒，为MP3尾音留3秒；最终文件另行检查60秒上限。'
                '最高第7品，第6—7品音符不得超过全部音符10%；同时按弦品位差最多3，'
                '相邻指型最低按弦品位移动最多3，空弦不计。'
                '必须同时包含melody旋律与accompaniment和声伴奏音符，至少部分同时发声。'
                '每小节用chord声明一个明确和弦，整个小节保持此和声，使用常见调内三和弦或七和弦。'
                '组织主功能、下属功能、属功能到主功能的方向，不用任意音符凑和弦。'
                '每小节实际音符须体现根音与三音，伴奏音均属于声明和弦，首个低音为根音或声明的转位低音。'
                '旋律重要位置有和声支持。若使用经过音或辅助音，前后相邻旋律都紧接无空白，前后级进1或2半音，且下一个音属于它所在小节和弦；经过音同方向级进，辅助音回到前音。其他非和弦音须有明确准备和解决，拿不准则创作和弦音旋律，不可随意填音。'
                '倒数第二小节使用原位V或V7，实际写出根音和导音；导音的结束时刻必须是此小节末尾，下一小节offset_tick=0同时起奏高1半音的主音。最后小节使用原位I（小调用i），旋律最后音为主音。'
                '终止连接处实际导音必须上行半音到同音区主音；使用V7需实际包含七音，终止前仍持续的七音下行到主和弦三音。'
                '最后小节第一拍即建立完整原位主三和弦。'
                '最后旋律主音起奏时，低音主音、和弦三音与五音必须同时实际发声并与旋律共同持续到全曲结束，构成完整主三和弦。'
                '请设计主功能建立、发展和紧张、属到主解决的完整乐句，句尾主音必须由前面音乐自然引出。'
                '这些是本产品本轮的调性创作要求；不要只在creative_plan声称已经落实。'
                '不要借错误音高或变速来绕过规则。JSON Schema：'
                + json.dumps(CompactCandidate.model_json_schema(), ensure_ascii=False))
            if regeneration_constraints is not None:
                instructions += ('\n这是整段重新创作，必须返回tempo_bpm=%s，key_signature=%s。'
                                 '速度和调性优先于用户文字中的变速/转调要求；实际创作不同音符和节奏，不要只改标题。' %
                                 (regeneration_constraints.tempo_bpm, json.dumps(regeneration_constraints.key_signature, ensure_ascii=False)))
            if correction_feedback:
                instructions += '\n上次候选未通过检查，请重新返回完整JSON并修正这些问题：' + correction_feedback
        if _structured is not None:
            instructions = _structured[0] + '\n返回JSON，遵守Schema：' + json.dumps(_structured[1].model_json_schema(), ensure_ascii=False)
        output_limit = 4096 if production else MAX_OUTPUT_TOKENS
        payload = {'model': self.settings.model,
                   'messages': [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': prompt}],
                   'response_format': {'type': 'json_object'}, 'enable_thinking': False,
                   'max_tokens': output_limit, 'stream': production}
        if production:
            payload['stream_options'] = {'include_usage': True}
        raw_payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        if len(raw_payload) > MAX_INPUT_BYTES:
            raise ProviderError('input_error', '请求超出本次诊断的输入上限')
        # Byte-length bound + framing allowance is deliberately conservative; no free-token assumption.
        input_bound = len(raw_payload) + 2048
        estimate = (Decimal(input_bound) * self.settings.input_price
                    + Decimal(output_limit) * self.settings.output_price) / Decimal(1000000)
        owned_client = self.client is None
        client = self.client or httpx.Client(timeout=httpx.Timeout(self.settings.timeout_seconds, connect=15),
                                            follow_redirects=False)
        try:
            for attempt in range(1, self.settings.max_attempts + 1):
                control = getattr(self, 'control', None)
                if control: control.checkpoint()
                reservation = self.ledger.reserve(estimate, self.settings.model, local_id, attempt)
                try:
                    url = self.settings.base_url.rstrip('/') + '/chat/completions'
                    headers = {'Authorization': 'Bearer ' + self.settings.api_key}
                    timing = {}
                    if production:
                        response, timing = receive_stream(client, url, headers, payload, self.progress, control)
                    else:
                        response = client.post(url, headers=headers, json=payload)
                except ProviderError:
                    self.ledger.settle(reservation, 'response_error_unknown_charge')
                    raise
                except (httpx.TimeoutException, httpx.TransportError) as error:
                    self.ledger.settle(reservation, 'network_error_unknown_charge')
                    if attempt < self.settings.max_attempts:
                        self.sleep(1)
                        continue
                    if control: control.checkpoint()
                    reason = '模型请求超时' if isinstance(error, httpx.TimeoutException) else '模型网络连接失败'
                    raise ProviderError('network_error', reason + '；未使用模板替代，未知费用保守计入预算') from None
                request_id = safe_request_id(response.headers.get('x-request-id'))
                if response.status_code != 200:
                    self.ledger.settle(reservation, 'http_error_unknown_charge', http_status=response.status_code,
                                       provider_request_id=request_id)
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < self.settings.max_attempts:
                        self.sleep(1)
                        continue
                    if response.status_code in (401, 403):
                        raise ProviderError('authentication_error', '百炼拒绝认证或权限，请检查密钥地域和模型权限')
                    raise ProviderError('provider_error', f'百炼接口调用失败（HTTP {response.status_code}），没有生成候选')
                try:
                    body = response.json()
                    usage = body['usage']
                    inp, out = usage['prompt_tokens'], usage['completion_tokens']
                    if any(type(n) is not int or n < 0 for n in [inp, out]):
                        raise ValueError('usage')
                    cost = (Decimal(inp) * self.settings.input_price + Decimal(out) * self.settings.output_price) / Decimal(1000000)
                except (ValueError, TypeError, KeyError):
                    self.ledger.settle(reservation, 'response_error_unknown_charge', provider_request_id=request_id)
                    raise ProviderError('response_error', '供应商响应缺少有效用量，无法可靠计费，停止处理') from None
                self.ledger.settle(reservation, 'response_received', cost, input_tokens=inp, output_tokens=out,
                                   provider_request_id=request_id, provider_model=safe_request_id(body.get('model')),
                                   estimated_cost_cny=str(cost))
                try:
                    choice = body['choices'][0]
                    if choice['finish_reason'] != 'stop':
                        raise ValueError('incomplete')
                    if _structured is not None:
                        candidate = _structured[1].model_validate_json(choice['message']['content'])
                    elif production:
                        plan = CompactCandidate.model_validate_json(choice['message']['content'])
                        candidate = expand_candidate(plan, prompt, composition_id)
                    else:
                        candidate = MusicCandidate.model_validate_json(choice['message']['content'])
                    piece = candidate.composition if _structured is None else None
                    if _structured is None and (piece.origin != 'ai' or piece.composition_id != composition_id or piece.prompt != prompt
                            or piece.generator_version != 'qwen-candidate-1' or piece.schema_version != '1.0'):
                        raise ValueError('metadata')
                except (ValidationError, ValueError, TypeError, KeyError, IndexError) as error:
                    self.ledger.settle(reservation, 'invalid_music_structure', cost)
                    if isinstance(error, ValidationError):
                        # Only schema locations/types; never echo raw model values or responses.
                        fields = ['.'.join(str(x) for x in item['loc']) + ':' + item['type']
                                  for item in error.errors(include_input=False)[:8]]
                        detail = '字段检查失败：' + '; '.join(fields)
                        if any('note_boundary:' in item['msg'] for item in error.errors(include_input=False)):
                            detail += '；音符起点加时值不得超过1920tick'
                        if any('melody_overlap:' in item['msg'] for item in error.errors(include_input=False)):
                            detail += '；旋律音符不得重叠'
                    elif isinstance(error, ValueError) and str(error) == 'incomplete':
                        detail = '模型输出未完整结束，请缩短候选或减少冗余字段'
                    else:
                        detail = '候选JSON或音符记谱字段无效，请遵守Schema'
                    raise ProviderError('structure_error', '模型返回的音乐数据不符合要求，未交付作品；请重试。',
                                        correction_feedback=detail, receipt={'local_request_id':local_id,
                                            'provider_request_id':request_id, 'configured_model':self.settings.model,
                                            'provider_model':safe_request_id(body.get('model')), 'attempt':attempt,
                                            'input_tokens':inp, 'output_tokens':out, 'estimated_cost_cny':str(cost), **timing}) from None
                self.ledger.settle(reservation, 'candidate_ready', cost)
                return candidate, {'local_request_id': local_id, 'provider_request_id': request_id,
                                   'configured_model': self.settings.model,
                                   'provider_model': safe_request_id(body.get('model')),
                                   'attempt': attempt, 'input_tokens': inp, 'output_tokens': out,
                                   'estimated_cost_cny': str(cost), **timing}
        finally:
            if owned_client:
                client.close()
