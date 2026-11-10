from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from drugtime.modules.access.application.list_linked_patients import list_linked_patients
from drugtime.modules.access.domain.rules import AccessFacts, ActorRole, Scope
from drugtime.shared.errors import Forbidden, ServiceUnavailable

C = UUID(int=100)
P = UUID(int=1)
Q = UUID(int=2)


def setup(ids=(P, Q), name_map=None):
    events = []
    facts = Mock()
    by_id = {p: AccessFacts(C, p, False, True, True, True) for p in ids}

    def read(uow, caller, admin, patient, scope):
        events.append(("facts", patient))
        assert caller == C and not admin and scope is Scope.LINKED_PATIENTS
        return by_id[patient]

    facts.read.side_effect = read
    log = Mock()
    log.append_allowed.side_effect = lambda *args: events.append(("allowed", args[3]))
    names = Mock()

    def get(uow, patients):
        events.append(("names", tuple(patients)))
        return name_map if name_map is not None else {p: "An" for p in patients}

    names.get.side_effect = get
    candidates = Mock()
    candidates.ids.return_value = list(ids)
    return SimpleNamespace(
        uow=object(),
        events=events,
        by_id=by_id,
        kwargs=dict(
            caller_id=C,
            caller_is_admin=False,
            candidates=candidates,
            facts=facts,
            access_log=log,
            names=names,
            request_audit=Mock(),
        ),
    )


def run(s):
    return list_linked_patients(s.uow, **s.kwargs)


@pytest.mark.parametrize("ids", [(), (P,), (P, Q), (C, P, P, Q)])
def test_list_only_authorized_patients(ids):
    s = setup(ids)
    result = run(s)
    expected = sorted(set(ids) - {C})
    assert [p.patient_id for p in result] == expected
    assert s.kwargs["access_log"].append_allowed.call_count == len(expected)
    for call in s.kwargs["access_log"].append_allowed.call_args_list:
        assert call.args[0] is s.uow
        assert call.args[1:3] == (C, ActorRole.FAMILY)
        assert call.args[4] is Scope.LINKED_PATIENTS
    s.kwargs["access_log"].append_denied.assert_not_called()


@pytest.mark.parametrize(
    "missing",
    ["purpose_consent", "family_sharing_consent", "active_sharing_link", "patient_exists"],
)
def test_filtered_candidates_do_not_write_denied(missing):
    s = setup()
    s.by_id[P] = replace(s.by_id[P], **{missing: False})
    assert [p.patient_id for p in run(s)] == [Q]
    s.kwargs["access_log"].append_denied.assert_not_called()
    s.kwargs["names"].get.assert_called_once_with(s.uow, [Q])


def test_allowed_audit_precedes_name_read():
    s = setup()
    run(s)
    assert s.events == [
        ("facts", P),
        ("allowed", P),
        ("facts", Q),
        ("allowed", Q),
        ("names", (P, Q)),
    ]


def test_empty_list_request_audit_has_no_subject():
    s = setup()
    for p in (P, Q):
        s.by_id[p] = replace(s.by_id[p], purpose_consent=False)
    assert run(s) == []
    s.kwargs["request_audit"].empty.assert_called_once_with(s.uow, C)
    s.kwargs["names"].get.assert_not_called()
    s.kwargs["access_log"].append_allowed.assert_not_called()


def test_admin_denied_before_candidates():
    s = setup()
    s.kwargs["caller_is_admin"] = True
    with pytest.raises(Forbidden, match="khong_co_quyen"):
        run(s)
    s.kwargs["request_audit"].denied.assert_called_once_with(C)
    for key in ("candidates", "facts", "names", "access_log"):
        assert not s.kwargs[key].mock_calls


def test_names_sort_deduplicate_and_minimal_projection():
    a, b, c, d, e = (UUID(int=i) for i in range(1, 6))
    s = setup((e, b, d, a, c, a), {a: " An ", b: "An", c: " an ", d: " ", e: "Án"})
    result = run(s)
    assert [(p.patient_id, p.patient_full_name) for p in result] == [
        (a, "An"),
        (b, "An"),
        (c, "an"),
        (e, "Án"),
        (d, None),
    ]
    assert set(vars(result[0])) == {"patient_id", "patient_full_name"}


@pytest.mark.parametrize(
    "key,method",
    [("access_log", "append_allowed"), ("facts", "read"), ("names", "get"), ("candidates", "ids")],
)
def test_audit_or_name_reader_failure_aborts(key, method):
    s = setup()
    getattr(s.kwargs[key], method).side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        run(s)
    if key != "names":
        s.kwargs["names"].get.assert_not_called()


@pytest.mark.parametrize("admin", [False, True])
def test_request_audit_failure_is_not_suppressed(admin):
    s = setup(())
    s.kwargs["caller_is_admin"] = admin
    getattr(s.kwargs["request_audit"], "denied" if admin else "empty").side_effect = RuntimeError
    with pytest.raises(RuntimeError):
        run(s)


def test_no_name_read_when_pep_denies():
    s = setup((P,))
    s.by_id[P] = replace(s.by_id[P], family_sharing_consent=False)
    assert run(s) == []
    assert s.events == [("facts", P)]


def test_erased_patient_projection_fails_closed_but_null_name_is_valid():
    s = setup((P,), {})
    with pytest.raises(ServiceUnavailable, match="service_unavailable"):
        run(s)
    s = setup((P,), {P: None})
    assert run(s)[0].patient_full_name is None


def test_scope_facts_not_cached_after_revocation():
    s = setup((P,))
    assert len(run(s)) == 1
    s.by_id[P] = replace(s.by_id[P], purpose_consent=False)
    assert run(s) == []
    assert s.kwargs["facts"].read.call_count == 2
