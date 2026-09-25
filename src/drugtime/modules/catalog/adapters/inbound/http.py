from fastapi import APIRouter

router = APIRouter(tags=["catalog"])

# TODO: GET /medications/search (Mobile, K04);
#       Admin: CRUD danh mục (xóa mềm), POST /admin/catalog/sync -> job_queue.enqueue_sync(),
#       GET /admin/catalog/sync-runs
