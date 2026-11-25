"""Cache raw output LLM gợi ý bữa ăn trên Redis/Upstash (CD10, task 5.09 AC3, AC8, AC13).

Fail-open: mọi `RedisError` (không kết nối được, timeout, Upstash từ chối lệnh khi hết quota) chỉ
được log mã lỗi rồi bỏ qua, để người gọi gọi thẳng LLM. Không retry và timeout ngắn để không vượt
ngân sách 10 giây của PB37. Log không chứa key, URL (có token) hay nội dung.
"""

import logging

from redis import Redis, RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry

_log = logging.getLogger(__name__)


def build_client(url: str, timeout_seconds: float) -> Redis:
    return Redis.from_url(
        url,
        socket_timeout=timeout_seconds,
        socket_connect_timeout=timeout_seconds,
        retry=Retry(NoBackoff(), 0),
        decode_responses=True,
    )


class RedisMealCache:
    def __init__(self, client: Redis, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("meal cache TTL must be positive")  # CD10: mọi key phải có TTL
        self._client = client
        self._ttl = ttl_seconds

    def get(self, key: str) -> str | None:
        try:
            return self._client.get(key)
        except RedisError as exc:
            _log.warning("ai_meal cache event=error op=get kind=%s", type(exc).__name__)
            return None

    def put(self, key: str, raw: str) -> None:
        try:
            self._client.set(key, raw, ex=self._ttl)
        except RedisError as exc:
            _log.warning("ai_meal cache event=error op=set kind=%s", type(exc).__name__)
