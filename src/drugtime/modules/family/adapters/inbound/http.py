from fastapi import APIRouter

router = APIRouter(prefix="/family", tags=["family"])

# TODO: POST /family/link-codes, POST /family/links (dùng mã; yêu cầu consent family_sharing của
#       patient qua consent.api), PATCH /family/links/{id}/sharing, DELETE /family/links/{id}
