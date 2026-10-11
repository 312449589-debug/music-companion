"""Task 03 schema checks only; no musical-quality or playability claim."""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from pydantic import ValidationError
from app.schemas.composition import Composition, STANDARD_TUNING


def load_composition(path):
    # Validate JSON directly: object keys are strings, converted to integer tuning keys by Pydantic.
    return Composition.model_validate_json(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=BACKEND / "fixtures" / "diagnostic-fingerstyle.json")
    parser.add_argument("--invalid-string", action="store_true")
    parser.add_argument("--missing-field", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
        if args.invalid_string:
            data["measures"][0]["events"][0]["string"] = 7
        if args.missing_field:
            data.pop("tempo_bpm", None)
        piece = Composition.model_validate_json(json.dumps(data))
    except ValidationError as error:
        print("结构检查失败：")
        for issue in error.errors(include_input=False, include_url=False):
            print(f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}")
        return 1
    except (OSError, json.JSONDecodeError) as error:
        print(f"读取诊断数据失败：{error}")
        return 1
    print("结构检查通过（不是音乐规则或可演奏性验收）")
    print(json.dumps({"composition_id": piece.composition_id, "origin": piece.origin,
                      "tempo_bpm": piece.tempo_bpm, "key_signature": piece.key_signature,
                      "ppq": piece.ppq, "measure_count": len(piece.measures),
                      "voices": sorted({event.voice for bar in piece.measures for event in bar.events}),
                      "standard_tuning": STANDARD_TUNING, "fixture_tuning": piece.tuning},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
