"""
Production AI Agent — Part 6 Final Project.

Kiểm tra: python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object ──────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
# force=True: thay mọi handler đã có, đảm bảo không còn dòng log dạng text thường
logging.basicConfig(level=settings.log_level, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": {"event": event, **fields}})


# ── Graceful shutdown (tiêu chí 11) ─────────────────────────────────────────
# uvicorn tự bắt SIGTERM: ngừng nhận request mới → chờ request đang chạy xong →
# chạy phần sau `yield` của lifespan → thoát exit code 0.
# Không tự đăng ký signal handler để khỏi vô tình chặn cơ chế đó của uvicorn.
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment, port=settings.port,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              daily_budget_usd=settings.daily_budget_usd)
    yield
    log_event("shutdown", reason="SIGTERM / lifespan shutdown")
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


# ── Access log + không lộ stack trace ra ngoài ──────────────────────────────
@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled_error",
                         extra={"fields": {"event": "unhandled_error", "path": request.url.path}})
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    log_event("request", method=request.method, path=request.url.path,
              status=response.status_code,
              ms=round((time.perf_counter() - start) * 1000, 1))
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


def _estimate_tokens(text: str) -> int:
    """Mock LLM không trả về số token → ước lượng ~4 ký tự / token."""
    return max(1, len(text) // 4)


# ── Health / readiness (tiêu chí 4, 5) ───────────────────────────────────────
@app.get("/health")
def health():
    """Liveness: process còn sống → 200. KHÔNG phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi kết nối được Redis, nếu không → 503."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not reachable")
    return {"status": "ready"}


# ── Endpoint chính ───────────────────────────────────────────────────────────
@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):   # 401
    check_rate_limit(api_key)                                         # 429
    check_budget()                                                    # 402
    answer = llm_ask(body.question)
    cost = record_cost(_estimate_tokens(body.question), _estimate_tokens(answer))
    log_event("ask", user_id=body.user_id, question_chars=len(body.question),
              cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}
