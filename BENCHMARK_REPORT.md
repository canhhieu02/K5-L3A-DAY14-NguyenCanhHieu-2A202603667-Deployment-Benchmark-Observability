# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ `reports/*.json` (load_test.py, run_eval.py), `benchmark-results/*_stats.csv` (Locust) và Prometheus/Jaeger của stack đang chạy, không ước lượng.

**Họ tên:** Nguyễn Cảnh Hiếu
**Ngày chạy:** 25/11/2026
**Môi trường:** Laptop Windows 11, Intel Core i5-10300H (4 nhân / 8 luồng), RAM 16 GB; Docker Desktop 29.9.3 (VM 8 CPU / 7,7 GB RAM). Bước 1 chạy agent bằng Python 3.12 trên Windows; Bước 2 chạy stack Docker Compose (agent giới hạn 0,5 CPU / 256 MB mỗi container).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Request thường mất khoảng 200 ms (LLM khoảng 120–180 ms + retrieval khoảng 20 ms), nên 500 ms còn dư hơn 2 lần cho jitter và hàng đợi. Đặt theo p95 vì trung bình che mất tail latency (xem mục 2.2). Alert production đặt lỏng hơn (p95 > 1 s trong 2 phút) để tránh báo động vì spike ngắn |
| Error rate `/ask` | < 2 % | Upstream LLM (mock) có sẵn khoảng 1% lỗi (`MOCK_ERROR_RATE=0.01`), nên SLO 2% chừa error budget 1% cho lỗi của chính mình. Alert chỉ bắn khi > 5% kéo dài 1 phút |
| Accuracy trên golden dataset | ≥ 85 % (và không regression) | Dùng làm quality gate trong CI (`--min-accuracy 0.85`): v1 (4,3%) bị chặn, v2 (91,3%) qua được. Kèm điều kiện **0 regression** so với baseline để sửa câu này không làm hỏng câu khác |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.26 | 202.5 | 236.6 | 1682.8 | 0.67 % | ✅ PASS |
| 10 | 37.14 | 197.4 | 501.0 | 1703.4 | 0.33 % | ❌ FAIL (p95 501 > 500) |
| 50 | 92.65 | 207.8 | 554.0 | 1784.2 | 1.33 % | ❌ FAIL (p95) |
| 100 | 42.95 | 745.4 | 4499.7 | 4762.7 | 1.00 % | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS **không** tăng tuyến tính.
- Từ 1 lên 10: RPS tăng 8,7 lần (4,26 → 37,14) trong khi p50 gần như không đổi (khoảng 200 ms). Agent là async, phần lớn thời gian là `await` chờ LLM, nên một process phục vụ song song được nhiều request. Số liệu khớp với định luật Little: RPS ≈ concurrency / latency (1 / 0,236 s ≈ 4,2 req/s).
- Từ 10 lên 50: RPS chỉ tăng 2,5 lần (lẽ ra 5 lần), p95 vượt 500 ms. CPU bắt đầu là nút thắt: agent chỉ có **1 process uvicorn**, nên mọi việc tốn CPU (parse JSON, ghi log JSON, cập nhật metric) dồn vào 1 nhân. Thêm vào đó, `load_test.py` chạy trên cùng máy và tranh CPU với agent.
- Lên 100: RPS **giảm** còn 43 và p50 nhảy lên 745 ms, p95 lên 4,5 s. Server đã bão hoà: request xếp hàng chờ event loop, và thời gian chờ trong hàng đợi trở thành phần lớn của latency. Thêm concurrency lúc này chỉ làm hàng đợi dài thêm.
- p99 ở mọi mức đều khoảng 1,7 s: đó là khoảng 3% request "chậm bất thường" của mock LLM (`MOCK_SLOW_RATE=0.03`, +1500 ms), không phụ thuộc tải.

