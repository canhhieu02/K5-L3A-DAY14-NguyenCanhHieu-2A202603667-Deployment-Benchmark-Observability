"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày (UTC)
  • Tổng chi phí trong ngày >= DAILY_BUDGET_USD → HTTP 402
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

KEY_TTL_SECONDS = 2 * 24 * 3600  # giữ 2 ngày rồi Redis tự xoá


def _cost_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc):%Y-%m-%d}"


def current_spend() -> float:
    return float(r.get(_cost_key()) or 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    try:
        spent = current_spend()
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Cost guard unavailable")
    if spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    key = _cost_key()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(key, cost)   # nguyên tử → nhiều worker cộng cùng lúc không mất số
        pipe.expire(key, KEY_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError:
        # Câu trả lời đã có rồi — không làm hỏng response chỉ vì ghi chi phí thất bại.
        pass
    return cost
