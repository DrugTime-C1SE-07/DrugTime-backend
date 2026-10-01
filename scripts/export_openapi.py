"""Sinh OpenAPI từ Backend API để đối chiếu với hợp đồng.

`api_contract/openapi.json` là bản viết tay, là nguồn chuẩn; script này KHÔNG ghi đè nó.
Mặc định ghi ra `api_contract/openapi.generated.json` (đã có trong .gitignore của api_contract).
Đối chiếu tự động: tests/unit/test_contract_medication.py.

    python scripts/export_openapi.py [--out <đường-dẫn>]
"""

import argparse
import json
from pathlib import Path

from drugtime.main import create_app

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "api_contract"
DEFAULT_OUT = CONTRACT_DIR / "openapi.generated.json"
CONTRACT = CONTRACT_DIR / "openapi.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    out = parser.parse_args().out.resolve()
    if out == CONTRACT.resolve():
        parser.error(f"{CONTRACT} is the hand-written contract; choose another --out")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
