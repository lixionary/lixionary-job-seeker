from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://mongo:27017"
    mongo_db: str = "job_radar"
    config_dir: str = "/app/config"

    llm_base_url: str = "https://api.minimax.io/v1"
    llm_api_key: str = ""
    llm_model: str = "MiniMax-M1"
    llm_tailor_model: str = "MiniMax-M1"
    max_llm_scores_per_run: int = 50

    apify_token: str = ""
    serpapi_key: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    dashboard_public_url: str = "http://mini-pc-2.fluffy-oratrice.ts.net:3000"
    tz: str = "Asia/Jakarta"

    @property
    def resolved_config_dir(self) -> Path:
        p = Path(self.config_dir)
        if p.exists():
            return p
        fallback = Path(__file__).resolve().parents[2] / "config"
        return fallback

    @property
    def llm_enabled(self) -> bool:
        key = (self.llm_api_key or "").strip()
        return bool(key and not key.startswith("your_"))


settings = Settings()
