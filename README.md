# Nivii SQL Query Application

A natural-language interface for querying a POS sales database. Type a question in plain English, get back the SQL, the results, and a human-readable answer — all running locally inside Docker.

---

## Quick Start

**Prerequisites:** Docker and Docker Compose (v2+).

```bash
git clone <repo-url>
cd nivii-sql-app
docker compose up --build
```

Then open **http://localhost** in your browser.

> **First run:** The app downloads two Ollama models on startup (~3 GB total). This only happens once; subsequent runs reuse the cached `ollama_data` Docker volume. Startup can take 5–10 minutes depending on your connection.

> **Memory:** The default model (`qwen2.5-coder:1.5b`) requires ~1.2 GB RAM and runs on any modern laptop. If you have Docker Desktop, make sure it has at least **4 GB of memory** allocated (Settings → Resources → Memory). For better English-language accuracy, switch to `llama3.2:3b` (requires ~2 GB RAM / Docker 5 GB):

```bash
SQL_MODEL=llama3.2:3b NL_MODEL=llama3.2:3b docker compose up --build
```

---

## Example Questions

- What is the most bought product on Fridays?
- Which waiter had the highest revenue?
- Top 5 products by total quantity sold?
- Average order value per day of the week?
- How many unique products are there?

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        docker-compose                         │
│                                                              │
│  ┌───────────────────┐   ┌──────────────────┐   ┌─────────┐ │
│  │     frontend      │   │       api        │   │ ollama  │ │
│  │   nginx:alpine    │──▶│ FastAPI · Python │──▶│   LLM   │ │
│  │                   │   │ • /api/query     │   │ server  │ │
│  │ • Serves React SPA│   │ • /api/health    │   └─────────┘ │
│  │ • Proxies /api/*  │   │ • SQLite (embed.)│               │
│  └───────────────────┘   └──────────────────┘               │
│        :80 (public)          (internal only)                 │
└──────────────────────────────────────────────────────────────┘
```

**Request flow:**

1. User submits a question via the web UI.
2. `app` sends the question + table schema to Ollama (`qwen2.5:1.5b`) → receives SQL.
3. SQL is validated and executed against embedded SQLite.
4. If execution fails, the error is fed back to the model for up to 3 retry attempts.
5. The SQL result is sent back to Ollama → receives a natural-language answer.
6. The UI displays the answer, the generated SQL, and the results table.

**Dataset:** `data.csv` (~24k rows) — POS transaction records with columns:
`date, week_day, hour, ticket_number, waiter, product_name, quantity, unitary_price, total`

---

## Model Evaluation

Eight open-source models were benchmarked against a 5-query test suite using three core KPIs: SQL validity rate, answer correctness, and average latency. The evaluation targets a MacBook Air with 8 GB RAM — no GPU required.

Evaluated on a 31-question bilingual suite (21 ES + 10 EN) across three difficulty tiers (simple, medium, hard).

| Model | SQL valid | Correct | ES% | EN% | Latency | Docker RAM |
|---|---|---|---|---|---|---|
| **`qwen2.5-coder:1.5b`** ← default | **100%** | **64.5%** | 67% | 60% | 1.5 s | 4 GB |
| `gemma3:4b` ← if Docker ≥ 5 GB | **100%** | **74.2%** | **71%** | **80%** | 3.1 s | 5 GB† |
| `llama3.2:3b` | 100% | 64.5% | 62% | 70% | 2.4 s | 5 GB |
| `qwen2.5:1.5b` | 100% | 54.8% | 62% | 40% | 1.6 s | 4 GB |
| `llama3.2:1b` | 97% | 41.9% | 33% | 60% | 1.6 s | 4 GB |
| `gemma2:2b` | 94% | 38.7% | 33% | 50% | 2.8 s | 4 GB |
| `qwen2.5-coder:0.5b` | 94% | 32.3% | 24% | 50% | 0.7 s | 4 GB |

> † `gemma3:4b` requires the benchmark's `num_ctx=4096` cap (already set in `benchmark.py`). Without it, Ollama pre-allocates KV cache for a 32K token context and OOMs at 5 GB.

**Notable findings:**
- `gemma3:4b` is the top performer at 74.2% overall and 80% EN, with 3.1 s latency — but needs Docker 5 GB. Best choice if you have the memory.
- `qwen2.5-coder:1.5b` remains the default for the standard 4 GB reference hardware.
- Hard questions (subqueries, non-standard date parsing, two-level aggregations) expose the ceiling of small models — even the best model scores only 30% on the hard tier.

For the full methodology, KPI definitions, per-query results, trade-off analysis, and the list of models considered but not evaluated (API-only, HuggingFace-only, and hardware-constrained), see **[decisions.md](decisions.md)** — written in Spanish as required.

The benchmark is reproducible:

```bash
python3 eval/benchmark.py          # all models
python3 eval/benchmark.py qwen2.5:1.5b   # single model
```

---

## Model Configuration

| Role | Default (4 GB Docker) | Best (5 GB Docker) | How to switch |
|---|---|---|---|
| Text-to-SQL | `qwen2.5-coder:1.5b` | `gemma3:4b` | `SQL_MODEL=gemma3:4b docker compose up` |
| NL answer | `qwen2.5-coder:1.5b` | `gemma3:4b` | `NL_MODEL=gemma3:4b docker compose up` |

Both roles share the same model by default, keeping memory usage at ~1.2 GB total.

**Why Ollama instead of in-process HuggingFace?** Ollama handles GGUF quantization, GPU detection, and REST API serving out of the box — no CUDA drivers or `torch` inside the app image.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama server URL |
| `SQL_MODEL` | `qwen2.5:1.5b` | Model used for text-to-SQL |
| `NL_MODEL` | `qwen2.5:1.5b` | Model used for natural-language answers |
| `DB_PATH` | `/app/data/sales.db` | SQLite database file path |
| `CSV_PATH` | `/app/data/data.csv` | Source CSV file path |
| `MAX_RETRIES` | `3` | Max SQL generation retries on error |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/api/health` | Liveness check + row count (routed via nginx) |
| `GET` | `/api/schema` | Returns the SQLite table schema |
| `POST` | `/api/query` | Run a natural-language query |

**POST /api/query**

Request:
```json
{ "question": "What is the most bought product on Fridays?" }
```

Response:
```json
{
  "sql": "SELECT product_name, SUM(quantity) AS total_qty FROM sales WHERE week_day = 'Friday' GROUP BY product_name ORDER BY total_qty DESC LIMIT 1;",
  "columns": ["product_name", "total_qty"],
  "rows": [["Alfajor 70 cacao x un", 312]],
  "answer": "Alfajor 70 cacao x un is the most bought product on Fridays with 312 units sold.",
  "row_count": 1
}
```

---

## Scaling the Architecture

The architecture already separates concerns into three containers (`frontend`, `api`, `ollama`), making each layer independently scalable. Here is how to grow each layer:

### Frontend layer
The `frontend` container is an nginx process serving pre-built static files — it has no state and requires negligible CPU. It already scales horizontally with zero code changes.

**In production, skip the nginx container entirely.** Run `npm run build`, upload `frontend/dist/` to S3, Netlify, Vercel, or CloudFront, and point it at the public API URL. The frontend becomes zero-cost to serve and handles any traffic level without touching the API layer. The nginx container in docker-compose mirrors this separation locally so the deployment model is consistent.

### Database layer
- **Replace SQLite with PostgreSQL.** Use a `postgres` service in docker-compose and swap `sqlite3` for `asyncpg` + `SQLAlchemy`. Connection pooling (e.g. `pgbouncer`) handles concurrent reads efficiently.
- **Add indexes** on high-cardinality query columns (`product_name`, `week_day`, `date`) to keep analytical queries fast as data grows.
- For **multiple tables**, generate a combined schema string (all `CREATE TABLE` statements) and inject it into the SQL prompt — the model handles multi-table JOINs well with context.

### Application layer
- **Horizontal scaling:** Run multiple replicas of the `api` service behind an nginx `upstream` block. All replicas share the same Postgres and Ollama instances.
- **Async queries:** Move the Ollama calls to a task queue (Celery + Redis). The `/api/query` endpoint returns a job ID immediately; a WebSocket or polling endpoint delivers the result. This prevents gateway timeouts under high load.
- **Query result caching:** Cache (question → result) in Redis with a short TTL. Repeated identical questions skip the model entirely.

### Model serving layer
- **Replace Ollama with vLLM or TGI (Text Generation Inference).** Both support batched inference and continuous batching, multiplying throughput 10–50× compared to sequential Ollama requests.
- **GPU autoscaling:** Deploy vLLM on a GPU node group in Kubernetes. Use KEDA to scale replicas based on the Redis queue depth.
- For **very high traffic**, cache the compiled schema embedding and use a vector similarity search (pgvector or Qdrant) to retrieve few-shot examples relevant to the incoming question, improving accuracy without prompt length overhead.

### Observability
- Add structured logging (JSON) and expose Prometheus metrics (`/metrics`) for request latency, model call latency, and retry rates.
- Use Grafana + Loki for dashboards and alerting.
