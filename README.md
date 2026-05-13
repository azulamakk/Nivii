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

> **Memory:** The default model (`qwen2.5-coder:1.5b`) requires ~1.5 GB RAM. If you have Docker Desktop, make sure it has at least **4 GB of memory** allocated (Settings → Resources → Memory). To use the higher-accuracy 7B model (requires ~5 GB RAM), set `SQL_MODEL=qwen2.5-coder:7b`:

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
│  │   FastAPI · Python │──▶│  Model server       │ │
│  │                    │   │  qwen2.5-coder:1.5b │ │
│  │  • Loads data.csv  │   │  llama3.2:3b        │ │
│  │  • SQLite (embed.) │   └───────────────────┘ │
│  │  • Serves web UI   │                         │
│  │  • /api/query      │                         │
│  └────────────────────┘                         │
└─────────────────────────────────────────────────┘
```

**Request flow:**

1. User submits a question via the web UI.
2. `app` sends the question + table schema to Ollama (`qwen2.5-coder:1.5b` by default) → receives SQL.
3. SQL is validated and executed against embedded SQLite.
4. If execution fails, the error is fed back to the model for up to 3 retry attempts.
5. The SQL result is sent to Ollama (`llama3.2:3b`) → receives a natural-language answer.
6. The UI displays the answer, the generated SQL, and the results table.

**Dataset:** `data.csv` (~24k rows) — POS transaction records with columns:
`date, week_day, hour, ticket_number, waiter, product_name, quantity, unitary_price, total`

---

## Model Choices & Trade-offs

| Role | Model | Size | RAM needed | Why |
|---|---|---|---|---|
| Text-to-SQL (default) | `qwen2.5-coder:1.5b` | ~1 GB | ~1.5 GB | Works on any machine; purpose-built for code generation |
| Text-to-SQL (high accuracy) | `qwen2.5-coder:7b` | ~4.7 GB | ~5 GB | Better SQL for complex queries; set `SQL_MODEL=qwen2.5-coder:7b` |
| NL answer (default) | `qwen2.5-coder:1.5b` | shared | ~0 extra | Reuses the SQL model already in memory — zero extra RAM cost |
| NL answer (dedicated) | `llama3.2:3b` | ~2 GB | ~2 GB | Set `NL_MODEL=llama3.2:3b` on machines with ≥6 GB Docker memory |

**Why `qwen2.5-coder:1.5b` as default?** The assignment requires the system to "run reliably outside your local environment." A 7B model fails on machines with Docker Desktop's default memory allocation (~2-4 GB). The 1.5B model runs comfortably on any modern laptop. Quality is mitigated by:
- Full schema injected into every system prompt.
- Three curated few-shot examples anchor the output format.
- Retry loop (up to 3 attempts) feeds the SQLite error back to the model for self-correction.
- SQL output is stripped of markdown fences before execution.

**Why not SQLCoder-7b-2?** Defog's SQLCoder requires 14 GB of RAM and is extremely slow on CPU — not practical for a take-home demo.

**Why Ollama instead of in-process HuggingFace?** Ollama handles model loading, GGUF quantization, GPU detection, and a clean REST API out of the box — far less Docker complexity than bundling transformers + CUDA drivers inside the app image.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama server URL |
| `SQL_MODEL` | `qwen2.5-coder:1.5b` | Model used for text-to-SQL |
| `NL_MODEL` | `qwen2.5-coder:1.5b` | Model used for natural-language answers |
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
