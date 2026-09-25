"""Composition root của Background Job Worker: `python -m drugtime.worker`.

Chạy cùng rqscheduler (xem scripts/start_worker.sh).
"""

import logging
import os
import socket
import threading

from redis import Redis
from rq import Queue, Worker

from drugtime.runtime import scheduler
from drugtime.shared.config import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    redis = Redis.from_url(get_settings().redis_url)
    instance_id = f"{socket.gethostname()}-{os.getpid()}"

    stop = threading.Event()
    threading.Thread(
        target=scheduler.run_loop,
        args=(redis, instance_id, stop),
        daemon=True,
        name="ensure-and-heartbeat",
    ).start()
    try:
        Worker([Queue("default", connection=redis)], connection=redis).work()
    finally:
        stop.set()


if __name__ == "__main__":
    main()
