from dataclasses import replace
from pathlib import Path

import pytest
from app.music.audio import AudioExportError, AudioTools, export_mp3
from app.schemas.composition import Composition


def fixture():
    return Composition.model_validate_json((Path(__file__).parents[1] / 'fixtures' / 'diagnostic-fingerstyle.json').read_text())


def test_missing_tools_preserves_existing_output(tmp_path):
    output = tmp_path / 'previous.mp3'
    output.write_bytes(b'previous-result')
    tools = replace(AudioTools.load(), ffmpeg=tmp_path / 'absent')
    with pytest.raises(AudioExportError) as error:
        export_mp3(fixture(), output, tools)
    assert error.value.code == 'tool_missing'
    assert output.read_bytes() == b'previous-result'


def test_tail_budget_rejects_before_starting_tools(tmp_path):
    source = fixture()
    source.tempo_bpm = 8.0
    with pytest.raises(AudioExportError) as error:
        export_mp3(source, tmp_path / 'rejected.mp3')
    assert error.value.code == 'tail_budget'
    assert not (tmp_path / 'rejected.mp3').exists()


def test_missing_soundfont_does_not_create_fake_mp3(tmp_path):
    tools = replace(AudioTools.load(), soundfont=tmp_path / 'absent.sf3')
    with pytest.raises(AudioExportError) as error:
        export_mp3(fixture(), tmp_path / 'rejected.mp3', tools)
    assert error.value.code == 'soundfont_missing'
    assert not (tmp_path / 'rejected.mp3').exists()
