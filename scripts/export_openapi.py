"""Ghi OpenAPI của Backend API ra ../api-contract/openapi.json (hợp đồng cho Mobile và Admin)."""

import json
from pathlib import Path

from drugtime.main import create_app

OUT = Path(__file__).resolve().parents[2] / "api-contract" / "openapi.json"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