### 2.2 Tail latency (agent v2, `--requests 300 --concurrency 20`, khởi động lại agent mỗi lần)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 226.7 | 489.1 | 524.2 |
| 0.03 (mặc định) | 293.3 | 1648.4 | 1716.5 |
| 0.1 | 347.1 | 1682.9 | 1725.8 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** **p99 nhạy nhất**: từ 0 lên 0.03, p99 tăng **3,3 lần** (524 → 1717 ms) trong khi **avg chỉ tăng 29%** (227 → 293 ms). Ở lần chạy này p95 cũng vọt lên 1648 ms. Với 300 mẫu, p95 là "request chậm thứ 15", nên chỉ cần khoảng 5% request rơi vào nhóm chậm là p95 đổi hẳn sang nhóm đó. Điều này cho thấy p95/p99 phản ánh trực tiếp trải nghiệm của nhóm người dùng tệ nhất. Average thì "pha loãng" vài request 1,7 s vào hàng trăm request 0,2 s: con số 293 ms trông vẫn ổn, trong khi cứ 100 người thì có vài người phải chờ gần 2 giây. Vì vậy **SLO phải đặt theo p95/p99**, không đặt theo average: average có thể đạt SLO ngay cả khi một nhóm người dùng đang có trải nghiệm rất tệ.
(Hệ quả phụ: tail latency kéo RPS giảm từ 85,19 xuống 55,92 rồi 46,43 req/s, vì mỗi "slot" concurrency bị giữ lâu hơn.)

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`, 23 câu golden dataset)

Agent chạy với `MOCK_ERROR_RATE=0` để kết quả eval ổn định (theo TROUBLESHOOTING).

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100.0 % (23/23) |
| Avg tokens / câu | 56.4 | 109.1 | 113.9 |
| Tổng cost (USD) | 0.000394 | 0.000762 | 0.000793 |
| Cost / câu đúng (USD) | 0.00039435 | 0.00003627 | 0.00003448 |
| Quality gate | FAIL (gate 80%) | PASS (gate 80%, 0 regression so với v1) | PASS (gate **100%**, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `eval_v2.json`, `eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách sửa:**

| ID | Keyword bị thiếu | Đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Retrieval không tìm được tài liệu nào nên mock trả câu chung chung. Đã thêm vào `KNOWLEDGE_BASE` entry từ khoá `["jwt", "api key"]`: *"API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn…"* |
| scaling-03 ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry từ khoá `["hpa", "kubernetes", "autoscal"]`: *"Kubernetes HPA … dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi."* |

Trước khi thêm, mình đã kiểm tra các từ khoá mới trên toàn bộ 23 câu hỏi: `jwt` và `api key` chỉ khớp security-02, `hpa` và `kubernetes` chỉ khớp scaling-03. Nhờ vậy entry mới không "giành" retrieval của câu khác, và eval xác nhận **0 regression**. Không sửa `golden_dataset.jsonl`.

**Quality gate dùng để chặn merge:** `run_eval.py` trả **exit code 1** khi accuracy < `--min-accuracy` hoặc có regression so với `--baseline`. Thử chạy v1 với `--baseline reports/eval_v2.json` thì gate báo **❌ FAIL, 20 câu regression, exit code 1**. Job `.github/workflows/eval.yml` chạy lệnh eval trong mỗi Pull Request. Exit code 1 làm step fail, job fail; nếu bật branch protection "Require status checks to pass" cho `main` thì PR làm giảm chất lượng **không merge được**.

**Trade-off chất lượng / chi phí / latency giữa v1 và v2:** v2 thêm bước retrieval nên prompt dài gần gấp đôi (109 so với 56 token/câu): tổng cost tăng 1,9 lần và p95 eval tăng khoảng 38 ms (196,6 → 234,4 ms). Đổi lại, accuracy tăng từ 4,3% lên 91,3%. Tính theo **cost / câu đúng**, v2 **rẻ hơn v1 khoảng 10,9 lần** (0,0000363 so với 0,000394 USD). Câu trả lời sai thì rẻ đến đâu cũng là tiền mất, nên đây là chỉ số đúng để so hai phiên bản. Sửa KB thêm 4,4% token nhưng đưa accuracy lên 100%, và cost/câu đúng còn giảm tiếp.

---

## 4. Observability stack (production)

