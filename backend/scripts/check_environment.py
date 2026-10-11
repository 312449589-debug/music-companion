"""Task 02 diagnostics only; does not compose music or call AI."""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
OUTPUT = ROOT / "runtime" / "diagnostics"


def resolve_path(variable, fallback):
    value = os.getenv(variable) or fallback
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def tool_path(variable, name):
    value = os.getenv(variable)
    if value:
        return resolve_path(variable, value)
    local = ROOT / ".tools" / "audio" / "bin" / name
    return local if local.is_file() else Path(shutil.which(name) or str(local))


def execute(command):
    return subprocess.run([str(x) for x in command], check=True,
                          capture_output=True, text=True, timeout=60)


def version(path, argument):
    if not path.is_file():
        raise RuntimeError("缺失可执行文件；安装后在 .env 中设置对应路径")
    result = execute([path, argument])
    return (result.stdout + result.stderr).splitlines()[0]


def browser_probe():
    from playwright.sync_api import sync_playwright
    browsers = resolve_path("PLAYWRIGHT_BROWSERS_PATH", ".tools/browsers")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            page = browser.new_page()
            page.set_content('<html lang="zh-CN"><body style="font-family:Songti SC">'
                             '<h1>音乐伙伴环境检查</h1><p>Chromium 中文字体测试 ABC123</p>'
                             '</body></html>')
            page.evaluate("document.fonts.ready")
            page.pdf(path=str(OUTPUT / "font-check.pdf"), format="A4")
            return browser.version


def guitar_probe(fluid, font):
    # A fixed diagnostic sequence of standard open strings; not a composition exporter.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    track = bytearray(b"\x00\xff\x51\x03\x07\xa1\x20\x00\xc0\x18")
    for pitch in [40, 45, 50, 55, 59, 64]:
        track.extend(bytes([0, 0x90, pitch, 88]))
        track.extend(bytes([0x81, 0x70, 0x80, pitch, 0]))  # 240 ticks
    track.extend(b"\x00\xff\x2f\x00")
    midi = OUTPUT / "open-strings.mid"
    midi.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
                     + b"MTrk" + struct.pack(">I", len(track)) + track)
    wav = OUTPUT / "open-strings.wav"
    execute([fluid, "-ni", "-F", wav, "-r", "44100", font, midi])
    with wave.open(str(wav)) as audio:
        frames = audio.readframes(audio.getnframes())
        if audio.getnframes() == 0 or not any(frames):
            raise RuntimeError("音色测试得到空音频或全静音")
        return {"file": str(wav), "seconds": round(audio.getnframes() / audio.getframerate(), 3),
                "sample_rate": audio.getframerate(), "program_zero_based": 24}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sound-check", action="store_true")
    parser.add_argument("--play", action="store_true", help="用 macOS afplay 试听诊断音频")
    args = parser.parse_args()
    if args.play:
        args.sound_check = True
    results = []

    def check(name, probe, remedy):
        try:
            detail = probe()
            results.append({"item": name, "status": "可用", "detail": detail})
        except Exception as error:
            # Tool output may contain paths; do not print environment variables or credentials.
            detail = type(error).__name__
            if name == "Chromium" and "Permission denied" in str(error):
                detail = "当前执行环境限制 macOS 浏览器进程通信；请双击本机环境检查入口验证"
            if name == "本机试听":
                detail = "当前执行环境无法启动系统音频输出；请从本机环境检查入口试听"
            results.append({"item": name, "status": "缺失或检查失败",
                            "detail": detail, "remedy": remedy})

    fluid = tool_path("FLUIDSYNTH_PATH", "fluidsynth")
    ffmpeg = tool_path("FFMPEG_PATH", "ffmpeg")
    font = resolve_path("SOUNDFONT_PATH", ".tools/soundfonts/FluidR3Mono_GM.sf3")
    check("FluidSynth", lambda: version(fluid, "--version"), "安装 conda-forge fluidsynth，设置 FLUIDSYNTH_PATH")
    check("FFmpeg", lambda: version(ffmpeg, "-version"), "安装 conda-forge ffmpeg，设置 FFMPEG_PATH")
    check("Chromium", browser_probe, "安装 requirements-dev.txt，再设置 PLAYWRIGHT_BROWSERS_PATH 并安装 Chromium")
    check("中文字体", lambda: next(str(p) for p in [Path('/System/Library/Fonts/Supplemental/Songti.ttc'),
          Path('/System/Library/Fonts/PingFang.ttc')] if p.is_file()), "安装可用中文字体，检查 font-check.pdf")
    def font_probe():
        with font.open('rb') as handle:
            header = handle.read(12)
        if not header.startswith(b'RIFF') or header[8:12] != b'sfbk':
            raise RuntimeError('音色不是有效 SoundFont 文件')
        return {"path": str(font), "bytes": font.stat().st_size,
                "license_record": "docs/依赖工具与参数记录.md"}
    check("SoundFont", font_probe, "按音色来源说明下载文件，设置 SOUNDFONT_PATH")
    if args.sound_check:
        check("吉他开放弦音色", lambda: guitar_probe(fluid, font), "先解决 FluidSynth/SoundFont 错误再重试")
    sound_ok = any(x['item'] == '吉他开放弦音色' and x['status'] == '可用' for x in results)
    if args.play and sound_ok:
        check("本机试听", lambda: execute(['afplay', OUTPUT / 'open-strings.wav']).returncode,
              "在播放器打开 runtime/diagnostics/open-strings.wav")
    # Deliberately report only presence, never secret value or prefix. No paid API request.
    results.append({"item": "AI 配置", "status": "待接入时验证", "detail": {
        key: bool(os.getenv(key)) for key in ['DASHSCOPE_API_KEY', 'QWEN_MODEL', 'QWEN_BASE_URL']}})
    results.append({"item": "开发测试预算", "status": "已确认", "detail": "总额不超过人民币 200 元；本检查不调用模型"})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'environment-report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return int(any(item['status'] == '缺失或检查失败' for item in results))


if __name__ == '__main__':
    sys.exit(main())
