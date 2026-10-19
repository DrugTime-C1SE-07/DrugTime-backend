class DomainError(Exception):
    """Vi phạm quy tắc nghiệp vụ (HTTP 422)."""


class NotFound(DomainError):
    """Không tìm thấy (HTTP 404)."""


class Unauthorized(Exception):
    """Chưa xác thực hoặc tài khoản đã bị xóa (HTTP 401)."""


class Forbidden(Exception):
    """Không có quyền (HTTP 403)."""


class Conflict(Exception):
    """Xung đột với trạng thái hiện tại, ví dụ trùng bản ghi hoặc phiên bản cũ (HTTP 409)."""


class TooManyRequests(Exception):
    """Gửi quá nhanh hoặc quá nhiều lần (HTTP 429).

    `retry_after`: số giây còn phải chờ; có thì response kèm header `Retry-After`.
    """

    def __init__(self, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class ServiceUnavailable(Exception):
    """Dịch vụ phụ thuộc lỗi hoặc không phản hồi (HTTP 503)."""
