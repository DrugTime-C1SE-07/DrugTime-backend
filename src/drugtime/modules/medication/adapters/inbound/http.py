from fastapi import APIRouter

router = APIRouter(prefix="/medications", tags=["medication"])

# TODO: CRUD thuốc/lịch của patient (authorize qua access.api, validate qua catalog.api);
#       GET /patients/{id}/schedules cho Mobile kéo lịch về (DM2).
#       Tạo lịch hoặc sửa intake_time/days_of_week phải đặt effective_from = now().
