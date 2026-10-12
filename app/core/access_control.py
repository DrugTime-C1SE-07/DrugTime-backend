"""Contextual Role-Based Access Control (RBAC) & Audit Logging Dependency (Schema v9: CD1, CD2, QA.09)."""
from typing import Literal, Optional
from fastapi import HTTPException, status, Depends, Header
from app.core.security import CurrentUser, get_current_user
from app.mock_db import db, current_time_iso

PermissionType = Literal["read", "write"]
DataScope = Literal["ho_so_suc_khoe", "danh_sach_thuoc", "lich_su_tuan_thu", "canh_bao_tuong_tac", "goi_y_bua_an", "admin"]

def log_access(
    actor_user_id: str,
    actor_role: Literal["family", "admin", "khong_co_quyen"],
    patient_user_id: str,
    data_scope: str,
    result: Literal["allowed", "denied"],
    rejection_reason: Optional[str] = None,
    override_reason: Optional[str] = None,
    action: Optional[str] = None,
    is_emergency_override: bool = False,
    review_status: Optional[str] = None,
    review_deadline: Optional[str] = None
):
    """
    Appends an immutable audit log entry according to Schema v9 & QA.09.
    Rules:
    - Actor role must be one of: family, admin, khong_co_quyen (never 'self').
    - If result is 'allowed', actor_role IN ('family', 'admin').
    """
    log_entry = {
        "id": len(db.access_logs) + 1,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "patient_user_id": patient_user_id,
        "data_scope": data_scope,
        "result": result,
        "rejection_reason": rejection_reason,
        "override_reason": override_reason,
        "action": action,
        "is_emergency_override": is_emergency_override,
        "review_status": review_status,
        "review_deadline": review_deadline,
        "accessed_at": current_time_iso(),
        # Compatibility aliases for tests if needed
        "ket_qua": result,
        "ly_do_tu_choi": rejection_reason,
        "ly_do_can_thiep": override_reason,
        "thoi_gian": current_time_iso()
    }
    db.access_logs.append(log_entry)

def check_patient_consent(patient_id: str, purpose: str) -> bool:
    """Checks if the patient has active consent for the given purpose."""
    for consent in reversed(db.user_consents):
        consent_type = consent.get("consent_type", consent.get("loai_dong_y"))
        consent_status = consent.get("status", consent.get("trang_thai"))
        if consent["user_id"] == patient_id and consent_type == purpose:
            return consent_status == "dong_y"
    return True

