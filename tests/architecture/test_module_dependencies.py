"""Import giữa các module phải nằm trong ma trận này (khớp C4 spec K15–K27, W07–W12).

- identity: mọi module có endpoint dùng identity.api.current_user (note trên sơ đồ L3).
- consent gọi các module khác khi xóa dữ liệu (W13–W18) qua port UserDataEraser được inject
  ở runtime/job_runner.py, nên consent KHÔNG import các module đó.
Thêm quan hệ mới: cập nhật C4 spec trước, rồi mới sửa ma trận này.
"""

import grimp
import pytest

ALLOWED: dict[str, set[str]] = {
    "identity": set(),
    "health": set(),
    "consent": {"identity"},
    "family": {"identity", "consent"},
    "catalog": {"identity"},
    "access": {"identity", "family", "consent"},
    "medication": {"identity", "access", "catalog"},
    "adherence": {"identity", "access", "medication"},
    "interaction": {"identity", "access", "medication", "catalog"},
    "ai_meal": {"identity", "access", "medication", "interaction"},
}
PKG = "drugtime.modules"


@pytest.fixture(scope="module")
def graph():
    return grimp.build_graph("drugtime")


def test_matrix_is_acyclic():
    seen, done = set(), set()

    def visit(m):
        assert m not in seen or m in done, f"cycle through {m}"
        if m in done:
            return
        seen.add(m)
        for dep in ALLOWED[m]:
            visit(dep)
        done.add(m)

    for m in ALLOWED:
        visit(m)


@pytest.mark.parametrize("src", sorted(ALLOWED))
def test_imports_follow_matrix(graph, src):
    actual = {
        dst
        for dst in ALLOWED
        if dst != src
        and graph.direct_import_exists(
            importer=f"{PKG}.{src}", imported=f"{PKG}.{dst}", as_packages=True
        )
    }
    assert actual <= ALLOWED[src], f"{src} imports {actual - ALLOWED[src]} (not allowed)"
