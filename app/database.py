import sqlite3
import pandas as pd
from app.config import settings


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> int:
    df = pd.read_csv(settings.csv_path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sales'"
        ).fetchone()[0]

        if existing:
            count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            if count == len(df):
                return count

        df.to_sql("sales", conn, if_exists="replace", index=False)
        return len(df)


def get_schema() -> str:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sales'"
        ).fetchall()
        return rows[0][0] if rows else ""


def execute_query(sql: str) -> tuple[list[str], list[list]]:
    with get_connection() as conn:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description]
        rows = [list(row) for row in cursor.fetchall()]
        return columns, rows
