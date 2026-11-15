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