def verify_access(
    caller: CurrentUser,
    patient_id: str,
    required_permission: PermissionType = "read",
    data_scope: DataScope = "ho_so_suc_khoe",
    admin_reason: Optional[str] = None
) -> str:
    """
    Verifies caller access to patient data, resolves contextual role, and records audit log.
    Strictly follows Schema v9 RBAC logic:
      1. C.erased_at IS NOT NULL -> 401, stop immediately
      2. C == P -> self access: check consent; DO NOT log to access_logs
      3. C.system_role == 'admin' -> actor_role = admin (log allowed)
      4. active caregiver link with sharing_enabled & valid family_sharing consent -> actor_role = family (log allowed)
      5. otherwise -> 403 + log access: result = denied, actor_role = khong_co_quyen
    """
    # 1. Tombstone check
    if getattr(caller, "erased_at", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "ACCOUNT_ERASED", "message": "Tài khoản đã bị xóa dữ liệu theo yêu cầu cá nhân (tombstone)."}
        )

    # 2. Self Access (Patient accessing their own data)
    if caller.user_id == patient_id:
        actor_role = "self"
        if not check_patient_consent(patient_id, "health_data"):
            reason = "Bệnh nhân đã rút quyền xử lý dữ liệu sức khỏe cá nhân (health_data)"
            # Note: In Schema v9, self access (allowed or denied) is NOT logged to access_logs
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "CONSENT_HEALTH_DATA_REVOKED", "message": reason}
            )
        # Self access is NOT logged to access_logs in Schema v9 (reduces table bloat, QA.04/QA.09)
        return actor_role

    # 3. Admin Role
    if caller.system_role == "admin":
        actor_role = "admin"
        from urllib.parse import unquote
        decoded_reason = unquote(admin_reason) if admin_reason else None
        if required_permission == "write":
            if not decoded_reason or len(decoded_reason.strip()) < 10:
                err_msg = "Thao tác can thiệp của Quản trị viên bắt buộc phải cung cấp lý do qua header 'X-Admin-Reason' (tối thiểu 10 ký tự)."
                log_access(caller.user_id, actor_role, patient_id, data_scope, "denied", rejection_reason=err_msg)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "ADMIN_OVERRIDE_REASON_REQUIRED", "message": err_msg}
                )
        log_access(caller.user_id, actor_role, patient_id, data_scope, "allowed", override_reason=decoded_reason)
        return actor_role

    # 4. Family Access (Caregiver accessing patient data)
    # Check active caregiver link
    link = next((
        l for l in db.caregiver_links
        if l["patient_user_id"] == patient_id and l["family_user_id"] == caller.user_id and l.get("status", l.get("trang_thai")) == "active"
    ), None)

    if not link:
        reason = "Không tìm thấy liên kết người thân hợp lệ giữa bạn và bệnh nhân"
        log_access(caller.user_id, "khong_co_quyen", patient_id, data_scope, "denied", rejection_reason=reason)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "NO_ACTIVE_CAREGIVER_LINK", "message": reason}
        )

    # Check sharing switch
    is_sharing = link.get("sharing_enabled", link.get("cho_phep_chia_se", False))
    if not is_sharing:
        reason = "Bệnh nhân đã tắt công tắc chia sẻ dữ liệu cho tài khoản người thân của bạn"
        log_access(caller.user_id, "khong_co_quyen", patient_id, data_scope, "denied", rejection_reason=reason)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PATIENT_DISABLED_SHARING", "message": reason}
        )

    # Check patient's family_sharing consent
    if not check_patient_consent(patient_id, "family_sharing"):
        reason = "Bệnh nhân đã thu hồi đồng thuận chia sẻ dữ liệu gia đình (family_sharing)"
        log_access(caller.user_id, "khong_co_quyen", patient_id, data_scope, "denied", rejection_reason=reason)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CONSENT_FAMILY_SHARING_REVOKED", "message": reason}
        )

    # Check write permission if required
    if required_permission == "write":
        # Check if write is allowed (supports cho_phep_chinh_sua flag for backward test compatibility)
        if not link.get("cho_phep_chinh_sua", False):
            reason = "Người thân chỉ có quyền XEM dữ liệu, chưa được bệnh nhân cấp quyền GHI/chỉnh sửa"
            log_access(caller.user_id, "khong_co_quyen", patient_id, data_scope, "denied", rejection_reason=reason)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "INSUFFICIENT_WRITE_PERMISSION", "message": reason}
            )

    actor_role = "family"
    log_access(caller.user_id, actor_role, patient_id, data_scope, "allowed")
    return actor_role

def require_patient_read(data_scope: DataScope = "ho_so_suc_khoe"):
    def dependency(
        patient_id: str,
        caller: CurrentUser = Depends(get_current_user),
        x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
    ) -> str:
        return verify_access(caller, patient_id, required_permission="read", data_scope=data_scope, admin_reason=x_admin_reason)
    return dependency

def require_patient_write(data_scope: DataScope = "ho_so_suc_khoe"):
    def dependency(
        patient_id: str,
        caller: CurrentUser = Depends(get_current_user),
        x_admin_reason: Optional[str] = Header(None, alias="X-Admin-Reason")
    ) -> str:
        return verify_access(caller, patient_id, required_permission="write", data_scope=data_scope, admin_reason=x_admin_reason)
    return dependency
