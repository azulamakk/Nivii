import re
import logging
from app.config import settings
from app import ollama_client, database

logger = logging.getLogger(__name__)

_SYSTEM_TEMPLATE = """\
You are an expert SQLite assistant. Given the table schema below, convert the user's \
natural language question into a valid SQLite SELECT query.

Return ONLY the raw SQL query — no explanation, no markdown fences, no extra text.

Schema:
{schema}

Rules:
- The table name is: sales
- Use only valid SQLite syntax
- The "date" column stores values like "10/4/2024" (M/D/YYYY format)
- The "week_day" column stores: Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday
- The "hour" column stores time strings like "14:00"
- Always return a SELECT statement; never modify data

Examples:
  Q: What is the most bought product on Fridays?
  A: SELECT product_name, SUM(quantity) AS total_qty FROM sales WHERE week_day = 'Friday' GROUP BY product_name ORDER BY total_qty DESC LIMIT 1;

  Q: How many unique products are there?
  A: SELECT COUNT(DISTINCT product_name) AS unique_products FROM sales;

  Q: Which waiter made the most sales?
  A: SELECT waiter, SUM(total) AS revenue FROM sales GROUP BY waiter ORDER BY revenue DESC LIMIT 1;
"""


def _clean_sql(raw: str) -> str:
    raw = raw.strip()
    # Strip markdown code fences if the model adds them anyway
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    # Take only the first statement
    raw = raw.split(";")[0].strip() + ";"
    return raw


def text_to_sql(question: str) -> tuple[str, list[str], list[list]]:
    schema = database.get_schema()
    system = _SYSTEM_TEMPLATE.format(schema=schema)

    prompt = question
    last_error: str = ""

    for attempt in range(1, settings.max_retries + 1):
        if last_error:
            prompt = (
                f"{question}\n\n"
                f"Previous attempt produced this SQL:\n{last_sql}\n"
                f"Which failed with error: {last_error}\n"
                f"Please fix the SQL and return only the corrected query."
            )

        raw = ollama_client.generate(settings.sql_model, prompt, system)
        last_sql = _clean_sql(raw)
        logger.info(f"Attempt {attempt} SQL: {last_sql}")

        try:
            columns, rows = database.execute_query(last_sql)
            return last_sql, columns, rows
        except Exception as exc:
            last_error = str(exc)
            logger.warning(f"Attempt {attempt} failed: {last_error}")

    raise ValueError(
        f"Could not generate a valid SQL query after {settings.max_retries} attempts. "
        f"Last error: {last_error}"
    )
