"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường (tiêu chí 9).

Mỗi field dùng default_factory nên giá trị được đọc tại thời điểm app khởi động,
không phải lúc định nghĩa class → cùng một image chạy được ở dev / staging / production
chỉ bằng cách đổi biến môi trường. Không có secret nào nằm trong code.
"""
import os
from dataclasses import dataclass, field


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float_env(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass
class Settings:
    port: int = field(default_factory=lambda: _int_env("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    # Mặc định rỗng → quên đặt key thì mọi request /ask bị 401 (an toàn mặc định).
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    rate_limit_per_minute: int = field(default_factory=lambda: _int_env("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _float_env("DAILY_BUDGET_USD", 1.0))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())


settings = Settings()
