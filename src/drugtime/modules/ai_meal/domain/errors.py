"""Lỗi của gợi ý bữa ăn (task 4.26).

Message chỉ là mã lý do cố định, không bao giờ chứa nội dung từ provider, prompt hay key.
"""

from drugtime.shared.errors import DomainError


class MealInputIncomplete(DomainError):
    """Thiếu hoặc mâu thuẫn dữ liệu bắt buộc (QD-40): không tạo gợi ý, không gọi provider."""


class LlmDisabled(Exception):
    """Tính năng tắt (`AI_MEAL_LLM_ENABLED`) hoặc chưa cấu hình `LLM_API_KEY`."""

    def __init__(self) -> None:
        super().__init__("llm_disabled")


class LlmUnavailable(Exception):
    """Provider lỗi, quá tải, sai key hoặc quá thời gian."""

    REASONS = frozenset({"auth", "rate_limited", "upstream", "network", "timeout"})

    def __init__(self, reason: str) -> None:
        if reason not in self.REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        super().__init__(reason)
        self.reason = reason


class LlmInvalidOutput(Exception):
    """Provider trả nội dung không dùng được; không bao giờ trả gợi ý một phần."""

    REASONS = frozenset(
        {"invalid_json", "schema", "refusal", "max_tokens", "no_valid_suggestion"}
    )

    def __init__(self, reason: str) -> None:
        if reason not in self.REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        super().__init__(reason)
        self.reason = reason


class PreviousSuggestionNotFound(Exception):
    """`previous_suggestion_id` không tồn tại, của người khác hoặc khác bữa (task 5.11, AC16).

    Ba trường hợp không phân biệt để không lộ việc bản ghi có tồn tại hay không.
    """

    def __init__(self) -> None:
        super().__init__("previous_suggestion_not_found")


class RefreshLimitReached(Exception):
    """Hết lượt "Gợi ý khác" trong ngày (task 5.11, AC27). `retry_after`: giây tới 00:00 VN."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("refresh_limit_reached")
        self.retry_after = retry_after


class MealImageNotFound(Exception):
    """Ảnh không tồn tại hoặc chưa `ready` (task 5.11)."""

    def __init__(self) -> None:
        super().__init__("meal_image_not_found")


class ImageSearchFailed(Exception):
    """Tìm hoặc tải ảnh thất bại (Worker). Chỉ mang mã lý do, không mang URL hay key."""

    REASONS = frozenset(
        {"no_result", "rate_limited", "upstream", "network", "timeout", "too_large",
         "not_image", "invalid_response"}
    )

    def __init__(self, reason: str) -> None:
        if reason not in self.REASONS:
            raise ValueError(f"unknown reason {reason!r}")
        super().__init__(reason)
        self.reason = reason


class StorageUnavailable(Exception):
    """Kho lưu trữ ảnh lỗi. Không mang URL, header hay key."""

    def __init__(self, reason: str = "storage") -> None:
        super().__init__(reason)
        self.reason = reason
