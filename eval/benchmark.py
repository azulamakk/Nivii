#!/usr/bin/env python3
"""
Benchmark text-to-SQL para el proyecto Nivii.
Uso: python3 eval/benchmark.py [modelo1 modelo2 ...]
     python3 eval/benchmark.py  (prueba todos los modelos definidos en MODELS)
"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434"
DB_PATH = str(Path(__file__).parent.parent / "data" / "sales.db")

SCHEMA = """\
CREATE TABLE "sales" (
  "date"          TEXT,
  "week_day"      TEXT,
  "hour"          TEXT,
  "ticket_number" TEXT,
  "waiter"        INTEGER,
  "product_name"  TEXT,
  "quantity"      REAL,
  "unitary_price" INTEGER,
  "total"         INTEGER
)"""

SYSTEM_PROMPT = f"""\
You are an expert SQLite assistant. Given the table schema below, convert the user's \
natural language question into a valid SQLite SELECT query.
Return ONLY the raw SQL query — no explanation, no markdown fences, no extra text.

Schema:
{SCHEMA}

Rules:
- Table name: sales
- Use only valid SQLite syntax
- "date" column format: M/D/YYYY  (e.g. 10/4/2024)
- "week_day" values: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday
- "hour" format: HH:MM

Examples:
  Q: What is the most bought product on Fridays?
  A: SELECT product_name, SUM(quantity) AS total_qty FROM sales WHERE week_day = 'Friday' GROUP BY product_name ORDER BY total_qty DESC LIMIT 1;

  Q: How many rows are in the table?
  A: SELECT COUNT(*) FROM sales;

  Q: Which waiter had the highest total revenue?
  A: SELECT waiter, SUM(total) AS revenue FROM sales GROUP BY waiter ORDER BY revenue DESC LIMIT 1;
