"""Router 5: Schedules & Idempotent Dose Logging (Schema v9: English naming, effective_from)."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Header, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse, PaginatedData, PaginationMeta
from app.schemas.schedules import (
    ScheduleCreate, ScheduleUpdate, ScheduleResponse,
    BatchDoseLogSyncRequest, BatchDoseLogSyncResponse, BatchDoseLogSyncSummary,
    DoseSyncResultItem, DoseLogResponse, AdherenceSummaryResponse
)
from app.core.security import CurrentUser, get_current_user
from app.core.access_control import require_patient_read, require_patient_write, verify_access
from app.mock_db import db, current_time_iso

router = APIRouter(prefix="", tags=["5. Schedules & Dose Logs"])

@router.get(
    "/patients/{patient_id}/schedules",
    response_model=ResponseEnvelope[List[ScheduleResponse]],
    summary="Lấy danh sách lịch uống thuốc của bệnh nhân",
    description="Mobile dùng danh sách này để tạo Local Notifications trên thiết bị (Schema v9: effective_from)."
)
def get_patient_schedules(
    patient_id: str,
    actor_role: str = Depends(require_patient_read("lich_su_tuan_thu"))
):
    user_med_ids = {
        m["id"] for m in db.user_medications
        if m["user_id"] == patient_id and m.get("status", m.get("trang_thai", "active")) == "active"
    }
    schedules = [
        s for s in db.medication_schedules
        if s["user_medication_id"] in user_med_ids and s.get("status", s.get("trang_thai", "active")) == "active"
    ]
    formatted = [
        ScheduleResponse(
            id=s["id"],
            user_medication_id=s["user_medication_id"],
            medication_name=s.get("medication_name", s.get("ten_thuoc")),
            schedule_type=s.get("schedule_type", s.get("loai_lich", "co_dinh")),
            intake_time=s.get("intake_time", s.get("gio_uong")),
            days_of_week=s.get("days_of_week", s.get("ngay_trong_tuan")),
            reminder_enabled=s.get("reminder_enabled", s.get("bat_tat_nhac", True)),
            effective_from=s.get("effective_from", current_time_iso()),
            status=s.get("status", s.get("trang_thai", "active"))
        )
        for s in schedules
    ]
    return ResponseEnvelope(data=formatted)

@router.post(
    "/user-medications/{id}/schedules",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[ScheduleResponse],
    summary="Tạo lịch giờ uống thuốc (CD6: effective_from = now())",
    description="Hỗ trợ lịch giờ uống. Gán effective_from = now() để Worker không quét nhầm thành bỏ lỡ."
)
def create_medication_schedule(
    id: int,
    req: ScheduleCreate,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    med = next((m for m in db.user_medications if m["id"] == id), None)
    if not med or med.get("status", med.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_MEDICATION_NOT_FOUND", "message": "Không tìm thấy thuốc"})
    
    verify_access(caller, med["user_id"], required_permission="write", data_scope="lich_su_tuan_thu", admin_reason=x_admin_reason)

    now_iso = current_time_iso()
    med_name = med.get("name", med.get("ten_thuoc"))
    new_sched = {
        "id": len(db.medication_schedules) + 1,
        "user_medication_id": id,
        "medication_name": med_name,
        "ten_thuoc": med_name,
        "schedule_type": req.schedule_type,
        "loai_lich": req.schedule_type,
        "intake_time": req.intake_time if req.schedule_type == "co_dinh" else None,
        "gio_uong": req.intake_time if req.schedule_type == "co_dinh" else None,
        "days_of_week": req.days_of_week,
        "ngay_trong_tuan": req.days_of_week,
        "reminder_enabled": req.reminder_enabled,
        "bat_tat_nhac": req.reminder_enabled,
        "effective_from": now_iso,
        "status": "active",
        "trang_thai": "active"
    }
    db.medication_schedules.append(new_sched)
    return ResponseEnvelope(
        data=ScheduleResponse(
            id=new_sched["id"],
            user_medication_id=new_sched["user_medication_id"],
            medication_name=new_sched["medication_name"],
            schedule_type=new_sched["schedule_type"],
            intake_time=new_sched["intake_time"],
            days_of_week=new_sched["days_of_week"],
            reminder_enabled=new_sched["reminder_enabled"],
            effective_from=new_sched["effective_from"],
            status=new_sched["status"]
        ),
        message="Đã tạo lịch uống thuốc thành công"
    )

@router.patch(
    "/schedules/{id}",
    response_model=ResponseEnvelope[ScheduleResponse],
    summary="Cập nhật giờ uống hoặc bật/tắt nhắc nhở (CD6: reset effective_from = now())",
    description="Sửa giờ uống hoặc bật/tắt nhắc nhở. Tự động cập nhật effective_from = now()."
)
def update_schedule(
    id: int,
    req: ScheduleUpdate,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    sched = next((s for s in db.medication_schedules if s["id"] == id), None)
    if not sched or sched.get("status", sched.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "SCHEDULE_NOT_FOUND", "message": "Không tìm thấy lịch uống"})
    
    med = next((m for m in db.user_medications if m["id"] == sched["user_medication_id"]), None)
    patient_id = med["user_id"] if med else caller.user_id
    verify_access(caller, patient_id, required_permission="write", data_scope="lich_su_tuan_thu", admin_reason=x_admin_reason)

    if req.intake_time is not None:
        sched["intake_time"] = req.intake_time
        sched["gio_uong"] = req.intake_time
        # Reset effective_from when schedule time changes so Worker doesn't scan past doses as missed
        sched["effective_from"] = current_time_iso()
    if req.days_of_week is not None:
        sched["days_of_week"] = req.days_of_week
        sched["ngay_trong_tuan"] = req.days_of_week
        sched["effective_from"] = current_time_iso()
    if req.reminder_enabled is not None:
        sched["reminder_enabled"] = req.reminder_enabled
        sched["bat_tat_nhac"] = req.reminder_enabled

    return ResponseEnvelope(
        data=ScheduleResponse(
            id=sched["id"],
            user_medication_id=sched["user_medication_id"],
            medication_name=sched.get("medication_name", sched.get("ten_thuoc")),
            schedule_type=sched.get("schedule_type", sched.get("loai_lich", "co_dinh")),
            intake_time=sched.get("intake_time", sched.get("gio_uong")),
            days_of_week=sched.get("days_of_week", sched.get("ngay_trong_tuan")),
            reminder_enabled=sched.get("reminder_enabled", sched.get("bat_tat_nhac", True)),
            effective_from=sched.get("effective_from", current_time_iso()),
            status=sched.get("status", sched.get("trang_thai", "active"))
        ),
        message="Cập nhật lịch uống thành công"
    )

@router.delete(
    "/schedules/{id}",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Xóa (soft-delete) lịch uống thuốc",
    description="Chuyển trạng thái lịch sang 'archived' khi giảm số lần uống trong ngày."
)
def delete_schedule(
    id: int,
    caller: CurrentUser = Depends(get_current_user),
    x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
):
    sched = next((s for s in db.medication_schedules if s["id"] == id), None)
    if not sched or sched.get("status", sched.get("trang_thai")) == "archived":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "SCHEDULE_NOT_FOUND", "message": "Không tìm thấy lịch uống"})
    
    med = next((m for m in db.user_medications if m["id"] == sched["user_medication_id"]), None)
    patient_id = med["user_id"] if med else caller.user_id
    verify_access(caller, patient_id, required_permission="write", data_scope="lich_su_tuan_thu", admin_reason=x_admin_reason)

    sched["status"] = "archived"
    sched["trang_thai"] = "archived"
    return ResponseEnvelope(data=MessageResponse(message="Đã lưu trữ và hủy lịch uống thành công"))

@router.post(
    "/dose-logs/batch-sync",
    response_model=ResponseEnvelope[BatchDoseLogSyncResponse],
    summary="Đồng bộ liều uống từ client offline (Idempotent per client_uuid)",
    description="Chống trùng lặp tuyệt đối bằng client_uuid (QA.08, CD3). Trả về chi tiết trạng thái từng item (synced, duplicate, error)."
)
def batch_sync_dose_logs(
    req: BatchDoseLogSyncRequest,
    caller: CurrentUser = Depends(get_current_user)
):
    now = current_time_iso()
    
    synced_count = 0
    duplicate_count = 0
    error_count = 0
    results: List[DoseSyncResultItem] = []

    for item in req.logs:
        # Check duplicate client_uuid (if provided)
        if item.client_uuid:
            existing = next((log for log in db.dose_logs if log.get("client_uuid") == item.client_uuid), None)
            if existing:
                duplicate_count += 1
                results.append(DoseSyncResultItem(client_uuid=item.client_uuid, status="duplicate", message="Bản ghi đã tồn tại"))
                continue

        # Check schedule exists
        sched = next((s for s in db.medication_schedules if s["id"] == item.medication_schedule_id), None)
        if not sched:
            error_count += 1
            results.append(DoseSyncResultItem(
                client_uuid=item.client_uuid,
                status="error",
                error_code="SCHEDULE_NOT_FOUND",
                message=f"Không tìm thấy lịch uống #{item.medication_schedule_id}"
            ))
            continue

        # Valid item
        sched_name = sched.get("medication_name", sched.get("ten_thuoc", "Thuốc"))
        new_log = {
            "id": len(db.dose_logs) + 1,
            "medication_schedule_id": item.medication_schedule_id,
            "medication_name": sched_name,
            "ten_thuoc": sched_name,
            "scheduled_at": item.scheduled_at,
            "thoi_gian_du_kien": item.scheduled_at,
            "taken_at": item.taken_at,
            "thoi_gian_thuc_uong": item.taken_at,
            "status": item.status,
            "trang_thai": item.status,
            "client_uuid": item.client_uuid,
            "synced_at": now,
            "dong_bo_luc": now
        }
        db.dose_logs.append(new_log)
        synced_count += 1
        results.append(DoseSyncResultItem(client_uuid=item.client_uuid, status="synced"))

    summary = BatchDoseLogSyncSummary(synced=synced_count, duplicate=duplicate_count, error=error_count)
    return ResponseEnvelope(
        data=BatchDoseLogSyncResponse(summary=summary, results=results),
        message=f"Đã đồng bộ {synced_count} liều mới, {duplicate_count} trùng lặp, {error_count} lỗi."
    )

@router.get(
    "/patients/{patient_id}/dose-logs",
    response_model=ResponseEnvelope[PaginatedData[DoseLogResponse]],
    summary="Xem lịch sử uống thuốc của bệnh nhân (Phân trang)",
    description="Tra cứu lịch sử tuân thủ uống thuốc kèm trạng thái Đã uống / Bỏ lỡ / Uống trễ."
)
def get_patient_dose_logs(
    patient_id: str,
    from_date: Optional[str] = Query(None, description="Từ ngày YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="Đến ngày YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    actor_role: str = Depends(require_patient_read("lich_su_tuan_thu"))
):
    items = db.dose_logs
    if from_date:
        items = [log for log in items if log.get("scheduled_at", log.get("thoi_gian_du_kien", "")) >= from_date]
    if to_date:
        items = [log for log in items if log.get("scheduled_at", log.get("thoi_gian_du_kien", "")) <= to_date]

    total_items = len(items)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    paged_items = [
        DoseLogResponse(
            id=log["id"],
            medication_schedule_id=log["medication_schedule_id"],
            medication_name=log.get("medication_name", log.get("ten_thuoc")),
            scheduled_at=log.get("scheduled_at", log.get("thoi_gian_du_kien")),
            taken_at=log.get("taken_at", log.get("thoi_gian_thuc_uong")),
            status=log.get("status", log.get("trang_thai")),
            client_uuid=log.get("client_uuid"),
            synced_at=log.get("synced_at", log.get("dong_bo_luc"))
        )
        for log in items[start:end]
    ]

    return ResponseEnvelope(
        data=PaginatedData(
            items=paged_items,
            pagination=PaginationMeta(page=page, page_size=page_size, total_items=total_items, total_pages=total_pages)
        )
    )

@router.get(
    "/patients/{patient_id}/adherence-summary",
    response_model=ResponseEnvelope[AdherenceSummaryResponse],
    summary="Thống kê tỷ lệ tuân thủ điều trị (7 ngày / 30 ngày)",
    description="Tính toán tỷ lệ % uống đúng giờ, uống trễ, bỏ lỡ để hiển thị biểu đồ tuân thủ."
)
def get_adherence_summary(
    patient_id: str,
    period: str = Query("7d", pattern="^(7d|30d)$", description="Khoảng thời gian: 7d hoặc 30d"),
    actor_role: str = Depends(require_patient_read("lich_su_tuan_thu"))
):
    total = len(db.dose_logs)
    taken_on_time = len([l for l in db.dose_logs if l.get("status", l.get("trang_thai")) == "Đã uống"])
    taken_late = len([l for l in db.dose_logs if l.get("status", l.get("trang_thai")) == "Uống trễ"])
    missed = len([l for l in db.dose_logs if l.get("status", l.get("trang_thai")) == "Bỏ lỡ"])
    
    adherence_rate = (taken_on_time / total * 100.0) if total > 0 else 100.0
    
    data = AdherenceSummaryResponse(
        patient_id=patient_id,
        period=period, # type: ignore
        adherence_rate=round(adherence_rate, 1),
        taken_on_time=taken_on_time,
        taken_late=taken_late,
        missed=missed,
        total_scheduled=total
    )
    return ResponseEnvelope(data=data)
