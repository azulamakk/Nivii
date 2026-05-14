#!/usr/bin/env python3
"""
Benchmark text-to-SQL para el proyecto Nivii.
Uso: python3 eval/benchmark.py [modelo1 modelo2 ...]
     python3 eval/benchmark.py  (prueba todos los modelos definidos en MODELS)

Evaluación: para cada pregunta se ejecuta una SQL de referencia contra la base de datos
y se compara con la SQL generada por el modelo. Los resultados se normalizan antes de
comparar (orden, tipos numéricos, mayúsculas).
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

# ── Test suite ─────────────────────────────────────────────────────────────────
# 31 questions: 21 Spanish + 10 English duplicates of selected questions.
# Each entry carries a reference_sql whose result is the ground truth.
# Correctness is determined by comparing (normalised) result sets, not hardcoded values.
TESTS = [
    # ── Simple ──────────────────────────────────────────────────────────────
    {
        "id": "Q1", "difficulty": "simple", "language": "es",
        "question": "¿Cuántos registros hay en total en la base de datos?",
        "reference_sql": "SELECT COUNT(*) FROM sales;",
    },
    {
        "id": "Q1b", "difficulty": "simple", "language": "en",
        "question": "How many records are in the database?",
        "reference_sql": "SELECT COUNT(*) FROM sales;",
    },
    {
        "id": "Q2", "difficulty": "simple", "language": "es",
        "question": "¿Cuántos mozos distintos hay en la base de datos?",
        "reference_sql": "SELECT COUNT(DISTINCT waiter) FROM sales;",
    },
    {
        "id": "Q2b", "difficulty": "simple", "language": "en",
        "question": "How many distinct waiters are there?",
        "reference_sql": "SELECT COUNT(DISTINCT waiter) FROM sales;",
    },
    {
        "id": "Q3", "difficulty": "simple", "language": "es",
        "question": "¿Cuántos productos distintos hay en la base de datos?",
        "reference_sql": "SELECT COUNT(DISTINCT product_name) FROM sales;",
    },
    {
        "id": "Q4", "difficulty": "simple", "language": "es",
        "question": "¿Cuántos tickets únicos hay en la base de datos?",
        "reference_sql": "SELECT COUNT(DISTINCT ticket_number) FROM sales;",
    },
    # ── Medium ───────────────────────────────────────────────────────────────
    {
        "id": "Q5", "difficulty": "medium", "language": "es",
        "question": "¿Cuál es el producto más comprado los viernes?",
        "reference_sql": "SELECT product_name, SUM(quantity) AS total_qty FROM sales WHERE week_day = 'Friday' GROUP BY product_name ORDER BY total_qty DESC LIMIT 1;",
    },
    {
        "id": "Q5b", "difficulty": "medium", "language": "en",
        "question": "What is the most bought product on Fridays?",
        "reference_sql": "SELECT product_name, SUM(quantity) AS total_qty FROM sales WHERE week_day = 'Friday' GROUP BY product_name ORDER BY total_qty DESC LIMIT 1;",
    },
    {
        "id": "Q6", "difficulty": "medium", "language": "es", "order_rows": False,
        "question": "¿Cuáles son los 3 mozos con mayor ingreso total?",
        "reference_sql": "SELECT waiter, SUM(total) AS revenue FROM sales GROUP BY waiter ORDER BY revenue DESC LIMIT 3;",
    },
    {
        "id": "Q6b", "difficulty": "medium", "language": "en", "order_rows": False,
        "question": "Which are the 3 waiters with the highest total revenue?",
        "reference_sql": "SELECT waiter, SUM(total) AS revenue FROM sales GROUP BY waiter ORDER BY revenue DESC LIMIT 3;",
    },
    {
        "id": "Q7", "difficulty": "medium", "language": "es",
        "question": "¿Cuál es el promedio del total de venta por día de la semana?",
        "reference_sql": "SELECT week_day, AVG(total) AS avg_total FROM sales GROUP BY week_day ORDER BY avg_total DESC;",
    },
    {
        "id": "Q7b", "difficulty": "medium", "language": "en",
        "question": "What is the average sale total per day of the week?",
        "reference_sql": "SELECT week_day, AVG(total) AS avg_total FROM sales GROUP BY week_day ORDER BY avg_total DESC;",
    },
    {
        "id": "Q8", "difficulty": "medium", "language": "es",
        "question": "¿Cuál es el producto más vendido en total por cantidad?",
        "reference_sql": "SELECT product_name, SUM(quantity) AS total_qty FROM sales GROUP BY product_name ORDER BY total_qty DESC LIMIT 1;",
    },
    {
        "id": "Q9", "difficulty": "medium", "language": "es",
        "question": "¿Cuál es la hora del día con mayor número de ventas?",
        "reference_sql": "SELECT hour, COUNT(*) AS cnt FROM sales GROUP BY hour ORDER BY cnt DESC LIMIT 1;",
    },
    {
        "id": "Q10", "difficulty": "medium", "language": "es",
        "question": "¿Qué día de la semana genera el mayor ingreso total?",
        "reference_sql": "SELECT week_day, SUM(total) AS revenue FROM sales GROUP BY week_day ORDER BY revenue DESC LIMIT 1;",
    },
    {
        "id": "Q11", "difficulty": "medium", "language": "es", "order_rows": False,
        "question": "¿Cuáles son los 5 productos con mayor ingreso total?",
        "reference_sql": "SELECT product_name, SUM(total) AS revenue FROM sales GROUP BY product_name ORDER BY revenue DESC LIMIT 5;",
    },
    {
        "id": "Q11b", "difficulty": "medium", "language": "en", "order_rows": False,
        "question": "What are the top 5 products by total revenue?",
        "reference_sql": "SELECT product_name, SUM(total) AS revenue FROM sales GROUP BY product_name ORDER BY revenue DESC LIMIT 5;",
    },
    {
        "id": "Q12", "difficulty": "medium", "language": "es",
        "question": "¿Cuál es el ingreso total de todas las ventas?",
        "reference_sql": "SELECT SUM(total) FROM sales;",
    },
    {
        "id": "Q13", "difficulty": "medium", "language": "es",
        "question": "¿Cuál es el mozo que atendió más tickets distintos?",
        "reference_sql": "SELECT waiter, COUNT(DISTINCT ticket_number) AS tickets FROM sales GROUP BY waiter ORDER BY tickets DESC LIMIT 1;",
    },
    {
        "id": "Q14", "difficulty": "medium", "language": "es", "order_rows": False,
        "question": "¿Cuáles son los 3 productos más vendidos los fines de semana (sábado y domingo)?",
        "reference_sql": "SELECT product_name, SUM(quantity) AS total_qty FROM sales WHERE week_day IN ('Saturday', 'Sunday') GROUP BY product_name ORDER BY total_qty DESC LIMIT 3;",
    },
    {
        "id": "Q14b", "difficulty": "medium", "language": "en", "order_rows": False,
        "question": "What are the 3 most sold products on weekends (Saturday and Sunday)?",
        "reference_sql": "SELECT product_name, SUM(quantity) AS total_qty FROM sales WHERE week_day IN ('Saturday', 'Sunday') GROUP BY product_name ORDER BY total_qty DESC LIMIT 3;",
    },
    # ── Hard ─────────────────────────────────────────────────────────────────
    {
        "id": "Q15", "difficulty": "hard", "language": "es",
        "question": "¿Qué productos tienen una cantidad total vendida superior al promedio de ventas por producto?",
        "reference_sql": "SELECT product_name, SUM(quantity) AS total_qty FROM sales GROUP BY product_name HAVING total_qty > (SELECT AVG(qty) FROM (SELECT SUM(quantity) AS qty FROM sales GROUP BY product_name)) ORDER BY total_qty DESC;",
    },
    {
        "id": "Q16", "difficulty": "hard", "language": "es",
        "question": "¿Cuántos productos distintos vendió cada mozo?",
        "reference_sql": "SELECT waiter, COUNT(DISTINCT product_name) AS distinct_products FROM sales GROUP BY waiter ORDER BY waiter;",
    },
    {
        "id": "Q17", "difficulty": "hard", "language": "es",
        "question": "¿Cuál es el mozo con el mayor ingreso promedio por ticket?",
        "reference_sql": "SELECT waiter, AVG(ticket_total) AS avg_per_ticket FROM (SELECT waiter, ticket_number, SUM(total) AS ticket_total FROM sales GROUP BY waiter, ticket_number) GROUP BY waiter ORDER BY avg_per_ticket DESC LIMIT 1;",
    },
    {
        "id": "Q17b", "difficulty": "hard", "language": "en",
        "question": "Which waiter has the highest average revenue per ticket?",
        "reference_sql": "SELECT waiter, AVG(ticket_total) AS avg_per_ticket FROM (SELECT waiter, ticket_number, SUM(total) AS ticket_total FROM sales GROUP BY waiter, ticket_number) GROUP BY waiter ORDER BY avg_per_ticket DESC LIMIT 1;",
    },
    {
        "id": "Q18", "difficulty": "hard", "language": "es",
        "question": "¿En qué mes se registró el mayor ingreso total?",
        "reference_sql": "SELECT CAST(SUBSTR(date, 1, INSTR(date, '/') - 1) AS INTEGER) AS month, SUM(total) AS revenue FROM sales GROUP BY month ORDER BY revenue DESC LIMIT 1;",
    },
    {
        "id": "Q18b", "difficulty": "hard", "language": "en",
        "question": "Which month had the highest total revenue?",
        "reference_sql": "SELECT CAST(SUBSTR(date, 1, INSTR(date, '/') - 1) AS INTEGER) AS month, SUM(total) AS revenue FROM sales GROUP BY month ORDER BY revenue DESC LIMIT 1;",
    },
    {
        "id": "Q19", "difficulty": "hard", "language": "es",
        "question": "¿Cuánto ingreso generó cada mozo en octubre de 2024?",
        "reference_sql": "SELECT waiter, SUM(total) AS revenue FROM sales WHERE date LIKE '10/%/2024' GROUP BY waiter ORDER BY waiter;",
    },
    {
        "id": "Q20", "difficulty": "hard", "language": "es",
        "question": "¿Cuál es la diferencia de ingresos entre el mozo más vendedor y el menos vendedor?",
        "reference_sql": "SELECT MAX(rev) - MIN(rev) FROM (SELECT waiter, SUM(total) AS rev FROM sales GROUP BY waiter);",
    },
    {
        "id": "Q20b", "difficulty": "hard", "language": "en",
        "question": "What is the revenue difference between the highest and lowest earning waiter?",
        "reference_sql": "SELECT MAX(rev) - MIN(rev) FROM (SELECT waiter, SUM(total) AS rev FROM sales GROUP BY waiter);",
    },
    {
        "id": "Q21", "difficulty": "hard", "language": "es", "order_rows": False,
        "question": "¿Cuál es el precio unitario promedio de los productos vendidos por cada mozo, ordenado de mayor a menor?",
        "reference_sql": "SELECT waiter, AVG(unitary_price) AS avg_price FROM sales GROUP BY waiter ORDER BY avg_price DESC;",
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


def results_match(ref_rows: list, llm_rows: list, order_rows: bool = True) -> bool:
    """Compare two result sets as a multiset of value-multisets.

    Column names are dropped entirely (different models alias columns differently:
    `revenue` vs `total_revenue`, `tickets` vs `distinct_tickets`, etc.). Values
    within each row are also sorted, so column order in the SELECT list does not
    affect the result. Numeric values are rounded to 4 decimal places to avoid
    float noise.

    order_rows=True  (default): row order is ignored — both sets are sorted
                                before comparison (set-based equality).
    order_rows=False           : rows are compared positionally; use for
                                 rank-sensitive queries (TOP-N, explicit ORDER BY).
    """
    def norm_val(v) -> str:
        try:
            return str(round(float(v), 4))
        except (TypeError, ValueError):
            return str(v).strip().lower()

    def normalize(rows: list) -> list:
        return [tuple(sorted(norm_val(v) for v in row)) for row in rows]

    ref_norm = normalize(ref_rows)
    llm_norm = normalize(llm_rows)

    if order_rows:
        ref_norm = sorted(ref_norm)
        llm_norm = sorted(llm_norm)

    return ref_norm == llm_norm


def ollama_generate(model: str, prompt: str, num_ctx: int = 4096, think: bool | None = None) -> tuple[str, float]:
    t0 = time.time()
    options: dict = {"num_ctx": num_ctx}
    if think is not None:
        options["think"] = think
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "system": SYSTEM_PROMPT, "stream": False,
              "options": options},
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
            json={"model": model, "prompt": "SELECT 1;", "stream": False,
                  "options": {"num_ctx": 4096}},
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

    print("  Verificando disponibilidad...", end=" ", flush=True)
    if not check_ollama(model):
        print("❌ No disponible (OOM u otro error)")
        return {
            "model": model,
            "status": "unavailable",
            "sql_validity_rate": None,
            "correctness_rate": None,
            "es_correctness_rate": None,
            "en_correctness_rate": None,
            "avg_latency_s": None,
            "avg_retries": None,
            "results": [],
        }
    print("✅")

    # Run all reference SQLs up front to get expected result sets
    ref_results: dict[str, tuple | None] = {}
    for test in TESTS:
        try:
            cols, rows = run_sql(test["reference_sql"])
            ref_results[test["id"]] = (cols, rows)
        except Exception as exc:
            print(f"  ⚠️  Reference SQL failed for {test['id']}: {exc}")
            ref_results[test["id"]] = None

    results = []
    for test in TESTS:
        lang_tag = f"[{test['language'].upper()}]"
        print(f"  {test['id']} {lang_tag} [{test['difficulty']}] {test['question'][:48]}...", end=" ", flush=True)

        ref_result = ref_results[test["id"]]
        order_rows = test.get("order_rows", True)
        sql_valid = False
        correct = False
        retries = 0
        latencies: list[float] = []
        final_sql = ""
        last_error = ""
        prompt = test["question"]
        think = False if model.startswith("qwen3") else None

        for attempt in range(MAX_RETRIES):
            if last_error:
                prompt = (
                    f"{test['question']}\n\n"
                    f"Previous attempt failed with error: {last_error}\n"
                    "Please fix the SQL."
                )
            try:
                raw, latency = ollama_generate(model, prompt, think=think)
                latencies.append(latency)
                sql = clean_sql(raw)
                final_sql = sql

                llm_cols, llm_rows = run_sql(sql)
                sql_valid = True

                if ref_result is not None:
                    _, ref_rows = ref_result
                    correct = results_match(ref_rows, llm_rows, order_rows)
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

        results.append({
            "id": test["id"],
            "difficulty": test["difficulty"],
            "language": test["language"],
            "sql_valid": sql_valid,
            "correct": correct,
            "retries": retries,
            "latency_s": round(avg_lat, 2),
            "sql": final_sql,
        })

    n = len(results)
    valid = sum(1 for r in results if r["sql_valid"])
    corr = sum(1 for r in results if r["correct"])
    tested = [r for r in results if r["latency_s"] > 0]
    avg_lat = sum(r["latency_s"] for r in tested) / len(tested) if tested else 0.0
    avg_ret = sum(r["retries"] for r in results) / n if n else 0.0

    es_res = [r for r, t in zip(results, TESTS) if t["language"] == "es"]
    en_res = [r for r, t in zip(results, TESTS) if t["language"] == "en"]
    es_rate = round(sum(1 for r in es_res if r["correct"]) / len(es_res) * 100, 1) if es_res else None
    en_rate = round(sum(1 for r in en_res if r["correct"]) / len(en_res) * 100, 1) if en_res else None

    summary = {
        "model": model,
        "status": "ok",
        "sql_validity_rate": round(valid / n * 100, 1),
        "correctness_rate": round(corr / n * 100, 1),
        "es_correctness_rate": es_rate,
        "en_correctness_rate": en_rate,
        "avg_latency_s": round(avg_lat, 2),
        "avg_retries": round(avg_ret, 2),
        "results": results,
    }

    print(
        f"\n  SQL válido:   {valid}/{n}  ({summary['sql_validity_rate']}%)\n"
        f"  Correcto:     {corr}/{n}  ({summary['correctness_rate']}%)\n"
        f"  Correcto ES:  {es_rate}%\n"
        f"  Correcto EN:  {en_rate}%\n"
        f"  Latencia avg: {avg_lat:.1f}s\n"
        f"  Reintentos:   {avg_ret:.2f}\n"
    )
    return summary


# ── Entry point ───────────────────────────────────────────────────────────────

MODELS = [
    "qwen2.5-coder:0.5b",
    "qwen2.5-coder:1.5b",
    "qwen2.5:1.5b",
    "llama3.2:1b",
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

    print("\n" + "=" * 84)
    print(f"{'Modelo':<30} {'SQL%':>6} {'OK%':>6} {'ES%':>6} {'EN%':>6} {'Lat(s)':>8} {'Reintentos':>12}")
    print("-" * 84)
    for r in all_results:
        if r["status"] == "unavailable":
            print(f"{r['model']:<30} {'OOM':>6} {'—':>6} {'—':>6} {'—':>6} {'—':>8} {'—':>12}")
        else:
            es = f"{r['es_correctness_rate']:.0f}%" if r["es_correctness_rate"] is not None else "—"
            en = f"{r['en_correctness_rate']:.0f}%" if r["en_correctness_rate"] is not None else "—"
            print(
                f"{r['model']:<30}"
                f" {r['sql_validity_rate']:>5.0f}%"
                f" {r['correctness_rate']:>5.0f}%"
                f" {es:>6}"
                f" {en:>6}"
                f" {r['avg_latency_s']:>7.1f}s"
                f" {r['avg_retries']:>12.2f}"
            )
    print("=" * 84)