"""

# ── Test suite ────────────────────────────────────────────────────────────────
# Five queries covering different SQL patterns, with verifiable ground-truth.
TESTS = [
    {
        "id": "Q1",
        "difficulty": "simple",
        "question": "¿Cuántos registros hay en total en la base de datos?",
        "check": lambda cols, rows: bool(rows) and int(rows[0][0]) == 24212,
        "expected": "24212 filas",
    },
    {
        "id": "Q2",
        "difficulty": "medium",
        "question": "¿Cuál es el producto más comprado los viernes?",
        "check": lambda cols, rows: bool(rows) and "Alfajor Sin Azucar Suelto" in str(rows[0]),
        "expected": "Alfajor Sin Azucar Suelto (850 unidades)",
    },
    {
        "id": "Q3",
        "difficulty": "medium",
        "question": "¿Cuáles son los 3 mozos con mayor ingreso total?",
        "check": lambda cols, rows: len(rows) == 3,
        "expected": "3 filas",
    },
    {
        "id": "Q4",
        "difficulty": "medium",
        "question": "¿Cuál es el promedio del total de venta por día de la semana?",
        "check": lambda cols, rows: len(rows) == 7,
        "expected": "7 grupos (uno por día)",
    },
    {
        "id": "Q5",
        "difficulty": "simple",
        "question": "¿Cuántos mozos distintos hay en la base de datos?",
        "check": lambda cols, rows: bool(rows) and int(rows[0][0]) == 9,
        "expected": "9 mozos",
    },
]

MAX_RETRIES = 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_sql(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.split(";")[0].strip() + ";"
    return raw


def run_sql(sql: str):
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(sql)
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        return cols, rows
    finally:
        conn.close()


def ollama_generate(model: str, prompt: str) -> tuple[str, float]:
    t0 = time.time()
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "system": SYSTEM_PROMPT, "stream": False},
        timeout=180,
    )
    elapsed = time.time() - t0
    r.raise_for_status()
    return r.json().get("response", "").strip(), elapsed


def check_ollama(model: str) -> bool:
    """Verify the model can be loaded (no OOM)."""
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": "SELECT 1;", "stream": False},
            timeout=60,
        )
        data = r.json()
        if "error" in data:
            return False
        return True
    except Exception:
        return False


# ── Core evaluation ───────────────────────────────────────────────────────────

def evaluate_model(model: str) -> dict:
    sep = "=" * 60
    print(f"\n{sep}\nEvaluando: {model}\n{sep}")

    # Quick OOM / availability check
    print("  Verificando disponibilidad...", end=" ", flush=True)
    if not check_ollama(model):
        print("❌ No disponible (OOM u otro error)")
        return {
            "model": model,
            "status": "unavailable",
            "sql_validity_rate": None,
            "correctness_rate": None,
            "avg_latency_s": None,
            "avg_retries": None,
            "results": [],
        }
    print("✅")

    results = []
    for test in TESTS:
        print(f"  {test['id']} [{test['difficulty']}] {test['question'][:50]}...", end=" ", flush=True)

        sql_valid = False
        correct = False
        retries = 0
        latencies: list[float] = []
        final_sql = ""
        last_error = ""
        prompt = test["question"]

        for attempt in range(MAX_RETRIES):
            if last_error:
                prompt = (
                    f"{test['question']}\n\n"
                    f"Previous attempt failed with error: {last_error}\n"
                    "Please fix the SQL."
                )
            try:
                raw, latency = ollama_generate(model, prompt)
                latencies.append(latency)
                sql = clean_sql(raw)
                final_sql = sql

                cols, rows = run_sql(sql)
                sql_valid = True
                correct = test["check"](cols, rows)
                retries = attempt
                break
            except requests.exceptions.HTTPError as exc:
                print(f"\n    HTTP error: {exc}")
                break
            except Exception as exc:
                last_error = str(exc)[:120]
                retries = attempt + 1
                print(f"(retry {attempt + 1})", end=" ", flush=True)

        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        icon = "✅" if correct else ("⚠️ " if sql_valid else "❌")
        print(f"{icon}  {avg_lat:.1f}s")

        results.append(
            {
                "id": test["id"],
                "difficulty": test["difficulty"],
                "sql_valid": sql_valid,
                "correct": correct,
                "retries": retries,
                "latency_s": round(avg_lat, 2),
                "sql": final_sql,
            }
        )

    n = len(results)
    valid = sum(1 for r in results if r["sql_valid"])
    corr = sum(1 for r in results if r["correct"])
    tested = [r for r in results if r["latency_s"] > 0]
    avg_lat = sum(r["latency_s"] for r in tested) / len(tested) if tested else 0.0
    avg_ret = sum(r["retries"] for r in results) / n if n else 0.0

    summary = {
        "model": model,
        "status": "ok",
        "sql_validity_rate": round(valid / n * 100, 1),
        "correctness_rate": round(corr / n * 100, 1),
        "avg_latency_s": round(avg_lat, 2),
        "avg_retries": round(avg_ret, 2),
        "results": results,
    }

    print(
        f"\n  SQL válido:   {valid}/{n}  ({summary['sql_validity_rate']}%)\n"
        f"  Correcto:     {corr}/{n}  ({summary['correctness_rate']}%)\n"
        f"  Latencia avg: {avg_lat:.1f}s\n"
        f"  Reintentos:   {avg_ret:.2f}\n"
    )
    return summary


# ── Entry point ───────────────────────────────────────────────────────────────

MODELS = [
    "qwen2.5-coder:0.5b",
    "qwen2.5-coder:1.5b",
    "llama3.2:1b",
    "gemma2:2b",
    "deepseek-coder:1.3b",
]

if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else MODELS

    all_results = []
    for model in targets:
        result = evaluate_model(model)
        all_results.append(result)

    out_path = Path(__file__).parent / "results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Resultados guardados en {out_path}")

    # Quick summary table
    print("\n" + "=" * 72)
    print(f"{'Modelo':<30} {'SQL%':>6} {'OK%':>6} {'Lat(s)':>8} {'Reintentos':>12}")
    print("-" * 72)
    for r in all_results:
        if r["status"] == "unavailable":
            print(f"{r['model']:<30} {'OOM':>6} {'—':>6} {'—':>8} {'—':>12}")
        else:
            print(
                f"{r['model']:<30}"
                f" {r['sql_validity_rate']:>5.0f}%"
                f" {r['correctness_rate']:>5.0f}%"
                f" {r['avg_latency_s']:>7.1f}s"
                f" {r['avg_retries']:>12.2f}"
            )
    print("=" * 72)
