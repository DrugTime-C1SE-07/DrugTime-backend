from contextlib import contextmanager
from uuid import uuid4

import pytest

from drugtime.modules.consent.application.execute_erasure import execute_erasure
from drugtime.modules.consent.domain.deletion_request import DeletionRequest, DeletionStatus


class FakeRequests:
    def __init__(self, req):
        self.req, self.completed, self.error = req, False, None

    def get(self, uow, request_id):
        return self.req

    def approved_ids(self, uow):
        return [self.req.id]

    def mark_completed(self, uow, request_id):
        self.completed = True

    def record_error(self, uow, request_id, error):
        self.error = error


class Eraser:
    def __init__(self, name, calls):
        self.name, self.calls = name, calls

    def erase_user(self, uow, user_id):
        self.calls.append(self.name)


@contextmanager
def fake_uow():
    yield object()


def run(status, remover):
    calls = []
    req = DeletionRequest(uuid4(), uuid4(), status)
    repo = FakeRequests(req)
    erasers = [Eraser(n, calls) for n in ("ai_meal", "interaction", "identity")]
    execute_erasure(
        req.id, requests=repo, erasers=erasers, account_remover=remover, uow_factory=fake_uow
    )
    return calls, repo


class OkRemover:
    def delete_account(self, user_id):
        pass


class FailingRemover:
    def delete_account(self, user_id):
        raise RuntimeError("auth down")


def test_runs_erasers_in_given_order_then_completes():
    calls, repo = run(DeletionStatus.APPROVED, OkRemover())
    assert calls == ["ai_meal", "interaction", "identity"] and repo.completed


def test_not_approved_does_nothing():
    calls, repo = run(DeletionStatus.PENDING, OkRemover())
    assert calls == [] and not repo.completed


def test_auth_failure_keeps_request_open_with_error():
    calls = []
    req = DeletionRequest(uuid4(), uuid4(), DeletionStatus.APPROVED)
    repo = FakeRequests(req)
    with pytest.raises(RuntimeError):
        execute_erasure(
            req.id,
            requests=repo,
            erasers=[Eraser("x", calls)],
            account_remover=FailingRemover(),
            uow_factory=fake_uow,
        )
    assert not repo.completed and "auth down" in repo.error
