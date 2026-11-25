"""Cache key cho output LLM gợi ý bữa ăn (CD10, task 5.09 AC1, AC2).

Key băm toàn bộ prompt gửi provider: `user` là JSON `sort_keys` của input đã tối thiểu hóa (bữa ăn,
hoạt chất, bệnh nền, thực phẩm cần tránh, dị ứng, hạn chế, sở thích, phiên bản prompt), nên
không có định danh và đổi bất kỳ trường nào thì key đổi. `system` cũng được băm để sửa prompt mà
quên tăng `PROMPT_VERSION` không dùng lại output cũ.

`user` được casefold trước khi băm: `clean_list` giữ nguyên cách viết hoa của người dùng nên
"Tôm" và "tôm" cho prompt khác chữ hoa (AC1). Không bỏ dấu: "Cá" và "Cà" là hai thực phẩm khác.
"""

import hashlib
import json

from drugtime.modules.ai_meal.domain.prompt import MealPrompt

CACHE_KEY_PREFIX = "meal_cache:"


def cache_key(prompt: MealPrompt) -> str:
    parts = [prompt.version, prompt.system, prompt.user.casefold()]
    payload = json.dumps(parts, ensure_ascii=False)
    return CACHE_KEY_PREFIX + hashlib.sha256(payload.encode("utf-8")).hexdigest()
