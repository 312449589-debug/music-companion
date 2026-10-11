"""Task10: Chromium prints the same source-derived tablature as the webpage."""
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError, sync_playwright
from pypdf import PdfReader
from app.music.alphatex import to_alphatex
from app.music.validation import validate_composition

ROOT = Path(__file__).resolve().parents[3]


class PdfExportError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def inspect_pdf(path, piece):
    try:
        reader = PdfReader(path)
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        if not reader.pages or not all((page.extract_text() or '').strip() for page in reader.pages):
            raise ValueError('blank')
        if piece.composition_id not in text or '全曲结束' not in text:
            raise ValueError('missing identity/end')
        return {'pages': len(reader.pages), 'bytes': path.stat().st_size,
                'composition_id': piece.composition_id, 'measures': len(piece.measures)}
    except Exception:
        raise PdfExportError('invalid_pdf', 'PDF为空白、损坏或缺少作品标识/末尾，未交付') from None


def export_pdf(piece, destination, base_url='http://127.0.0.1:8000', alphatex_override=None):
    validate_composition(piece)
    parsed = urlparse(base_url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PdfExportError('print_url', '打印服务必须使用本机HTTP地址')
    payload = {'composition': piece.model_dump(mode='json'),
               'alphatex': to_alphatex(piece) if alphatex_override is None else alphatex_override}
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.tools' / 'browsers'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pdf-', dir=str(destination.parent)) as temporary:
        output = Path(temporary) / 'score.pdf'
        try:
            with sync_playwright() as playwright:
                with playwright.chromium.launch() as browser:
                    page = browser.new_page(viewport={'width': 794, 'height': 1123})
                    page.add_init_script('window.__PRINT_DATA__ = ' + json.dumps(payload, ensure_ascii=False) + ';')
                    page.emulate_media(media='print')
                    response = page.goto(base_url.rstrip('/') + '/diagnostics/print', wait_until='networkidle', timeout=30000)
                    if response is None or response.status != 200:
                        raise PdfExportError('print_page', '本机打印页面未就绪，请启动服务并构建前端')
                    page.wait_for_function("window.__PDF_STATUS__ === 'ready' || window.__PDF_STATUS__ === 'error'", timeout=30000)
                    if page.evaluate('window.__PDF_STATUS__') != 'ready':
                        raise PdfExportError('score_render', '谱面渲染失败，未导出空白PDF')
                    page.evaluate('document.fonts.ready')
                    page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                    if page.locator('.at-surface svg').count() == 0:
                        raise PdfExportError('score_render', '打印页没有实际谱面图形，未导出PDF')
                    page.pdf(path=str(output), format='A4', print_background=True, prefer_css_page_size=True,
                             display_header_footer=True, header_template='<span></span>',
                             footer_template='<div style="font-size:9px;width:100%;text-align:center"><span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        except PlaywrightError:
            raise PdfExportError('browser_failed', 'Chromium启动、加载或打印失败；请检查本机浏览器执行环境，未交付PDF') from None
        report = inspect_pdf(output, piece)
        os.replace(output, destination)
        return report
