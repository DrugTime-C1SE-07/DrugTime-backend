#!/usr/bin/env bash
# Start command của Render Background Worker (CD10).
# Chạy hai tiến trình: rqscheduler (chuyển job đến hạn vào hàng đợi) và RQ worker
# (kèm vòng lặp ensure_schedules + heartbeat). Thoát ngay khi một tiến trình dừng
# để Render khởi động lại cả service.
set -euo pipefail

rqscheduler --url "${REDIS_URL}" --interval 60 &
python -m drugtime.worker &

wait -n
exit 1
