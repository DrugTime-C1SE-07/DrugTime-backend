import logging
from typing import Optional
from fastapi import APIRouter, Depends, status, HTTPException
from app.schemas.common import ResponseEnvelope, MessageResponse
from app.schemas.auth import (
    SyncProfileRequest, UpdateProfileRequest, UserResponse, DeviceTokenRequest,
    DataExportResponse, DataExportJobCreate, DataExportJobResponse, DataExportJobStatusResponse,
    RegisterRequest, LoginRequest, AuthResponse
)
from app.core.security import CurrentUser, get_current_user
from app.core.supabase_client import get_supabase_client
from app.mock_db import db, current_time_iso
from app.core.access_control import log_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["1. Auth & User Profile"])


# ──────────────────────────────────────────────────
# Register
# ──────────────────────────────────────────────────

@router.post(
    "/auth/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[AuthResponse],
    summary="Đăng ký tài khoản mới (Bệnh nhân hoặc Người thân)",
    description="Tạo tài khoản Supabase Auth và đồng bộ hồ sơ DrugTime. Hỗ trợ loại tài khoản: benh_nhan, nguoi_than."
)
def register(req: RegisterRequest):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_SERVICE_UNAVAILABLE",
                "message": "Dịch vụ xác thực chưa được cấu hình. Vui lòng liên hệ quản trị viên."
            }
        )

    try:
        auth_response = supabase.auth.sign_up({
            "email": req.email,
            "password": req.password,
            "options": {
                "data": {
                    "ho_ten": req.ho_ten,
                    "loai_tai_khoan": req.loai_tai_khoan,
                }
            }
        })
    except Exception as e:
        error_message = str(e)
        logger.error("Supabase sign_up failed: %s", error_message)

        # Map common Supabase errors safely
        if "already registered" in error_message.lower() or "already been registered" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "EMAIL_ALREADY_REGISTERED",
                    "message": "Email này đã được đăng ký. Vui lòng đăng nhập hoặc sử dụng email khác."
                }
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "REGISTRATION_FAILED",
                "message": "Đăng ký thất bại. Vui lòng thử lại."
            }
        )

    # Extract user and session from Supabase response
    supabase_user = auth_response.user
    session = auth_response.session

    if not supabase_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "REGISTRATION_FAILED",
                "message": "Đăng ký thất bại. Không nhận được thông tin người dùng từ dịch vụ xác thực."
            }
        )

    user_id = supabase_user.id

    # Synchronize with DrugTime application user
    user_data = {
        "id": user_id,
        "ho_ten": req.ho_ten,
        "ngay_sinh": req.ngay_sinh,
        "gioi_tinh": req.gioi_tinh,
        "so_dien_thoai": req.so_dien_thoai,
        "che_do_nguoi_cao_tuoi": False,
        "vai_tro_he_thong": "user",
        "created_at": current_time_iso()
    }
    db.users[user_id] = user_data

    user_response = UserResponse(**user_data)

    auth_data = AuthResponse(
        user=user_response,
        access_token=session.access_token if session else "",
        refresh_token=session.refresh_token if session else None,
        token_type="bearer",
        expires_in=session.expires_in if session else None
    )

    return ResponseEnvelope(
        data=auth_data,
        message="Đăng ký tài khoản thành công"
    )


# ──────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────

@router.post(
    "/auth/login",
    response_model=ResponseEnvelope[AuthResponse],
    summary="Đăng nhập bằng email và mật khẩu",
    description="Xác thực người dùng qua Supabase Auth và trả về JWT token."
)
def login(req: LoginRequest):
    supabase = get_supabase_client()
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_SERVICE_UNAVAILABLE",
                "message": "Dịch vụ xác thực chưa được cấu hình. Vui lòng liên hệ quản trị viên."
            }
        )

    try:
        auth_response = supabase.auth.sign_in_with_password({
            "email": req.email,
            "password": req.password,
        })
    except Exception as e:
        error_message = str(e)
        logger.error("Supabase sign_in failed: %s", error_message)

        if "invalid" in error_message.lower() or "credentials" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Email hoặc mật khẩu không đúng."
                }
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "LOGIN_FAILED",
                "message": "Đăng nhập thất bại. Vui lòng thử lại."
            }
        )

    supabase_user = auth_response.user
    session = auth_response.session

    if not supabase_user or not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Email hoặc mật khẩu không đúng."
            }
        )

    user_id = supabase_user.id

    # Synchronize with DrugTime user (create if not exists)
    user = db.users.get(user_id)
    if not user:
        user_meta = supabase_user.user_metadata or {}
        user = {
            "id": user_id,
            "ho_ten": user_meta.get("ho_ten", supabase_user.email or ""),
            "ngay_sinh": user_meta.get("ngay_sinh"),
            "gioi_tinh": user_meta.get("gioi_tinh"),
            "so_dien_thoai": user_meta.get("so_dien_thoai"),
            "che_do_nguoi_cao_tuoi": False,
            "vai_tro_he_thong": "user",
            "created_at": current_time_iso()
        }
        db.users[user_id] = user

    user_response = UserResponse(**user)

    auth_data = AuthResponse(
        user=user_response,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        token_type="bearer",
        expires_in=session.expires_in
    )

    return ResponseEnvelope(
        data=auth_data,
        message="Đăng nhập thành công"
    )


