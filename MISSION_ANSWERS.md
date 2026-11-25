# Day 14 Lab — Mission Answers

> Môi trường chạy: Windows 11, Intel i5-10300H (4 nhân / 8 luồng), RAM 16 GB, Docker Desktop 29.9.3 (VM 8 CPU / 7,7 GB), Python 3.12 (venv) cho các bài chạy local.
> Bài kiểm tra cần tín hiệu SIGTERM (Part 5.2, Part 6) được chạy **trong container Linux** vì Windows không gửi được SIGTERM.
> Mọi output dưới đây là output thật từ các lệnh đã chạy ngày 25/11/2026.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Vì sao nguy hiểm |
|---|---|---|---|
| 1 | Hardcode secret: `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL = "postgresql://admin:password123@..."` | 17–18 | Push lên GitHub là lộ key và mật khẩu DB. Muốn đổi key phải sửa code rồi deploy lại |
| 2 | **Ghi secret ra log**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Log thường được gửi sang hệ thống tập trung và nhiều người đọc được → lộ key kể cả khi code không bị lộ |
| 3 | Config cứng trong code: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Không đổi được giữa dev/staging/prod nếu không sửa code; debug bật ở production |
| 4 | Log bằng `print()` (không level, không cấu trúc) | 33, 34, 38 | Không lọc theo mức độ, không parse được, không gắn request_id |
| 5 | Không có `/health` (chỉ có comment) | 42 | Platform không biết app còn sống để restart hoặc ngừng route traffic |
| 6 | Bind `host="localhost"` | 51 | Trong container, chỉ nghe localhost thì bên ngoài container không gọi vào được |
| 7 | Port cứng `port=8000` | 52 | Railway/Render cấp port qua biến `PORT` → app không nhận được traffic |
| 8 | `reload=True` | 53 | Chế độ dev: theo dõi file và tự restart, tốn tài nguyên, không dùng ở production |
| 9 | Không xử lý shutdown (không lifespan, không bắt SIGTERM) | cả file | Deploy bản mới hoặc scale down sẽ cắt ngang request đang chạy |

**Phát hiện thêm khi chạy thật trên Windows:** lần chạy đầu, `POST /ask?question=Hello` trả **500 Internal Server Error**: `print()` câu trả lời tiếng Việt ra console cp1252 gây `UnicodeEncodeError` (dòng 38). Phải đặt `PYTHONUTF8=1` mới chạy được. Đây là ví dụ thật của "chạy được trên máy này, hỏng trên máy khác": hành vi của app phụ thuộc vào cấu hình console của máy.