Stack: `docker compose -p k5-day14-observability up -d --build` (agent × 1→3, Nginx, Prometheus, Grafana, Jaeger, Locust). Tải nền: Locust headless 30 user.
*Lưu ý:* Dockerfile agent có sẵn bị lỗi `ModuleNotFoundError: No module named 'uvicorn'`, vì user `agent` có `HOME=/app` nên Python tìm package ở `/app/.local`. Đã sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): `screenshots/grafana-dashboard.png`
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (span lỗi 503, event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với **2 alert cùng firing** (`AgentHighErrorRate`, `AgentHighLatencyP95`): `screenshots/prometheus-alert-firing.png`
- [x] (Thêm) Dashboard 30 phút bao trọn các thí nghiệm A→E: `screenshots/grafana-experiments-A-E.png`

**Trả lời Exercise 7.4** (số lấy từ Prometheus lúc 10:10:58 UTC, 3 instance, tải 30 user):
1. p95 = **293 ms**, avg = **231 ms**, p99 = **1818 ms**. p95 chỉ cao hơn avg khoảng 60 ms, nên phần lớn request đều đặn, nhưng p99 gấp 8 lần avg: khoảng 3% request chậm bất thường (tail latency) nằm ở đó, và avg không cho thấy điều này.
2. Panel "Requests/s theo instance": **6,20 / 6,16 / 6,13 req/s**, tức Nginx chia gần như đều (round-robin qua Docker DNS `server agent:8000 resolve`).
3. Input tokens/s (**1424**) gần gấp đôi output (**747**), vì prompt gồm system prompt + **tài liệu retrieval** + câu hỏi, còn câu trả lời ngắn. Với RAG, input luôn là phần lớn số token.
4. `curl http://localhost:8080/metrics` trả **404**: Nginx chặn `/metrics` từ bên ngoài. Metrics là thông tin nội bộ (lộ cấu trúc hệ thống, số request, chi phí) và chỉ Prometheus được scrape trực tiếp `agent:8000/metrics` qua mạng nội bộ.

### 4.2 Thí nghiệm "phá hệ thống"

Cách đo: ghi T0 ngay trước `docker compose up -d` với `.env` mới, rồi một script hỏi `GET /api/v1/alerts` của Prometheus mỗi 5 giây và ghi thời điểm từng alert đổi trạng thái. A và B làm **cùng lúc** để có ảnh 2 alert firing.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (tỉ lệ lỗi đo được 19–20%) | **89 s** (pending ở 29 s, cộng `for: 1m`) | Error rate (đỏ), "Requests/s theo status code" (đường 503 tăng), "LLM calls theo kết quả" (error) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (p95 ≈ 1,9 s) | **149 s** (pending ở 29 s, cộng `for: 2m`) | "Latency /ask — p50/p95/p99": p95 nhảy lên khoảng 1,9 s, avg tăng ít hơn nhiều |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | **145 s** (pending ở 25 s, cộng `for: 2m`) | "Cost burn rate": từ khoảng $2,4 lên **$16,1/giờ**; "LLM latency p95 theo model" (khoảng 2 s); p95 `/ask` 293 → 681 ms |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (172.20.0.5) | **41 s** (pending ở 11 s, cộng `for: 30s`) | "Instances up" 3 → 2; "Requests/s theo instance" (1 đường rơi về 0). Panel Error rate **vẫn xanh (1,26%)**, trong khi Nginx ghi **6 lỗi 502/504** `upstream timed out` |
| E | `AGENT_VERSION=v1` | **Không có** | — | Bảng "Phiên bản đang chạy" đổi sang v1; Tokens/s giảm khoảng một nửa (input 1419 → 690/s); cost/giờ giảm; p95 còn **giảm** (292 → 198 ms) |

**Quan sát thêm:**
- Mỗi lần `docker compose up -d` tạo lại 3 container agent, `AgentInstanceDown` chuyển sang **pending** vài giây rồi tự về inactive mà **không firing**. Đây là tác dụng của `for: 30s`: không báo động giả trong lúc rolling restart. Nếu đặt `for: 0s` thì mỗi lần deploy đều có cảnh báo (alert fatigue); nếu đặt `for: 30m` thì sự cố thật phải nửa giờ sau mới biết.
- `LLMCostBurnRateHigh` **đã firing từ trước thí nghiệm C**, ngay trong lúc benchmark scaling 100 user (10:04:42, khoảng $4,3/giờ). Với model nhỏ, tải lớn cũng đủ vượt $2/giờ, nên ngưỡng cost alert phải đặt theo tải dự kiến.
- D giải thích vì sao lỗi 504 không có trên dashboard: lỗi xảy ra ở Nginx (`proxy_read_timeout 10s`), request chưa bao giờ được agent xử lý xong nên metric của agent không đếm. Muốn thấy loại lỗi này phải giám sát ở tầng load balancer hoặc dùng synthetic check từ bên ngoài.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đổi sang v1 làm accuracy rơi từ 100% xuống 4,3% (mục 3), nhưng mọi metric hạ tầng lại **đẹp hơn**: nhanh hơn, rẻ hơn, ít token hơn. Metrics chỉ trả lời "hệ thống có chạy không", không trả lời "câu trả lời có đúng không". Cách phát hiện:
1. **Chặn trước khi deploy:** quality gate eval trong CI/CD (job `eval.yml`), không cho bản có regression lên production.
2. **Eval liên tục trên production:** chạy golden dataset định kỳ (vd mỗi 15 phút) vào endpoint thật, xuất accuracy thành metric `agent_eval_accuracy` và alert khi nó < 85%.
3. **Chấm mẫu traffic thật:** lấy mẫu khoảng 1–5% câu hỏi thật, chấm bằng LLM-as-judge hoặc semantic similarity.
4. **Proxy metric chất lượng:** retrieval hit ratio, tỉ lệ câu trả lời "chung chung", độ dài câu trả lời, feedback 👍/👎 của người dùng, và alert khi chúng lệch khỏi baseline.
5. **Alert khi `agent_info{version}` đổi ngoài lịch deploy:** đổi version mà không qua pipeline là dấu hiệu bất thường.

### 4.3 Debug bằng trace

Trace chậm nhất tìm được (Jaeger API v3, lọc `duration_min=1s`, lấy span dài nhất):

- `trace_id`: `40d3875ba46d26025abbb8fdb5240a24`
- Tổng thời gian: **2540,3 ms** (`POST /ask`, instance `a1be3c175920`, lúc benchmark 1 instance × 100 user)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`: 1647,8 ms (64,9%)**, `gen_ai.usage.input_tokens=76`, `output_tokens=39`
- Các span khác: `agent.run` 1742,6 ms (68,6%), `agent.retrieve_context` 94,7 ms (3,7%).
- Còn khoảng **798 ms (31%) nằm ngoài `agent.run`**: thời gian request chờ trong hàng đợi của server (1 instance bị giới hạn 0,5 CPU đang chịu 100 user). Vậy trace này chậm vì 2 lý do: LLM chậm bất thường (tail latency của upstream) và server quá tải. Lý do thứ hai biến mất khi scale lên 3 instance (mục 5).
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 40d3875ba46d26025abbb8fdb5240a24`):

