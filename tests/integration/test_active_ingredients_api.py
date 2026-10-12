"""Tra cứu hoạt chất cho admin (task 2.16, AC12), Postgres thật."""

from uuid import uuid4

BASE = "/admin/active-ingredients"


def test_search_by_name_and_alias__AC12(client, admin_auth, make):
    _, h = admin_auth
    tag = uuid4().hex[:10]
    warf = make.ingredient(name=f"Warfarin-{tag}", aliases=(f"Coumadin-{tag}",))
    make.ingredient(name=f"Other-{tag}")

    by_name = client.get(BASE, params={"q": f"warfarin-{tag.upper()}"}, headers=h).json()
    assert [i["id"] for i in by_name["items"]] == [warf] and by_name["total"] == 1
    assert by_name["items"][0]["aliases"] == [f"Coumadin-{tag}"]
    assert set(by_name["items"][0]) == {
        "id",
        "standard_name",
        "atc_code",
        "pharmacological_group",
        "aliases",
    }
    by_alias = client.get(BASE, params={"q": f"coumadin-{tag}"}, headers=h).json()
    assert [i["id"] for i in by_alias["items"]] == [warf]
    both = client.get(BASE, params={"q": tag}, headers=h).json()
    assert [i["standard_name"] for i in both["items"]] == [f"Other-{tag}", f"Warfarin-{tag}"]


def test_wildcards_are_literal(client, admin_auth, make):
    _, h = admin_auth
    tag = uuid4().hex[:10]
    make.ingredient(name=f"plain-{tag}")
    assert client.get(BASE, params={"q": f"%{tag}"}, headers=h).json()["total"] == 0
    assert client.get(BASE, params={"q": f"_lain-{tag}"}, headers=h).json()["total"] == 0


def test_by_medication__AC12(client, admin_auth, make):
    _, h = admin_auth
    a, b = make.ingredient(), make.ingredient()
    med = make.medication_with([a, b])
    page = client.get(BASE, params={"medication_id": med}, headers=h).json()
    assert sorted(i["id"] for i in page["items"]) == sorted([a, b]) and page["total"] == 2
    page = client.get(BASE, params={"medication_id": med, "limit": 1}, headers=h).json()
    assert len(page["items"]) == 1 and page["total"] == 2


def test_unknown_or_unmapped_medication_empty__AC12(client, admin_auth, make):
    _, h = admin_auth
    for med in (2_000_000_000, make.medication_with([])):
        assert client.get(BASE, params={"medication_id": med}, headers=h).json() == {
            "items": [],
            "total": 0,
        }
