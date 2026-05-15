from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://ollama:11434"
    sql_model: str = "gemma3:4b"
    nl_model: str = "qwen2.5-coder:1.5b"
    db_path: str = "/app/data/sales.db"
    csv_path: str = "/app/data/data.csv"
    max_retries: int = 3

    class Config:
        env_file = ".env"


settings = Settings()
