from fastapi import APIRouter, Depends

from drugtime.modules.identity import api as identity

router = APIRouter(prefix="/admin/access-logs", tags=["access"])


@router.get("")
def list_access_logs(admin: identity.CurrentUser = Depends(identity.require_admin)) -> list[dict]:
    raise NotImplementedError  # TODO: lọc theo patient/actor, phân trang (index v9)