### Exercise 1.2: Chạy bản develop

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 422 Unprocessable Entity
{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
```

Log của server, cho thấy secret bị in ra:

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
```

**Quan sát:** app chạy được nhưng chưa sẵn sàng cho production: không có health check, nhận input qua query, lộ secret trong log, chỉ nghe `localhost`.

### Exercise 1.3: So sánh develop và production

Bản production chạy thử: `/health` → 200 (có uptime, version, environment), `/ready` → 200 `{"ready":true}`, `/ask` nhận JSON → 200, Uvicorn nghe `0.0.0.0:8000`.

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (dòng 17–22) | `config.py`: mọi giá trị đọc từ env (`os.getenv`), có `validate()` fail-fast khi thiếu `AGENT_API_KEY` ở production | Cùng một code/image chạy được ở mọi môi trường; secret không nằm trong git |
| Secret | Hardcode + in ra log | Đọc từ env, log chỉ ghi `question_length`, `client_ip` | Không lộ secret qua code lẫn log |
| Health check | Không có | `/health` (liveness) + `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform tự restart app chết và chỉ gửi traffic vào instance đã sẵn sàng |
| Logging | `print()` | `logging` với format JSON | Máy đọc được, lọc theo field, đưa vào Loki/Datadog |
| Shutdown | Đột ngột | `lifespan` (startup/shutdown) + handler SIGTERM | Request đang chạy được xử lý xong khi deploy/scale |
| Host / Port | `localhost:8000` cứng | `HOST`/`PORT` từ env, mặc định `0.0.0.0` | Chạy được trong container và trên cloud |
| Reload | Luôn bật | Chỉ bật khi `DEBUG=true` | Production không dùng chế độ dev |
| CORS | Không có | `allowed_origins` từ env | Chỉ cho phép frontend hợp lệ gọi API |

**Lưu ý về bản production:** khi chạy thật, mình **không thấy dòng log JSON nào** của app. Nguyên nhân: `config.py` gọi `logging.warning("OPENAI_API_KEY not set …")` lúc import. Lời gọi này tự cấu hình root logger (level WARNING, format mặc định) **trước** khi `app.py` chạy `logging.basicConfig(format=JSON)`, nên lệnh `basicConfig` trong `app.py` không còn tác dụng. Output thực tế là `WARNING:root:OPENAI_API_KEY not set — using mock LLM`, và các log INFO dạng JSON bị nuốt mất. Đây là lý do Part 6 cấu hình logging bằng `basicConfig(..., force=True)`.

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Python đầy đủ dựa trên Debian (có compiler, header, nhiều tool). Image cuối nặng 1,67 GB.
2. **Working directory:** `/app` (`WORKDIR /app`), mọi lệnh `COPY`/`RUN`/`CMD` sau đó chạy ở thư mục này.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer, và một layer chỉ phải build lại khi input của nó đổi. Copy `requirements.txt` rồi `pip install` trước thì khi chỉ sửa `app.py`, layer cài thư viện vẫn dùng cache: build lại mất vài giây thay vì cài lại toàn bộ thư viện.
4. **CMD và ENTRYPOINT:** `ENTRYPOINT` là chương trình cố định của container. `CMD` là lệnh hoặc tham số **mặc định**, bị ghi đè khi chạy `docker run image <lệnh khác>`. Khi dùng cả hai thì `CMD` trở thành tham số cho `ENTRYPOINT`. Dockerfile này chỉ dùng `CMD ["python", "app.py"]` ở dạng exec (mảng JSON), nên python là PID 1 và nhận tín hiệu trực tiếp.

### Exercise 2.2: Build và chạy (build từ gốc repo)

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d -p 8000:8000 my-agent:develop
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":0.5,"container":true}
$ docker exec p2-develop whoami
root
```

### Exercise 2.3: Multi-stage build và so sánh kích thước

- **Stage 1 (builder):** `python:3.11-slim` + `apt-get install gcc libpq-dev` + `pip install --user -r requirements.txt` → toàn bộ package nằm trong `/root/.local`. Stage này có compiler để build package native, nhưng **không được deploy**.
- **Stage 2 (runtime):** bắt đầu lại từ `python:3.11-slim` sạch, tạo user `appuser`, `COPY --from=builder /root/.local`, copy `main.py` + `utils/`, chạy `USER appuser`, có `HEALTHCHECK`, `CMD uvicorn ... --workers 2`.
- **Vì sao nhỏ hơn:** image cuối không chứa gcc, header, apt cache hay pip cache của stage 1. Base `slim` cũng nhỏ hơn nhiều so với base đầy đủ.

Số đo thật (`docker images my-agent` và `docker image inspect --format '{{.Size}}'`):

```text
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   54a2b2501715        240MB         57.4MB
my-agent:develop    3d3885fbacd5       1.67GB          426MB

my-agent:develop   .Size=1667796303   (≈ 1667,8 MB)
my-agent:advanced  .Size=239815443    (≈  239,8 MB)
```

- Develop: **1667,8 MB**
- Production: **239,8 MB**
- Chênh lệch: (1667,8 − 239,8) / 1667,8 = **85,6 %** nhỏ hơn (gấp khoảng 7 lần)
- Kiểm tra thêm: `docker exec ... whoami` → develop chạy bằng **root**, production chạy bằng **appuser**.

### Exercise 2.4: Docker Compose stack (`02-docker/production`)

Sơ đồ (đọc từ `docker-compose.yml`):

```text
                 cổng 80/443 (public)
Client ──────────────► nginx (nginx:alpine, reverse proxy + rate limit 10r/s, security headers)
                          │  proxy_pass http://agent:8000   (mạng nội bộ "internal")
                          ▼
                       agent (build từ 02-docker/production/Dockerfile, target runtime, KHÔNG mở port ra ngoài)
                          │                         │
          REDIS_URL=redis://redis:6379/0   QDRANT_URL=http://qdrant:6333
                          ▼                         ▼
                 redis:7-alpine (cache/session)   qdrant v1.9.0 (vector DB)
                 volume redis_data                volume qdrant_data
```

- 4 service: `agent`, `redis`, `qdrant`, `nginx`, cùng nằm trong network bridge `internal`.
- Các service gọi nhau bằng **tên service** (DNS nội bộ của Compose): `redis`, `qdrant`, `agent`.
- `agent` có `depends_on` redis + qdrant với `condition: service_healthy`, nên chỉ khởi động khi DB đã sẵn sàng.
- Chỉ Nginx mở port ra ngoài, agent bị ẩn sau proxy.

Kết quả test (chạy với `-p k5-day14-docker` theo lưu ý K5):

```text
SERVICE   IMAGE                   STATUS                            PORTS
agent     k5-day14-docker-agent   Up 4 seconds (health: starting)   8000/tcp
nginx     nginx:alpine            Up 3 seconds                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 15 seconds (healthy)           6333-6334/tcp
redis     redis:7-alpine          Up 15 seconds (healthy)           6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
{"status":"ok","uptime_seconds":2.7,"version":"2.0.0","timestamp":"2026-11-25T08:51:44.414010"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Header `Server: nginx` và các security header chứng tỏ request đi qua Nginx rồi mới tới agent. Log của agent ghi nhận đúng request đó:
`{"time":"2026-11-25 08:51:44,452","level":"INFO","msg":"{"event": "request", "q_len": 21}"}`.
Dòng này **không phải JSON hợp lệ** (chuỗi JSON lồng trong `msg` mà không escape dấu nháy). Part 6 tránh lỗi này bằng một `JsonFormatter` dùng `json.dumps` cho toàn bộ dòng log.

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

Theo cách làm của K5: deploy luôn **agent Part 6** (thư mục `06-lab-complete/`), không deploy app mẫu `03-cloud-deployment/`.

- **Nền tảng:** Railway, project gồm service `agent` (build bằng `Dockerfile` theo `06-lab-complete/railway.toml`) + service `Redis` (`redis:8.2`).
- **URL public:** https://agent-production-5cce1ae2.up.railway.app
- **Cách deploy:** `railway login` → `railway link` → `railway add --service agent` → `railway up --service agent` → `railway variables --service agent --set ...` → `railway domain --service agent`.
- **Biến môi trường** (đặt trên Railway, không ghi trong code): `AGENT_API_KEY` (ngẫu nhiên), `REDIS_URL=${{Redis.REDIS_URL}}`, `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1.0`. `PORT` do Railway cấp (8080).
- **Kết quả 4 lệnh tự kiểm:**

```text
health: 200          {"status":"ok","environment":"production"}
ready: 200           {"status":"ready"}
ask khong key: 401   {"detail":"Invalid or missing API key"}
ask co key: 200
```

- `python check_production_ready.py --public-url https://agent-production-5cce1ae2.up.railway.app` → `✅ Public URL: GET .../health → 200`.
- **Ảnh:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`.
- **Quan sát khi deploy:** log khởi động trên Railway hiển thị dạng `[INFO] startup ts=... event="startup" port=8080`, tức Railway tự parse log JSON của app thành từng field, nhờ structured logging. Railway CLI cảnh báo `railway.toml` sắp bị thay bằng định dạng `.railway/railway.ts` (vẫn dùng được tới 01/12/2026); mình giữ `railway.toml` vì đó là file script chấm kiểm tra.

### So sánh `railway.toml` và `render.yaml` (`03-cloud-deployment/`)

| Khía cạnh | `railway/railway.toml` | `render/render.yaml` |
|---|---|---|
| Định dạng | TOML | YAML (Render Blueprint) |
| Phạm vi | Cấu hình **build và deploy của 1 service** | Mô tả **cả hạ tầng**: web service + Redis trong cùng một file (Infrastructure as Code) |
| Build | `builder = "NIXPACKS"` (tự nhận diện Python), có thể đổi sang `DOCKERFILE` | `runtime: python` + `buildCommand: pip install -r requirements.txt` (hoặc `runtime: docker`) |
| Start | `startCommand = "uvicorn app:app --host 0.0.0.0 --port $PORT"` | `startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT` |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout = 30` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, tối đa 3 lần | Render tự quản lý |
| Biến môi trường / secret | **Không khai báo trong file**: đặt bằng `railway variables set` hoặc trên dashboard | Khai báo ngay trong file: giá trị thường (`value:`), secret nhập tay (`sync: false`), hoặc **để Render tự sinh** (`generateValue: true`) |
| Database | Thêm Redis plugin riêng trên dashboard, rồi tham chiếu `${{Redis.REDIS_URL}}` | Khai báo `type: redis` trong cùng blueprint |
| Khác | — | Chọn `region: singapore`, `plan: free`, `autoDeploy: true` (tự deploy khi push GitHub) |

**Vì sao khác nhau:** Railway đi theo hướng "CLI-first": file chỉ nói cách build/chạy, còn môi trường và dịch vụ phụ được quản lý trên nền tảng. Render đi theo hướng "Blueprint": toàn bộ hạ tầng nằm trong git, review được qua PR và tái tạo lại được. Cả hai đều cấp `PORT` qua biến môi trường và đều dùng `/health` để quyết định có chuyển traffic sang bản deploy mới hay không.

### Exercise 3.3: Pipeline Cloud Run (`cloudbuild.yaml` + `service.yaml`)

Pipeline CI/CD gồm 4 bước tuần tự (`waitFor`), thường được kích hoạt khi push lên `main`:
1. **test:** trong image `python:3.11-slim`, cài requirements + pytest rồi chạy `pytest tests/`. Fail thì dừng toàn bộ pipeline.
2. **build:** `docker build` với 2 tag `ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache.
3. **push:** đẩy image lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **deploy:** `gcloud run deploy` image theo đúng `$COMMIT_SHA` (truy vết được, rollback được) ở `asia-southeast1`; min 1 / max 10 instance (tránh cold start, chặn chi phí), 512 Mi RAM, 1 CPU, timeout 60 s, secret lấy từ **Secret Manager** (`--set-secrets`), không hardcode.

`service.yaml` mô tả cùng service đó dưới dạng khai báo (Knative): `containerConcurrency: 80`, autoscaling 1–10, `livenessProbe` gọi `/health`, `startupProbe` gọi `/ready`, secret qua `secretKeyRef`.
*Nhận xét:* thư mục `production-cloud-run/` không có thư mục `tests/`, nên bước 1 (`pytest tests/`) sẽ fail và chặn cả pipeline. Muốn chạy thật thì phải thêm test (hoặc bỏ bước đó).

---

## Part 4: API Security

### Exercise 4.1: API key (`04-api-gateway/develop`, chạy với `AGENT_API_KEY=secret-key-123`)

- **Key được kiểm ở đâu:** dependency `verify_api_key()` (dòng 39–54) đọc header `X-API-Key` bằng `APIKeyHeader(name="X-API-Key", auto_error=False)` và được gắn vào `/ask` qua `Depends(verify_api_key)` (dòng 70).
- **Sai key thì sao:** **thiếu** key → 401 `Missing API key`; **sai** key → **403** `Invalid API key`. (Hợp đồng Part 6 yêu cầu cả hai trường hợp đều trả 401, nên Part 6 làm khác chỗ này.)
- **Rotate key:** key đọc từ biến `AGENT_API_KEY`, nên chỉ cần đặt giá trị mới trên nền tảng rồi restart hoặc redeploy, không phải sửa code. Muốn rotate không gây gián đoạn thì cho phép **2 key cùng lúc** (cũ + mới) trong một khoảng chuyển tiếp, rồi mới bỏ key cũ.

```text
# 1) Không có key
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# 2) Sai key
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

# 3) Đúng key (X-API-Key: secret-key-123)
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`)

Luồng JWT (`auth.py`): `POST /auth/token` kiểm username/password → `create_token()` ký payload `{sub, role, iat, exp = +60 phút}` bằng HS256 với `JWT_SECRET` → client gửi `Authorization: Bearer <token>` → `verify_token()` kiểm chữ ký và hạn dùng (hết hạn → 401, sai chữ ký → 403), không cần tra database.

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN_DA_CHE>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN_DA_CHE>"}

# Không có token → 401
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Có token → 200
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window log: mỗi user có một `deque` lưu timestamp các request. Mỗi lần kiểm thì xoá timestamp cũ hơn 60 s, rồi đếm số còn lại (`rate_limiter.py`).
- **Giới hạn:** user thường **10 request / 60 giây**, admin **100 request / 60 giây**.
- **"Bypass" cho admin:** không bỏ hẳn giới hạn mà chọn limiter theo role: `role == "admin"` thì dùng `rate_limiter_admin` (100/phút). Tài khoản demo admin là `teacher`.
- **Hạn chế:** state nằm trong RAM của từng process, nên chạy nhiều instance thì mỗi instance đếm riêng, còn restart thì mất state. Part 6 đã chuyển state này sang Redis.

Vòng lặp của mình (đã gọi 1 request ở bước 4.2 nên chỉ còn 9 lượt):

```text
$ for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" ...; done
req  1 -> 200   req  2 -> 200   req  3 -> 200   req  4 -> 200   req  5 -> 200
req  6 -> 200   req  7 -> 200   req  8 -> 200   req  9 -> 200   req 10 -> 429
req 11 -> 429   ...             req 20 -> 429

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" ...
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795596870
retry-after: 53
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":53}}
```

### Exercise 4.4: Cost guard

**Cách làm của `cost_guard.py` (bản mẫu):** mỗi request ước lượng token (`len(words) × 2`), tính tiền theo bảng giá (input $0,15/1M, output $0,60/1M) và cộng vào `UsageRecord` của user trong ngày. **Trước** khi gọi LLM, `check_budget()` kiểm tra: tổng toàn hệ thống ≥ $10/ngày → 503; của user ≥ $1/ngày → **402 Payment Required**; ≥ 80% → ghi log cảnh báo. **Sau** khi gọi LLM, `record_usage()` cộng chi phí thật. Bản ghi tự reset khi sang ngày mới (so sánh `day`).

Usage thật của user `student` sau bài test: `{"requests":10,"input_tokens":40,"output_tokens":296,"cost_usd":0.000184,"budget_usd":1.0,"budget_remaining_usd":0.999816}`.

**Phiên bản dùng Redis** (theo đề: $10/tháng, reset đầu tháng, dùng được cho nhiều instance):

```python
def check_budget(user_id: str, estimated_cost: float) -> bool:
    key = f"budget:{user_id}:{datetime.now(timezone.utc):%Y-%m}"   # key theo tháng → tự reset đầu tháng
    current = float(r.get(key) or 0)
    if current + estimated_cost > 10:
        return False                                              # caller trả 402
    r.incrbyfloat(key, estimated_cost)                            # nguyên tử, nhiều instance cộng không mất số
    r.expire(key, 32 * 24 * 3600)                                 # tự dọn sau ~1 tháng
    return True
```

Phần `06-lab-complete/app/cost_guard.py` của mình áp dụng đúng ý tưởng này theo ngày (`DAILY_BUDGET_USD`), tách 2 bước `check_budget()` (trước khi gọi LLM) và `record_cost()` (sau khi gọi LLM, khi đã biết số token thật).

**Vì sao cần cả rate limit và cost guard:** rate limit bảo vệ **tốc độ** (chống spam, chống quá tải), còn cost guard bảo vệ **tiền**. 10 request/phút nghe thì ít, nhưng nếu kéo dài 24/7 với prompt dài thì hoá đơn LLM vẫn rất lớn. Ngược lại, chỉ có cost guard thì một client có thể đốt sạch ngân sách cả ngày trong vài giây.

*Lỗi nhỏ phát hiện được:* response `/ask` có field `budget_remaining_usd` nhưng giá trị lại là **số tiền đã dùng** (`usage.total_cost_usd`), không phải số còn lại.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health check và readiness (`05-scaling-reliability/develop`)

| | `/health` (liveness) | `/ready` (readiness) |
|---|---|---|
| Câu hỏi | Process còn sống không? | Có sẵn sàng nhận traffic không? |
| Bản develop kiểm tra | Uptime, version, RAM (psutil, "degraded" khi > 90%) | Cờ `_is_ready` (False lúc đang khởi động hoặc đang shutdown) + số request đang xử lý |
| Fail thì platform làm gì | **Restart** container | **Ngừng route traffic** vào instance (không restart) |

`/health` không được phụ thuộc Redis hay DB: nếu DB chết mà `/health` báo lỗi thì platform sẽ restart agent liên tục, nhưng restart không chữa được DB. Cách đúng là agent vẫn "sống" (200), còn `/ready` trả 503 để load balancer tạm tránh instance đó.

### Exercise 5.2: Graceful shutdown

Bản develop: `lifespan` chờ tối đa 30 s cho đến khi `_in_flight_requests == 0`, và `uvicorn.run(..., timeout_graceful_shutdown=30)`. Handler SIGTERM tự viết chỉ ghi log, còn việc tắt an toàn do uvicorn đảm nhận.

Test chạy **trong container Linux** (`python:3.11-slim`) vì Windows không gửi được SIGTERM: gửi `POST /ask` (mock LLM của Part 5 mất khoảng 3 giây), rồi 30 ms sau gửi `kill -TERM`:

```text
agent PID=10
t+30ms: kill -TERM 10
in-flight request -> HTTP 200 {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."} (3043 ms)
agent exit code: 0
----- agent log -----
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Shutting down
INFO:     127.0.0.1:34316 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 08:55:03,358 INFO 🔄 Graceful shutdown initiated...
2026-11-25 08:55:03,358 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [10]
2026-11-25 08:55:03,359 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết luận:** uvicorn in "Shutting down" ngay khi nhận SIGTERM (ngừng nhận request mới), nhưng request đang chạy vẫn hoàn thành với **200 sau 3043 ms**, rồi process thoát với **exit code 0**.
*Chi tiết đáng chú ý:* dòng log của handler tự viết (`Received signal 15`) xuất hiện **cuối cùng**. uvicorn tạm thay các signal handler bằng handler của chính nó; khi shutdown xong mới khôi phục handler cũ và phát lại tín hiệu. Vì thế handler tự viết không được chặn hoặc tự `exit` sớm, nếu không sẽ phá cơ chế này.

### Exercise 5.3: Stateless design

State trong RAM (`conversation_history = {}`) chỉ tồn tại trong một process. Khi có 3 instance sau load balancer, request 1 có thể vào instance A còn request 2 vào instance B, và B không thấy history mà A đã lưu. Restart instance thì cũng mất luôn. Bản production lưu session vào Redis (`session:<id>`, `SETEX` TTL 1 giờ), nên instance nào cũng đọc được cùng một history.
(Bản production tự quay về dict trong RAM nếu không kết nối được Redis lúc khởi động. Cách này tiện cho demo nhưng ở production thật nên fail rõ ràng thay vì âm thầm mất tính stateless.)

### Exercise 5.4 + 5.5: Load balancing và test stateless

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 17 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 17 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 16 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 16 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 27 seconds (healthy)   6379/tcp

$ python test_stateless.py
Session ID: 5e82aeaf-5e8a-460b-8b1f-6bfc4cf843ff
Request 1: [instance-1b6276]  Q: What is Docker?
Request 2: [instance-3b0035]  Q: Why do we need containers?
Request 3: [instance-1b6276]  Q: What is Kubernetes?
Request 4: [instance-7fa170]  Q: How does load balancing work?
Request 5: [instance-3b0035]  Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-1b6276', 'instance-7fa170', 'instance-3b0035'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** Nginx (`server agent:8000` + `resolver 127.0.0.11`) phân phối 5 request của **cùng một session** cho cả **3 instance khác nhau**. History vẫn đủ 10 tin nhắn (5 hỏi + 5 trả lời), vì không instance nào giữ state trong RAM: tất cả cùng đọc và ghi key `session:<id>` trong Redis.

**Thí nghiệm thêm (script không tự làm):** tắt hẳn một instance rồi chat tiếp trong cùng session:

```text
$ docker stop k5-day14-scaling-agent-1
turn=7 served_by=instance-7fa170
turn=8 served_by=instance-3b0035
turn=9 served_by=instance-7fa170
Total messages: 16
```

Sau khi `agent-1` chết, 2 instance còn lại tiếp tục phục vụ, không mất history (8 lượt hỏi đáp = 16 tin nhắn). Chi tiết nhỏ: field `turn` bị lệch 1 (câu thứ 6 hiển thị `turn=7`), vì code đếm số câu hỏi **sau khi** đã thêm câu hiện tại vào history rồi còn cộng thêm 1.

---

## Part 6: Final Project — output `check_production_ready.py`

Chạy đầy đủ (có Docker) **trên Linux**: container `python:3.11-slim` có docker CLI, mount cả repo, dùng Docker daemon của máy, chạy `cd 06-lab-complete && python check_production_ready.py`.

```text
python: 3.11.18 posix  docker: 29.10.1
🔎 Kiểm tra /repo/06-lab-complete

✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Docker: build image thành công — 1s
     ✅ Docker: image < 500 MB — 238 MB
     ✅ Docker: container chạy được, GET /health → 200
✅ 7. Rate limiting
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429
✅ 11. Graceful shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 0.9s

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 41/41 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Trên Windows (Python Windows), cùng code đó cho kết quả `11/12 · 40/40 checks`: tiêu chí 11 chỉ ⚠️ vì "Windows không gửi được SIGTERM" (phần `docker stop` vẫn ✅, exit code 0 sau 0,8 s).

---

## AI log

Theo `RULES.md` mục 1. Mình dùng **Claude Code (model Claude Opus 5.5)** trong VS Code cho các việc dưới đây:

| Hỏi / nhờ gì | Nhận được gì | Đã kiểm tra thế nào |
|---|---|---|
| Đọc các file md của đề, tổng hợp mục đích, checkpoint, lưu ý | File hướng dẫn tổng hợp (không nộp) | Đối chiếu lại với `CHECKPOINTS.md`, `RUBRIC.md`, `SUBMISSION.md` |
| Chạy lần lượt CP1–CP5, CP7, CP8 trên máy và lưu output | Các output, bảng và số đo trong file này và trong `BENCHMARK_REPORT.md` | Số liệu lấy trực tiếp từ output lệnh, file JSON/CSV trong `reports/` và `benchmark-results/`. Đã đối chiếu từng con số |
| Viết code Part 6 (`app/*.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`) | Code hoàn chỉnh cho 12 tiêu chí | `check_production_ready.py` bản đầy đủ trên Linux: **PASS 12/12 · 41/41**. Test tay bằng `docker compose`: 401 / 422 / 200 / 429 + `Retry-After`, tắt Redis thì `/ready` 503 còn `/health` 200, log toàn JSON |
| Exercise 7.1, 7.3: thêm metric `agent_question_length_chars`, sửa `KNOWLEDGE_BASE`, viết job CI | Code + `.github/workflows/eval.yml` | `/metrics` có histogram mới. Eval cuối 23/23, 0 regression. Đã kiểm từ khoá mới chỉ khớp đúng 2 câu cần sửa |
| Sửa Dockerfile của stack Part 7 (agent crash `ModuleNotFoundError: uvicorn`) | Thêm `ENV PYTHONUSERBASE=/home/agent/.local` | Agent khởi động, Prometheus thấy target `up`, Locust chạy được |

Mọi đoạn code trong `06-lab-complete/app/` đều có comment giải thích lý do.