# ──────────────────────────────────────────────────
# Sync Profile (existing)
# ──────────────────────────────────────────────────

@router.post(
    "/auth/sync-profile",
    response_model=ResponseEnvelope[UserResponse],
    summary="Đồng bộ hồ sơ người dùng từ Supabase Auth",
    description="Gọi lần đầu sau khi đăng nhập hoặc đăng ký thành công trên Supabase Auth để tạo/cập nhật bảng users."
)
def sync_profile(req: SyncProfileRequest, caller: CurrentUser = Depends(get_current_user)):
    user = db.users.get(caller.user_id)
    if not user:
        user = {
            "id": caller.user_id,
            "ho_ten": req.ho_ten,
            "ngay_sinh": req.ngay_sinh,
            "gioi_tinh": req.gioi_tinh,
            "so_dien_thoai": req.so_dien_thoai,
            "che_do_nguoi_cao_tuoi": False,
            "vai_tro_he_thong": "user",
            "created_at": current_time_iso()
        }
        db.users[caller.user_id] = user
    else:
        user["ho_ten"] = req.ho_ten
        if req.so_dien_thoai:
            user["so_dien_thoai"] = req.so_dien_thoai
        if req.ngay_sinh:
            user["ngay_sinh"] = req.ngay_sinh
        if req.gioi_tinh:
            user["gioi_tinh"] = req.gioi_tinh

    return ResponseEnvelope(data=UserResponse(**user), message="Đồng bộ hồ sơ người dùng thành công")


# ──────────────────────────────────────────────────
# User Profile
# ──────────────────────────────────────────────────

@router.get(
    "/users/me",
    response_model=ResponseEnvelope[UserResponse],
    summary="Lấy thông tin tài khoản và cài đặt giao diện hiện tại",
    description="Trả về thông tin người dùng đang đăng nhập cùng cài đặt Simple Mode (che_do_nguoi_cao_tuoi)."
)
def get_my_profile(caller: CurrentUser = Depends(get_current_user)):
    user = db.users.get(caller.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "Không tìm thấy hồ sơ người dùng"})
    return ResponseEnvelope(data=UserResponse(**user))

@router.patch(
    "/users/me",
    response_model=ResponseEnvelope[UserResponse],
    summary="Cập nhật hồ sơ & bật/tắt Simple Mode",
    description="Cho phép chỉnh sửa họ tên, số điện thoại, hoặc bật/tắt chế độ Simple Mode cho người cao tuổi."
)
def update_my_profile(req: UpdateProfileRequest, caller: CurrentUser = Depends(get_current_user)):
    user = db.users.get(caller.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "Không tìm thấy hồ sơ người dùng"})
    
    if req.ho_ten is not None:
        user["ho_ten"] = req.ho_ten
    if req.so_dien_thoai is not None:
        user["so_dien_thoai"] = req.so_dien_thoai
    if req.che_do_nguoi_cao_tuoi is not None:
        user["che_do_nguoi_cao_tuoi"] = req.che_do_nguoi_cao_tuoi

    return ResponseEnvelope(data=UserResponse(**user), message="Cập nhật hồ sơ thành công")


# ──────────────────────────────────────────────────
# Data Export
# ──────────────────────────────────────────────────

@router.post(
    "/users/me/data-export",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ResponseEnvelope[DataExportJobResponse],
    summary="Khởi tạo job xuất bản sao dữ liệu cá nhân bất đồng bộ (NĐ 356)",
    description="Khởi tạo tiến trình xuất toàn bộ hồ sơ y tế và lịch sử tuân thủ sang file ZIP/JSON bảo mật."
)
def create_data_export_job(
    req: Optional[DataExportJobCreate] = None,
    caller: CurrentUser = Depends(get_current_user)
):
    import uuid
    from datetime import datetime, timezone, timedelta
    job_id = f"export-{uuid.uuid4().hex[:8]}"
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    
    db.data_export_jobs[job_id] = {
        "job_id": job_id,
        "user_id": caller.user_id,
        "status": "completed",
        "download_url": f"https://api.drugtime.vn/api/v1/downloads/exports/{job_id}.zip",
        "expires_at": expires_at,
        "file_size_bytes": 1024 * 145,
        "created_at": current_time_iso()
    }
    log_access(caller.user_id, "self", caller.user_id, "ho_so_suc_khoe", "allowed")
    return ResponseEnvelope(
        data=DataExportJobResponse(job_id=job_id, status="pending"),
        message="Yêu cầu trích xuất dữ liệu cá nhân đã được tiếp nhận và xử lý bất đồng bộ."
    )

