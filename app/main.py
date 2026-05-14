import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import settings
from app import ollama_client, database
from app.text_to_sql import text_to_sql
from app.nl_response import generate_nl_answer

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Waiting for Ollama...")
    ollama_client.wait_for_ollama()
    logger.info(f"Pulling text-to-SQL model: {settings.sql_model}")
    ollama_client.pull_model(settings.sql_model)
    logger.info(f"Pulling NL response model: {settings.nl_model}")
    ollama_client.pull_model(settings.nl_model)
    logger.info("Loading CSV into database...")
    count = database.init_db()
    logger.info(f"Database ready: {count} rows in 'sales' table.")
    yield


app = FastAPI(title="Nivii SQL Query App", lifespan=lifespan)


class HistoryEntry(BaseModel):
    question: str
    sql: str
    answer: str


class QueryRequest(BaseModel):
    question: str
    history: list[HistoryEntry] = []


@app.get("/api/health")
async def health():
    try:
        with database.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        return {"status": "ok", "db_rows": count}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/schema")
async def schema():
    return {"schema": database.get_schema()}


@app.post("/api/query")
async def query(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        sql, columns, rows = text_to_sql(req.question, history=req.history)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Unexpected error during text-to-SQL: {exc}")
        raise HTTPException(status_code=503, detail="Model service unavailable.")

    answer = generate_nl_answer(req.question, sql, columns, rows)

    return {
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "answer": answer,
        "row_count": len(rows),
    }

