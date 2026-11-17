"""Configuration loader for the job-search monitor."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"


def _load_dotenv() -> None:
    """Load ROOT/.env if present. Real environment wins over .env, and .env
    wins over yaml values — so systemd Environment= still takes precedence."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # env overrides for secrets, so tokens never need to live in the yaml
    cfg.setdefault("poll_minutes", 30)
    cfg.setdefault("alert_min_score", 40)
    cfg.setdefault("alert_max_messages", 15)
    cfg.setdefault("api", {})
    cfg["api"].setdefault("host", "0.0.0.0")
    cfg["api"].setdefault("port", 8790)
    cfg.setdefault("telegram", {})
    tg = cfg["telegram"]
    tg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", tg.get("bot_token", "") or "")
    tg["chat_id"] = os.environ.get("TELEGRAM_CHAT_ID", str(tg.get("chat_id", "") or ""))
    cfg.setdefault("llm", {})
    cfg["llm"]["api_key"] = os.environ.get(
        "LITELLM_API_KEY", cfg["llm"].get("api_key", "") or "")
    cfg["llm"]["base_url"] = os.environ.get(
        "LITELLM_BASE_URL",
        cfg["llm"].get("base_url", "http://127.0.0.1:4000/v1") or "")
    cfg["llm"]["model"] = os.environ.get(
        "LLM_MODEL", cfg["llm"].get("model", "gpt-4o-mini") or "")
    cfg.setdefault("sources", {})
    cfg.setdefault("scoring", {})
    cfg["scoring"].setdefault("strong", [])
    cfg["scoring"].setdefault("prototype", [])
    cfg["scoring"].setdefault("negative", [])
    cfg["scoring"].setdefault("location_good", [])
    cfg["scoring"].setdefault("location_bad", [])
    cfg.setdefault("weights", {})
    cfg["weights"].setdefault("strong", 8)
    cfg["weights"].setdefault("prototype", 6)
    cfg["weights"].setdefault("negative", -10)
    cfg["weights"].setdefault("location_good", 4)
    cfg["weights"].setdefault("location_bad", -6)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return cfg
