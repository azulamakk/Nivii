import time
import json
import logging
import requests
from app.config import settings

logger = logging.getLogger(__name__)


def wait_for_ollama(timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
            if r.status_code == 200:
                logger.info("Ollama is ready.")
                return
        except requests.exceptions.RequestException:
            pass
        logger.info("Waiting for Ollama...")
        time.sleep(3)
    raise RuntimeError("Ollama did not become ready in time.")


def pull_model(name: str) -> None:
    logger.info(f"Pulling model: {name}")
    with requests.post(
        f"{settings.ollama_base_url}/api/pull",
        json={"name": name},
        stream=True,
        timeout=600,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                status = data.get("status", "")
                if "pulling" in status or status == "success":
                    logger.info(f"[{name}] {status}")
    logger.info(f"Model ready: {name}")


def generate(model: str, prompt: str, system: str = "") -> str:
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    r = requests.post(
        f"{settings.ollama_base_url}/api/generate",
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()
