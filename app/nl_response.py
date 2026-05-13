import logging
from app.config import settings
from app import ollama_client

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a helpful data analyst. Given a user question, the SQL query that was run, "
    "and a sample of the results, write a concise 1-2 sentence natural language answer. "
    "Be specific and include key numbers or names from the results. "
    "Do not repeat the SQL or mention technical details."
)


def generate_nl_answer(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list],
) -> str:
    if not rows:
        return "The query returned no results."

    sample = rows[:10]
    header = " | ".join(columns)
    divider = "-" * len(header)
    body = "\n".join(" | ".join(str(v) for v in row) for row in sample)
    results_text = f"{header}\n{divider}\n{body}"
    if len(rows) > 10:
        results_text += f"\n... ({len(rows)} rows total)"

    prompt = (
        f"Question: {question}\n\n"
        f"SQL Query:\n{sql}\n\n"
        f"Results:\n{results_text}"
    )

    try:
        return ollama_client.generate(settings.nl_model, prompt, _SYSTEM)
    except Exception as exc:
        logger.warning(f"NL response generation failed: {exc}")
        return ""
