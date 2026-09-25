Integration test chạy với Postgres và Redis thật:

```bash
supabase start          # chạy từ thư mục backend/
supabase db reset       # áp toàn bộ migration + seed
pytest tests/integration
```
Ưu tiên: UPSERT dose_logs (Worker và API chạy đua), access_logs fail-closed, xóa dữ liệu
chạy lại hai lần cho cùng kết quả, quyền của api_role/worker_role.
