from pathlib import Path

import pytest
from pypdf import PdfWriter
from app.music.pdf import PdfExportError, export_pdf, inspect_pdf
from app.schemas.composition import Composition


def fixture():
    return Composition.model_validate_json((Path(__file__).parents[1] / 'fixtures' / 'diagnostic-fingerstyle.json').read_text())


def test_blank_pdf_cannot_be_accepted_as_a_score(tmp_path):
    blank = tmp_path / 'blank.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(blank)
    with pytest.raises(PdfExportError) as failure:
        inspect_pdf(blank, fixture())
    assert failure.value.code == 'invalid_pdf'


def test_print_url_is_local_and_invalid_url_preserves_previous_output(tmp_path):
    output = tmp_path / 'previous.pdf'
    output.write_bytes(b'previous-result')
    with pytest.raises(PdfExportError) as failure:
        export_pdf(fixture(), output, base_url='https://example.com')
    assert failure.value.code == 'print_url'
    assert output.read_bytes() == b'previous-result'
