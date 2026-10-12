"""Disease Groups Router (Schema v9: QA.10, CD8 Lookup Table)."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, HTTPException
from app.schemas.common import ResponseEnvelope, PaginatedData, PaginationMeta
from app.schemas.disease_groups import (
    DiseaseGroupResponse, DiseaseGroupCreate, DiseaseGroupUpdate
)
from app.core.security import CurrentUser, get_current_user, require_admin_user
from app.mock_db import db

router = APIRouter(prefix="", tags=["Nhóm bệnh (Disease Groups)"])

@router.get(
    "/disease-groups",
    response_model=ResponseEnvelope[List[DiseaseGroupResponse]],
    summary="Tra cứu danh mục nhóm bệnh (Bảng lookup Schema v9)",
    description="Trả về các nhóm bệnh đang hoạt động (is_active=True) phục vụ hiển thị và cấu hình."
)
def list_active_disease_groups(
    q: Optional[str] = Query(None, description="Từ khóa tìm kiếm"),
    caller: CurrentUser = Depends(get_current_user)
):
    items = [dg for dg in db.disease_groups if dg.get("is_active", True)]
    if q:
        items = [dg for dg in items if q.lower() in dg["name"].lower() or q.lower() in dg["code"].lower()]
    return ResponseEnvelope(data=[DiseaseGroupResponse(**dg) for dg in items])

@router.get(
    "/admin/disease-groups",
    response_model=ResponseEnvelope[PaginatedData[DiseaseGroupResponse]],
    summary="Quản trị danh mục nhóm bệnh (Admin, Phân trang)",
    description="Tra cứu toàn bộ nhóm bệnh kể cả các nhóm đã vô hiệu hóa (is_active=False)."
)
def admin_list_disease_groups(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user)
):
    items = db.disease_groups
    total = len(items)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    paged = [DiseaseGroupResponse(**dg) for dg in items[start:start+page_size]]
    return ResponseEnvelope(
        data=PaginatedData(items=paged, pagination=PaginationMeta(page=page, page_size=page_size, total_items=total, total_pages=pages))
    )

@router.post(
    "/admin/disease-groups",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseEnvelope[DiseaseGroupResponse],
    summary="Thêm mới nhóm bệnh vào danh mục (Admin)",
    description="Tạo một nhóm bệnh mới trong bảng lookup disease_groups (QA.10)."
)
def admin_create_disease_group(
    req: DiseaseGroupCreate,
    admin: CurrentUser = Depends(require_admin_user)
):
    # Check duplicate code
    if any(dg["code"] == req.code for dg in db.disease_groups):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DUPLICATE_DISEASE_GROUP_CODE", "message": f"Mã nhóm bệnh '{req.code}' đã tồn tại"}
        )
    new_id = max([dg["id"] for dg in db.disease_groups], default=0) + 1
    new_dg = {
        "id": new_id,
        "code": req.code,
        "name": req.name,
        "is_active": req.is_active
    }
    db.disease_groups.append(new_dg)
    return ResponseEnvelope(data=DiseaseGroupResponse(**new_dg), message="Thêm nhóm bệnh thành công")

@router.patch(
    "/admin/disease-groups/{id}",
    response_model=ResponseEnvelope[DiseaseGroupResponse],
    summary="Cập nhật thông tin nhóm bệnh (Admin)",
    description="Chỉnh sửa tên, mã, hoặc bật/tắt trạng thái hoạt động (thay vì xóa cứng khi còn tham chiếu)."
)
def admin_update_disease_group(
    id: int,
    req: DiseaseGroupUpdate,
    admin: CurrentUser = Depends(require_admin_user)
):
    dg = next((d for d in db.disease_groups if d["id"] == id), None)
    if not dg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "DISEASE_GROUP_NOT_FOUND", "message": "Không tìm thấy nhóm bệnh"})
    if req.code is not None:
        dg["code"] = req.code
    if req.name is not None:
        dg["name"] = req.name
    if req.is_active is not None:
        dg["is_active"] = req.is_active
    return ResponseEnvelope(data=DiseaseGroupResponse(**dg), message="Cập nhật nhóm bệnh thành công")
