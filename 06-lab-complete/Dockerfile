# ============================================================
# Production Dockerfile — multi-stage (tiêu chí 1, 12)
#   Stage 1 (builder): cài dependencies vào /install
#   Stage 2 (runtime): base slim sạch, chỉ copy package đã cài + code, user non-root
# ============================================================

# ---------- Stage 1: builder ----------
FROM python:3.11-slim AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# Copy requirements TRƯỚC code → sửa code không làm mất cache layer cài thư viện
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
# Package cài bằng --prefix nằm ở chỗ chuẩn (/usr/local) → user non-root import được
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser utils/ ./utils/
USER appuser
EXPOSE 8000
# Image slim không có curl → dùng Python để gọi /health
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=2)" || exit 1
# exec → uvicorn thay thế shell, trở thành PID 1 và nhận SIGTERM khi `docker stop`
# ${PORT:-8000} → nghe theo port do Railway/Render cấp
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
