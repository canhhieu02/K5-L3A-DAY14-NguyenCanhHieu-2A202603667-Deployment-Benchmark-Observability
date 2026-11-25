# Deployment Information

## Public URL

https://agent-production-5cce1ae2.up.railway.app

## Platform

**Railway**, project `terrific-magic`, environment `production`, 2 service:

| Service | Nguồn | Ghi chú |
|---|---|---|
| `agent` | `railway up --service agent` từ thư mục `06-lab-complete/` | Build bằng `Dockerfile` theo `railway.toml` (`builder = "DOCKERFILE"`, `healthcheckPath = "/health"`). Uvicorn nghe cổng `PORT` do Railway cấp (8080) |
| `Redis` | Railway Database → Redis (`redis:8.2`, có volume) | Không public, agent kết nối qua mạng nội bộ bằng `REDIS_URL` |

## Test Commands

```bash
export BASE="https://agent-production-5cce1ae2.up.railway.app"
export AGENT_API_KEY="<key đã đặt trên Railway>"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả thực tế (25/11/2026, ảnh `screenshots/test.png`):

```text
health: 200
ready: 200
ask khong key: 401
ask co key: 200
```

Body trả về:

```text
GET  /health               → {"status":"ok","environment":"production"}
GET  /ready                → {"status":"ready"}          (kết nối được Redis trên Railway)
POST /ask (không / sai key) → {"detail":"Invalid or missing API key"}   401
```

Kiểm tra thêm bằng script chấm: `python check_production_ready.py --public-url https://agent-production-5cce1ae2.up.railway.app` → `✅ Public URL: GET .../health → 200`.

## Environment Variables Set

Đặt bằng `railway variables --service agent --set ...` (giá trị **không** ghi trong code hay repo):

- `AGENT_API_KEY`: chuỗi ngẫu nhiên 48 ký tự hex (sinh bằng `secrets.token_hex(24)`)
- `REDIS_URL`: `${{Redis.REDIS_URL}}`, tham chiếu biến của service Redis, Railway tự thay bằng URL nội bộ
- `ENVIRONMENT`: `production`
- `RATE_LIMIT_PER_MINUTE`: `10`
- `DAILY_BUDGET_USD`: `1.0`
- `PORT`: Railway tự cấp (8080), không đặt tay; CMD trong Dockerfile đọc `${PORT:-8000}`

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png): project có 2 service `agent` + `Redis`, cả hai Online
- [Service running](screenshots/running.png): deployment ACTIVE, "Deployment successful"
- [Test results](screenshots/test.png): 4 lệnh tự kiểm 200 / 200 / 401 / 200
