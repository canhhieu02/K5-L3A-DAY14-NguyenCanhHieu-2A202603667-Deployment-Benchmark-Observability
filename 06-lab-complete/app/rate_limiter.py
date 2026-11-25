"""
Rate limiting (tiêu chí 7) — sliding window 60 giây bằng Redis sorted set.

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây
  • Vượt giới hạn → HTTP 429 + header Retry-After
  • State nằm trong Redis: mọi worker / instance dùng chung, còn nguyên sau khi restart agent
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket_key(api_key: str) -> str:
    # Không lưu API key thô trong Redis — chỉ lưu bản băm.
    return "ratelimit:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]


def check_rate_limit(key: str) -> None:
    rkey = _bucket_key(key)
    now = time.time()
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(rkey, 0, now - WINDOW_SECONDS)  # 1. bỏ request cũ hơn 60s
        pipe.zcard(rkey)                                      # 2. đếm request trong cửa sổ
        _, count = pipe.execute()

        if count >= settings.rate_limit_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        pipe = r.pipeline()
        # member có uuid để 2 request cùng timestamp không ghi đè nhau
        pipe.zadd(rkey, {f"{now}:{uuid.uuid4().hex}": now})   # 3. ghi request này
        pipe.expire(rkey, WINDOW_SECONDS + 5)                 # 4. tự dọn key khi không dùng
        pipe.execute()
    except redis.RedisError:
        # Redis chết → báo 503 rõ ràng thay vì 500 kèm stack trace
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
