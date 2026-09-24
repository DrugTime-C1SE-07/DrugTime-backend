"""In-memory sliding window rate limiter for brute-force sensitive endpoints (e.g. Caregiver Code Redeem)."""
import time
from typing import Dict, List
from fastapi import HTTPException, status, Request

class FailedAttemptLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        # key -> list of failure timestamps
        self._failures: Dict[str, List[float]] = {}

    def _clean_old_attempts(self, key: str, now: float):
        if key in self._failures:
            threshold = now - self.window_seconds
            self._failures[key] = [t for t in self._failures[key] if t > threshold]
            if not self._failures[key]:
                del self._failures[key]

    def check(self, key: str):
        """Raises HTTP 429 if the key has exceeded max allowed failed attempts."""
        now = time.time()
        self._clean_old_attempts(key, now)
        attempts = self._failures.get(key, [])
        if len(attempts) >= self.max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "LINK_CODE_RATE_LIMITED",
                    "message": f"Bạn đã nhập sai mã quá {self.max_attempts} lần. Vui lòng thử lại sau {self.window_seconds // 60} phút."
                }
            )

    def record_failure(self, key: str):
        now = time.time()
        self._clean_old_attempts(key, now)
        if key not in self._failures:
            self._failures[key] = []
        self._failures[key].append(now)

    def reset(self, key: str):
        if key in self._failures:
            del self._failures[key]

class CodeFailureTracker:
    """Tracks global failed attempts per link-code to prevent distributed brute-force attacks."""
    def __init__(self, max_attempts: int = 10):
        self.max_attempts = max_attempts
        self._counts: Dict[str, int] = {}

    def check(self, code: str):
        c = self._counts.get(code.strip().upper(), 0)
        if c >= self.max_attempts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LINK_CODE_INVALIDATED",
                    "message": f"Mã liên kết này đã bị vô hiệu hóa do nhập sai quá {self.max_attempts} lần. Vui lòng yêu cầu bệnh nhân sinh mã mới."
                }
            )

    def record_failure(self, code: str) -> int:
        norm = code.strip().upper()
        self._counts[norm] = self._counts.get(norm, 0) + 1
        return self._counts[norm]

    def clear(self):
        self._counts.clear()

# Singleton instances
redeem_rate_limiter = FailedAttemptLimiter(max_attempts=5, window_seconds=900)
code_failure_tracker = CodeFailureTracker(max_attempts=10)

def get_client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"

