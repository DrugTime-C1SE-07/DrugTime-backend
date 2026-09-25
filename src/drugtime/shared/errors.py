class DomainError(Exception):
    """Vi phạm quy tắc nghiệp vụ (HTTP 422)."""


class NotFound(DomainError):
    """Không tìm thấy (HTTP 404)."""


class Unauthorized(Exception):
    """Chưa xác thực hoặc tài khoản đã bị xóa (HTTP 401)."""


class Forbidden(Exception):
    """Không có quyền (HTTP 403)."""
