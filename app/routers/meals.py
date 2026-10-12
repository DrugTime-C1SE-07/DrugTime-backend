"""Router 8: AI Meal Suggestions (Schema v9: English naming, DPIA bounded - FR05)."""
import uuid
from typing import List
from fastapi import APIRouter, Depends, status, HTTPException
from app.schemas.common import ResponseEnvelope
from app.schemas.meals import (
    MealSuggestionGenerateRequest, MealSuggestionJobResponse,
    MealSuggestionJobStatusResponse, MealSuggestionResponse
)
from app.core.security import CurrentUser, get_current_user
from app.core.access_control import require_patient_read, require_patient_write
from app.mock_db import db, current_time_iso

router = APIRouter(prefix="", tags=["8. AI Meal Suggestions"])

@router.post(
    "/patients/{patient_id}/meal-suggestions/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResponseEnvelope[MealSuggestionJobResponse],
    summary="Khởi tạo tiến trình sinh gợi ý món ăn dinh dưỡng qua AI (Bất đồng bộ - 202 Accepted)",
    description="Tuân thủ NFR04 (phản hồi < 2s) và DPIA. Gửi tác vụ vào hàng đợi và trả về job_id để client poll kết quả."
)
def generate_meal_suggestion_async(
    patient_id: str,
    req: MealSuggestionGenerateRequest,
    actor_role: str = Depends(require_patient_write("goi_y_bua_an"))
):
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    
    # Store initial job state
    db.meal_jobs[job_id] = {
        "job_id": job_id,
        "patient_id": patient_id,
        "status": "completed", # For immediate mock testing response
        "created_at": current_time_iso(),
        "result": {
            "id": len(db.meal_suggestions) + 1,
            "user_id": patient_id,
            "meal_type": req.meal_type.title(),
            "bua_an": req.meal_type.title(),
            "suggestion_content": f"Thực đơn {req.meal_type} tối ưu dinh dưỡng, tránh làm tăng đường huyết đột ngột và tương tác thuốc.",
            "noi_dung_goi_y": f"Thực đơn {req.meal_type} tối ưu dinh dưỡng, tránh làm tăng đường huyết đột ngột và tương tác thuốc.",
            "based_on_conditions": ["Đái tháo đường type 2", "Tăng huyết áp vô căn"],
            "dua_tren_dieu_kien": ["Đái tháo đường type 2", "Tăng huyết áp vô căn"],
            "recommended_dishes": ["Ức gà áp chảo sốt chanh", "Rau bina luộc", "Khoai lang hấp (nửa củ)"],
            "mon_an_khuyen_nghi": ["Ức gà áp chảo sốt chanh", "Rau bina luộc", "Khoai lang hấp (nửa củ)"],
            "foods_to_avoid": ["Nước ép bưởi chùm (tránh tương tác Amlor)", "Muối tiêu chanh quá mặn"],
            "thuc_pham_tranh": ["Nước ép bưởi chùm (tránh tương tác Amlor)", "Muối tiêu chanh quá mặn"],
            "created_at": current_time_iso(),
            "ngay_tao": current_time_iso()
        }
    }

    return ResponseEnvelope(
        data=MealSuggestionJobResponse(
            job_id=job_id,
            status="queued",
            estimated_seconds=3,
            message="Yêu cầu gợi ý món ăn đã được xếp vào hàng đợi xử lý. Vui lòng poll trạng thái qua job_id."
        ),
        message="Đã tiếp nhận yêu cầu sinh gợi ý món ăn"
    )

@router.get(
    "/patients/{patient_id}/meal-suggestions/jobs/{job_id}",
    response_model=ResponseEnvelope[MealSuggestionJobStatusResponse],
    summary="Kiểm tra tiến độ tiến trình sinh gợi ý món ăn (Poll Endpoint)",
    description="Client gọi định kỳ mỗi 1-2 giây cho đến khi status chuyển sang 'completed' hoặc 'failed'."
)
def get_meal_suggestion_job_status(
    patient_id: str,
    job_id: str,
    actor_role: str = Depends(require_patient_read("goi_y_bua_an"))
):
    job = db.meal_jobs.get(job_id)
    if not job or job["patient_id"] != patient_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": "Không tìm thấy tiến trình xử lý gợi ý món ăn"}
        )

    res_data = None
    if job["status"] == "completed" and job.get("result"):
        r = job["result"]
        res_data = MealSuggestionResponse(
            id=r["id"],
            user_id=r["user_id"],
            meal_type=r.get("meal_type", r.get("bua_an")),
            suggestion_content=r.get("suggestion_content", r.get("noi_dung_goi_y")),
            based_on_conditions=r.get("based_on_conditions", r.get("dua_tren_dieu_kien", [])),
            recommended_dishes=r.get("recommended_dishes", r.get("mon_an_khuyen_nghi", [])),
            foods_to_avoid=r.get("foods_to_avoid", r.get("thuc_pham_tranh", [])),
            created_at=r.get("created_at", r.get("ngay_tao", current_time_iso()))
        )

    return ResponseEnvelope(
        data=MealSuggestionJobStatusResponse(
            job_id=job_id,
            status=job["status"],
            result=res_data,
            error=job.get("error")
        )
    )

@router.get(
    "/patients/{patient_id}/meal-suggestions",
    response_model=ResponseEnvelope[List[MealSuggestionResponse]],
    summary="Lấy lịch sử các bữa ăn đã được gợi ý",
    description="Tra cứu các bữa ăn đã gợi ý trước đó của bệnh nhân."
)
def get_meal_suggestion_history(
    patient_id: str,
    actor_role: str = Depends(require_patient_read("goi_y_bua_an"))
):
    items = [m for m in db.meal_suggestions if m["user_id"] == patient_id]
    formatted = [
        MealSuggestionResponse(
            id=m["id"],
            user_id=m["user_id"],
            meal_type=m.get("meal_type", m.get("bua_an")),
            suggestion_content=m.get("suggestion_content", m.get("noi_dung_goi_y")),
            based_on_conditions=m.get("based_on_conditions", m.get("dua_tren_dieu_kien", [])),
            recommended_dishes=m.get("recommended_dishes", m.get("mon_an_khuyen_nghi", [])),
            foods_to_avoid=m.get("foods_to_avoid", m.get("thuc_pham_tranh", [])),
            created_at=m.get("created_at", m.get("ngay_tao", current_time_iso()))
        )
        for m in items
    ]
    return ResponseEnvelope(data=formatted)
