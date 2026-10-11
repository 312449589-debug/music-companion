"""Confirmed production tempo range; historical artifacts stay readable."""
import math
import re

from app.providers.errors import ProviderError

MIN_BPM = 60
MAX_BPM = 120


def require_tempo(tempo, *, source=False):
    if not math.isfinite(tempo) or not MIN_BPM <= tempo <= MAX_BPM:
        message = ('原作品速度超出首版60–120 BPM范围，不能保持原速度重新生成；旧作品仍可试听和下载。'
                   if source else '首版速度范围为60–120 BPM（含边界），请修改速度要求后重试。')
        raise ProviderError('tempo_out_of_range', message)


def check_prompt_tempo(prompt):
    # Recognize common explicit BPM wording; no mood-to-tempo guessing.
    for pattern in (r'([-+]?\d+(?:\.\d+)?)\s*BPM\b', r'\bBPM\s*[:：=]?\s*([-+]?\d+(?:\.\d+)?)'):
        for value in re.findall(pattern, prompt, flags=re.IGNORECASE):
            require_tempo(float(value))
