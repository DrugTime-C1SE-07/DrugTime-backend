"""Sinh file .importlinter từ danh sách module.

Chạy lại mỗi khi thêm module:  python scripts/gen_import_contracts.py
Ma trận import được phép giữa các module nằm ở tests/architecture/test_module_dependencies.py.
"""

from pathlib import Path

MODULES = [
    "identity",
    "consent",
    "family",
    "access",
    "catalog",
    "interaction",
    "medication",
    "adherence",
    "ai_meal",
    "health",
]
PKG = "drugtime.modules"
LAYERS = ["api", "adapters", "application", "domain"]
IO_LIBS = [
    "fastapi",
    "starlette",
    "sqlalchemy",
    "psycopg",
    "redis",
    "celery",
    "httpx",
    "jwt",
    "pydantic_settings",
]
OUTSIDE = ["drugtime.runtime", "drugtime.notification_gateway", "drugtime.main", "drugtime.worker"]


def block(key: str, **fields: object) -> str:
    lines = [f"[importlinter:contract:{key}]"]
    for name, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{name} =")
            lines += [f"    {v}" for v in value]
        else:
            lines.append(f"{name} = {value}")
    return "\n".join(lines)


def main() -> None:
    parts = [
        "# FILE SINH TỰ ĐỘNG bởi scripts/gen_import_contracts.py. Không sửa tay.",
        "[importlinter]\nroot_package = drugtime\ninclude_external_packages = True",
        block(
            "hexagon-layers",
            name="Each module: api > adapters > application > domain",
            type="layers",
            layers=LAYERS,
            containers=[f"{PKG}.{m}" for m in MODULES],
        ),
        block(
            "pure-core",
            name="domain/application do not import frameworks or I/O libraries",
            type="forbidden",
            source_modules=[
                f"{PKG}.{m}.{layer}" for m in MODULES for layer in ("domain", "application")
            ],
            forbidden_modules=IO_LIBS,
        ),
        block(
            "shared-kernel",
            name="shared does not depend on modules or entrypoints",
            type="forbidden",
            source_modules=["drugtime.shared"],
            forbidden_modules=[PKG, *OUTSIDE],
        ),
        block(
            "modules-no-entrypoints",
            name="modules do not import runtime, notification_gateway or entrypoints",
            type="forbidden",
            source_modules=[PKG],
            forbidden_modules=OUTSIDE,
        ),
    ]
    for m in MODULES:
        others = [f"{PKG}.{o}" for o in MODULES if o != m]
        parts.append(
            block(
                f"boundary-{m}",
                name=f"Others use {m} only through {m}.api",
                type="forbidden",
                source_modules=[*others, "drugtime.runtime", "drugtime.notification_gateway"],
                forbidden_modules=[f"{PKG}.{m}.{layer}" for layer in LAYERS[1:]],
                allow_indirect_imports="True",
            )
        )
        parts.append(
            block(
                f"core-isolation-{m}",
                name=f"{m} application/domain do not import other modules",
                type="forbidden",
                source_modules=[f"{PKG}.{m}.application", f"{PKG}.{m}.domain"],
                forbidden_modules=others,
            )
        )
    out = Path(__file__).resolve().parents[1] / ".importlinter"
    out.write_text("\n\n".join(parts) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
