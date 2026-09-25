from fastapi import APIRouter

router = APIRouter(tags=["ai_meal"])

# TODO: POST /patients/{id}/meal-suggestions (DK6: access(goi_y_bua_an) -> medication ->
#       LLM -> interaction lọc món -> lưu + disclaimer do backend gắn)