```json
{"ts": "2026-11-25T10:04:48.579055+00:00", "level": "INFO", "service": "observable-agent", "instance": "a1be3c175920", "event": "llm_call", "trace_id": "40d3875ba46d26025abbb8fdb5240a24", "span_id": "db5f6a681de66c63", "request_id": "066b6657f84c", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1647.1}
{"ts": "2026-11-25T10:04:48.579750+00:00", "level": "INFO", "service": "observable-agent", "instance": "a1be3c175920", "event": "http_request", "trace_id": "40d3875ba46d26025abbb8fdb5240a24", "span_id": "db5f6a681de66c63", "request_id": "066b6657f84c", "method": "POST", "route": "/ask", "status": 200, "ms": 2539.7}
```

Trace lỗi (`screenshots/jaeger-error-trace.png`): `trace_id` `768967574794eb1bf6a28d25709e4039`, 96,3 ms, `POST /ask` → 503. Span `chat mock-llm-small` có `error.type=upstream_unavailable` và event `exception` (`utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`). Log khớp:

```json
{"ts": "2026-11-25T10:11:44.363411+00:00", "level": "INFO", "service": "observable-agent", "instance": "bdf3c20b05be", "event": "llm_error", "trace_id": "768967574794eb1bf6a28d25709e4039", "span_id": "ac375ac148deae49", "request_id": "f3b025136ff8", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

(Lưu ý nhỏ: sự kiện `llm_error` được log ở level `INFO`. Nên dùng `ERROR` để lọc lỗi theo level được.)

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút, endpoint `POST /ask`)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 58.39 | 200 | 590 | 1700 | 80 / 6934 (1,15 %) |
| 3 | 59.70 | 200 | 240 | 1700 | 76 / 7104 (1,07 %) |

Nguồn: `benchmark-results/scale_1_stats.csv`, `scale_3_stats.csv` (dòng `/ask`).
*Lưu ý khi chạy:* `docker compose run locust` mặc định khởi động luôn các dependency, và vì compose khai báo `replicas: 2` nên nó **tự bật thêm agent-2** khi đang ở `--scale agent=1`. Mình dùng `run --no-deps` và kiểm tra số container agent (1 rồi 3) ngay trước mỗi lần chạy để số liệu "1 instance" là đúng 1 instance.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?
- **p95 cải thiện rõ: 590 → 240 ms.** Với 1 instance (giới hạn 0,5 CPU), mỗi đợt request dồn lại phải xếp hàng. 3 instance chia tải nên hàng đợi gần như biến mất, p95 về sát p50.
- **RPS gần như không đổi (58 so với 60).** Locust là mô hình "closed-loop": 100 user, mỗi user nghỉ 0,5–2 s (trung bình 1,25 s) giữa các request. Trần lý thuyết khoảng 100 / (1,25 + 0,25) ≈ 66 req/s tổng, và số đo được là 64,5 và 65,8 req/s (kể cả `/health`). Vậy RPS bị giới hạn bởi **bên tạo tải**, không phải bởi server; muốn thấy RPS tăng khi scale thì phải tăng số user.
- **p99 không đổi (1700 ms).** Đó là khoảng 3% request mà **chính LLM upstream** chậm thêm 1,5 s (`MOCK_SLOW_RATE`), thấy rõ trên panel "LLM latency" và trong trace mục 4.3. Scale ngang chỉ giải quyết được throughput và hàng đợi, không làm một lần gọi LLM nhanh hơn. Muốn giảm tail này phải xử lý ở dependency: timeout + retry/hedging, cache câu trả lời, model nhanh hơn hoặc streaming.
- **Failures khoảng 1%** ở cả hai lần, đúng bằng `MOCK_ERROR_RATE=0.01` của upstream, không liên quan đến số instance.

---

## 6. Kết luận

- 3 điều học được về benchmark và observability:
  1. **Trung bình nói dối, percentile thì không:** avg 293 ms trông ổn trong khi p99 1,7 s. SLO, dashboard và alert đều phải theo p95/p99; và khi số mẫu nhỏ, p95 rất nhạy, phải đọc cùng số mẫu.
  2. **Metrics hạ tầng không đo được chất lượng:** đổi sang v1 làm accuracy giảm từ 100% xuống 4,3% mà mọi panel còn "đẹp" hơn. Eval trên golden dataset, với chỉ số cost / câu đúng và quality gate trong CI, là một trụ cột riêng, bắt buộc phải có với hệ thống LLM.
  3. **Ba trụ cột phải liên kết với nhau:** dashboard báo p95 tăng → Jaeger chỉ ra span LLM chiếm 65% và 31% là thời gian xếp hàng → `trace_id` dẫn tới đúng dòng log JSON. Đồng thời, metric chỉ phản ánh những gì chính service đó thấy: lỗi 504 ở Nginx (thí nghiệm D) không xuất hiện trên dashboard của agent.
- Nếu đưa agent này lên production thật, mình sẽ thêm:
  - Metric và alert **chất lượng**: `agent_eval_accuracy` từ eval định kỳ, retrieval hit ratio, tỉ lệ 👎 của người dùng.
  - Giám sát **tầng Nginx/LB** (tỉ lệ 502/504, upstream response time) và **synthetic check** từ bên ngoài (gọi `/ask` mỗi phút từ một region khác).
  - Alert **cost theo ngân sách ngày** (dự báo chạm `DAILY_BUDGET_USD` trong 2 giờ tới) thay vì một ngưỡng $/giờ cố định, vì ngưỡng cố định đã firing ngay khi tải lớn với model nhỏ.
  - Alert **saturation** (`agent_in_flight_requests` cao kéo dài, CPU throttling của container) để scale trước khi p95 vỡ SLO.
  - Đổi log `llm_error` sang level `ERROR`, thêm Alertmanager để gửi cảnh báo qua Slack/PagerDuty, và chỉ trace một phần request (head sampling khoảng 10%, luôn giữ trace lỗi và trace chậm) khi traffic lớn.
