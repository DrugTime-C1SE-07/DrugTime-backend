from fastapi import APIRouter

router = APIRouter(tags=["interaction"])

# TODO: POST /patients/{id}/interaction-checks (DK3: access -> medication -> catalog -> evaluator);
#       Admin: CRUD quy tắc tương tác (xóa mềm)
