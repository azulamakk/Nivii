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

Then open **http://localhost:8000** in your browser.

> **First run:** The app downloads two Ollama models on startup (~3 GB total). This only happens once; subsequent runs reuse the cached `ollama_data` Docker volume. Startup can take 5–10 minutes depending on your connection.

> **Memory:** The default model (`qwen2.5:1.5b`) requires ~1.2 GB RAM and runs on any modern laptop. If you have Docker Desktop, make sure it has at least **4 GB of memory** allocated (Settings → Resources → Memory). To use a higher-accuracy 7B model (requires ~5 GB RAM), set `SQL_MODEL=qwen2.5-coder:7b`:

```bash
SQL_MODEL=qwen2.5-coder:7b docker compose up --build
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
┌─────────────────────────────────────────────────┐
│                  docker-compose                  │
│                                                 │
│  ┌────────────────────┐   ┌───────────────────┐ │
│  │   app (monolith)   │   │      ollama       │ │
│  │   FastAPI · Python │──▶│  Model server     │ │
│  │                    │   │  qwen2.5:1.5b     │ │
│  │  • Loads data.csv  │   │  (text-to-SQL +   │ │
│  │  • SQLite (embed.) │   │   NL answer)      │ │
│  │  • SQLite (embed.) │   └───────────────────┘ │
│  │  • Serves web UI   │                         │
│  │  • /api/query      │                         │
│  └────────────────────┘                         │
└─────────────────────────────────────────────────┘
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

| Model | SQL valid | Correct | Latency | RAM |
|---|---|---|---|---|
| **`qwen2.5:1.5b`** ← default | **100%** | **100%** | **2.5 s** | ~1.2 GB |
| `qwen2.5-coder:1.5b` | 100% | 80% | 2.4 s | ~1.2 GB |
| `llama3.2:1b` | 100% | 60% | 1.9 s | ~1.5 GB |
| `qwen2.5-coder:0.5b` | 100% | 60% | 0.9 s | ~0.5 GB |
| `deepseek-coder:1.3b` | 60% | 60% | 3.8 s | ~1.0 GB |
| `gemma2:2b`, `llama3.2:3b`, `qwen2.5-coder:7b` | OOM† | — | — | 2.5–5 GB |

> † OOM in the constrained test environment (Docker 2.4 GB). `gemma2:2b` and `llama3.2:3b` should run on a standard 8 GB machine; `qwen2.5-coder:7b` requires ≥ 16 GB RAM.

**Notable finding:** `qwen2.5:1.5b` (general instruct) outperformed `qwen2.5-coder:1.5b` (code-specialized) — 100% vs 80% correctness. The code fine-tuning appears to reduce flexibility on natural-language grouping queries. The base instruct model was therefore chosen as the default.

For the full methodology, KPI definitions, per-query results, trade-off analysis, and the list of models considered but not evaluated (API-only, HuggingFace-only, and hardware-constrained), see **[decisions.md](decisions.md)** — written in Spanish as required.

The benchmark is reproducible:

```bash
python3 eval/benchmark.py          # all models
python3 eval/benchmark.py qwen2.5:1.5b   # single model
```

---

## Model Configuration

| Role | Default | Alternative | How to switch |
|---|---|---|---|
| Text-to-SQL | `qwen2.5:1.5b` | `qwen2.5-coder:7b` | `SQL_MODEL=qwen2.5-coder:7b docker compose up` |
| NL answer | `qwen2.5:1.5b` | `llama3.2:3b` | `NL_MODEL=llama3.2:3b docker compose up` |

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
| `GET` | `/api/health` | Liveness check + row count |
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

The current setup is intentionally simple (SQLite + single container). Here is how to scale it for more tables, higher traffic, or larger models:

### Database layer
- **Replace SQLite with PostgreSQL.** Use a `postgres` service in docker-compose and swap `sqlite3` for `asyncpg` + `SQLAlchemy`. Connection pooling (e.g. `pgbouncer`) handles concurrent reads efficiently.
- **Add indexes** on high-cardinality query columns (`product_name`, `week_day`, `date`) to keep analytical queries fast as data grows.
- For **multiple tables**, generate a combined schema string (all `CREATE TABLE` statements) and inject it into the SQL prompt — the model handles multi-table JOINs well with context.

### Application layer
- **Horizontal scaling:** Run multiple replicas of the `app` service behind an nginx reverse proxy (`nginx:alpine` + `upstream` block). All replicas share the same Postgres and Ollama.
- **Async queries:** Move the Ollama calls to a task queue (Celery + Redis). The `/api/query` endpoint returns a job ID immediately; a WebSocket or polling endpoint delivers the result. This prevents gateway timeouts under high load.
- **Query result caching:** Cache (question → result) in Redis with a short TTL. Repeated identical questions skip the model entirely.

### Model serving layer
- **Replace Ollama with vLLM or TGI (Text Generation Inference).** Both support batched inference and continuous batching, multiplying throughput 10–50× compared to sequential Ollama requests.
- **GPU autoscaling:** Deploy vLLM on a GPU node group in Kubernetes. Use KEDA to scale replicas based on the Redis queue depth.
- For **very high traffic**, cache the compiled schema embedding and use a vector similarity search (pgvector or Qdrant) to retrieve few-shot examples relevant to the incoming question, improving accuracy without prompt length overhead.

### Observability
- Add structured logging (JSON) and expose Prometheus metrics (`/metrics`) for request latency, model call latency, and retry rates.
- Use Grafana + Loki for dashboards and alerting.
