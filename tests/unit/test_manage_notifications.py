from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest

from drugtime.modules.adherence.application.manage_notifications import (
    get_notification,
    list_my_notifications,
)
from drugtime.modules.adherence.domain.alert import NotificationRecord
from drugtime.shared.errors import Forbidden, NotFound, ServiceUnavailable


def setup():
    user, patient, denied = uuid4(), uuid4(), uuid4()
    events = []
    records = [
        NotificationRecord(
            i,
            user,
            p,
            "canh_bao_bo_lo_lieu_nguoi_than",
            "content",
            read,
            datetime(2026, 10, 22, tzinfo=UTC),
        )
        for i, p, read in [(3, denied, False), (2, patient, True), (1, patient, False)]
    ]
    repo = Mock()
    repo.metadata.side_effect = lambda *a: (
        events.append("metadata")
        or [(r.id, r.about_patient_user_id) for r in records if len(a) == 2 or a[2] == r.id]
    )

    def content(uow, uid, ids):
        events.append("content")
        assert ids == [2, 1] or ids == [1]
        return [r for r in records if r.id in ids]

    repo.authorized_records.side_effect = content
    repo.mark_as_read.side_effect = lambda *a: replace(records[-1], is_read=a[-1])

    def authorize(uow, uid, admin, pid):
        events.append("pep")
        if pid == denied:
            raise Forbidden("khong_co_quyen")

    access = Mock(authorize_adherence=Mock(side_effect=authorize))
    kwargs = dict(
        user_id=user,
        notifications=repo,
        access=access,
        patient_names=Mock(get_patient_name=Mock(return_value="Patient")),
    )
    return events, repo, access, kwargs


def test_list_authorizes_before_content_filters_counts_before_page_and_rechecks():
    events, repo, access, kwargs = setup()
    result = list_my_notifications(None, is_read=True, limit=1, offset=0, **kwargs)
    assert result.total == 1 and result.unread_count == 1
    assert [r.id for r in result.items] == [2]
    assert events == ["metadata", "pep", "pep", "content"]
    list_my_notifications(None, is_read=None, limit=1, offset=1, **kwargs)
    assert access.authorize_adherence.call_count == 4


@pytest.mark.parametrize("error", [RuntimeError("facts"), ServiceUnavailable("audit")])
def test_audit_or_facts_failure_never_reads_content(error):
    _, repo, access, kwargs = setup()
    access.authorize_adherence.side_effect = error
    with pytest.raises(ServiceUnavailable, match="notification_access_unavailable"):
        list_my_notifications(None, is_read=None, limit=20, offset=0, **kwargs)
    repo.authorized_records.assert_not_called()


@pytest.mark.parametrize("nid,error", [(99, NotFound), (3, Forbidden)])
def test_detail_patch_denied_before_content_or_update(nid, error):
    _, repo, _, kwargs = setup()
    with pytest.raises(error):
        get_notification(None, notification_id=nid, is_read=True, **kwargs)
    repo.authorized_records.assert_not_called()
    repo.mark_as_read.assert_not_called()


def test_patch_only_updates_after_pep_and_preserves_dose_snapshot():
    events, repo, _, kwargs = setup()
    record = get_notification(None, notification_id=1, is_read=True, **kwargs)
    assert record.is_read and record.about_patient_name == "Patient"
    assert events == ["metadata", "pep"]
    repo.mark_as_read.assert_called_once_with(None, 1, kwargs["user_id"], True)