@router.get(
    "/users/me/data-export/jobs/{job_id}",
    response_model=ResponseEnvelope[DataExportJobStatusResponse],
    summary="Poll tiến độ & lấy link tải file bản sao dữ liệu cá nhân",
    description="Kiểm tra trạng thái tiến trình xuất dữ liệu và nhận URL tải file (hạn 24 giờ)."
)
def get_data_export_job_status(
    job_id: str,
    caller: CurrentUser = Depends(get_current_user)
):
    job = db.data_export_jobs.get(job_id)
    if not job or job["user_id"] != caller.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "JOB_NOT_FOUND", "message": "Không tìm thấy tiến trình xuất dữ liệu"})
    
    log_access(caller.user_id, "self", caller.user_id, "ho_so_suc_khoe", "allowed")
    return ResponseEnvelope(
        data=DataExportJobStatusResponse(
            job_id=job["job_id"],
            status=job["status"],
            download_url=job.get("download_url"),
            expires_at=job.get("expires_at"),
            file_size_bytes=job.get("file_size_bytes")
        )
    )

@router.get(
    "/users/me/data-export",
    response_model=ResponseEnvelope[DataExportResponse],
    summary="Xuất toàn bộ bản sao dữ liệu cá nhân đồng bộ (NĐ 356)",
    description="Xuất toàn bộ hồ sơ, đơn thuốc, tuân thủ dưới dạng JSON trực tiếp."
)
def export_my_data(caller: CurrentUser = Depends(get_current_user)):
    user = db.users.get(caller.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "Không tìm thấy người dùng"})
    
    log_access(caller.user_id, "self", caller.user_id, "ho_so_suc_khoe", "allowed")
    
    # Filter related records
    conditions = [c for c in db.user_conditions if c["user_id"] == caller.user_id]
    prescriptions = [p for p in db.prescriptions if p["user_id"] == caller.user_id]
    consents = [c for c in db.user_consents if c["user_id"] == caller.user_id]

    data = DataExportResponse(
        user_id=caller.user_id,
        exported_at=current_time_iso(),
        profile=user,
        conditions=conditions,
        prescriptions=prescriptions,
        dose_logs=db.dose_logs,
        consents=consents
    )
    return ResponseEnvelope(data=data, message="Trích xuất bản sao dữ liệu cá nhân thành công")


# ──────────────────────────────────────────────────
# Device Tokens
# ──────────────────────────────────────────────────

@router.post(
    "/users/me/device-tokens",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[MessageResponse],
    summary="Đăng ký FCM Device Token nhận cảnh báo liều",
    description="Lưu FCM token của thiết bị để nhận push notification nhắc nhở hoặc cảnh báo người thân bỏ lỡ liều."
)
def register_device_token(req: DeviceTokenRequest, caller: CurrentUser = Depends(get_current_user)):
    existing = next((t for t in db.device_tokens if t["fcm_token"] == req.fcm_token), None)
    if existing:
        existing["user_id"] = caller.user_id
        existing["platform"] = req.platform
        existing["cap_nhat_luc"] = current_time_iso()
    else:
        db.device_tokens.append({
            "id": len(db.device_tokens) + 1,
            "user_id": caller.user_id,
            "fcm_token": req.fcm_token,
            "platform": req.platform,
            "cap_nhat_luc": current_time_iso()
        })
    return ResponseEnvelope(data=MessageResponse(message="Đăng ký thiết bị nhận thông báo thành công"))

@router.delete(
    "/users/me/device-tokens/{fcm_token}",
    response_model=ResponseEnvelope[MessageResponse],
    summary="Hủy đăng ký FCM token khi đăng xuất",
    description="Xóa token khỏi danh sách gửi cảnh báo khi người dùng đăng xuất."
)
def unregister_device_token(fcm_token: str, caller: CurrentUser = Depends(get_current_user)):
    db.device_tokens[:] = [t for t in db.device_tokens if not (t["user_id"] == caller.user_id and t["fcm_token"] == fcm_token)]
    return ResponseEnvelope(data=MessageResponse(message="Hủy đăng ký thiết bị thành công"))
