"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

- redis.from_url() KHÔNG mở kết nối ngay; kết nối chỉ được tạo ở lệnh đầu tiên.
  Nhờ vậy app vẫn khởi động được khi Redis chưa sẵn sàng (yêu cầu của Docker check).
- Timeout ngắn (1s) để khi Redis chết, /ready trả 503 nhanh thay vì treo.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: True nếu PING được Redis."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
