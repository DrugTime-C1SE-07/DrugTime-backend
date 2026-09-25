from typing import Protocol


class MealSuggester(Protocol):
    """LLM Provider. Chỉ gửi ngữ cảnh tối thiểu (bệnh nền), không gửi định danh (DPIA)."""

    def suggest(self, conditions: list[str]) -> list[str]: ...
