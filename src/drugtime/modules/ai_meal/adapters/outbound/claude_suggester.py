"""Adapter Claude (Anthropic Messages API) cho gợi ý bữa ăn (task 4.26, AC3, AC3b, AC8, AC9).

- SDK chính thức `anthropic`, structured outputs (`output_config.format` = JSON schema).
- `max_retries=0` và timeout theo cấu hình: tổng request ≤ 10 giây (PB37).
- Lỗi SDK đổi sang lỗi domain bằng `from None`: không mang response thô, header hay key theo.
- Logger `anthropic` ở mức WARNING: ở DEBUG, SDK in cả body request (dữ liệu sức khỏe).
"""

import logging

import anthropic
import httpx

from drugtime.modules.ai_meal.domain.errors import LlmInvalidOutput, LlmUnavailable
from drugtime.modules.ai_meal.domain.model import MealPrompt
from drugtime.modules.ai_meal.domain.prompt import LLM_OUTPUT_SCHEMA

logging.getLogger("anthropic").setLevel(logging.WARNING)

# JSON 6 món ~3–4K token; đủ chỗ cho thinking ở effort thấp mà không chạm giới hạn.
MAX_TOKENS = 8000
# Sonnet 5.5 mặc định adaptive thinking; effort thấp để giữ độ trễ trong ngân sách.
EFFORT = "low"


class ClaudeMealSuggester:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._model = model
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url or None,
            timeout=timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    def __repr__(self) -> str:
        return f"ClaudeMealSuggester(model={self._model!r})"

    def suggest(self, prompt: MealPrompt) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user}],
                output_config={
                    "effort": EFFORT,
                    "format": {"type": "json_schema", "schema": LLM_OUTPUT_SCHEMA},
                },
            )
        # Từ cụ thể tới chung; APITimeoutError là lớp con của APIConnectionError.
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise LlmUnavailable("auth") from None
        except anthropic.RateLimitError:
            raise LlmUnavailable("rate_limited") from None
        except anthropic.APITimeoutError:
            raise LlmUnavailable("timeout") from None
        except anthropic.APIConnectionError:
            raise LlmUnavailable("network") from None
        except anthropic.APIStatusError:
            raise LlmUnavailable("upstream") from None
        except anthropic.APIResponseValidationError:
            raise LlmInvalidOutput("schema") from None

        if response.stop_reason == "refusal":
            raise LlmInvalidOutput("refusal")
        if response.stop_reason == "max_tokens":
            raise LlmInvalidOutput("max_tokens")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LlmInvalidOutput("schema")
        return text
