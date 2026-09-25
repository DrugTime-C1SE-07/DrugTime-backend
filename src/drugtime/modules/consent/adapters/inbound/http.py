from fastapi import APIRouter, Depends

from drugtime.modules.identity import api as identity

router = APIRouter(tags=["consent"])


@router.get("/consents")
def list_my_consents(user: identity.CurrentUser = Depends(identity.current_user)) -> list[dict]:
    raise NotImplementedError  # TODO: task consent (Sprint 1)


# TODO: POST /consents, POST /consents/{purpose}/withdraw, POST /deletion-requests,
#       Admin: GET /admin/deletion-requests, POST /admin/deletion-requests/{id}/approve
#       (approve: set da_duyet trong transaction, rồi job_queue.enqueue_erasure)
