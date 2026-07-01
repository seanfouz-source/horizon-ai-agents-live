from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env.local")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Horizon AI Agent Hub"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    metricool_api_token: str | None = None
    metricool_blog_id: int | None = None
    metricool_user_id: int | None = None
    metricool_brand_label: str = "Horizon Wireless"
    manychat_api_token: str | None = None
    webhook_shared_secret: str | None = None
    ebay_access_token: str | None = None
    ebay_marketplace_id: str = "EBAY_US"
    ebay_store_url: str = "https://www.ebay.com/str/exactspec"
    ebay_store_backup_url: str | None = "https://ebay.us/m/GDmaKw"
    ebay_store_max_pages: int = 3
    sync_store_page_on_startup: bool = True
    seed_inventory_csv: Path | None = BASE_DIR / "data" / "exactspec_public_store.csv"
    public_base_url: str = "https://horizon-ai-agents.onrender.com"
    database_path: Path = BASE_DIR / "data" / "horizon_agents.db"
    report_email_to: str = "sean.fouz@gmail.com,horizonwirelesstx@gmail.com"
    report_email_provider: str = "smtp"
    report_email_from: str | None = None
    report_email_from_name: str = "Horizon AI Agents"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_username: str | None = None
    smtp_password: str | None = None
    gmail_sender: str | None = None
    gmail_client_credentials_file: Path | None = None
    gmail_refresh_token_current: str | None = None

    @property
    def resolved_database_path(self) -> Path:
        if self.database_path.is_absolute():
            return self.database_path
        return BASE_DIR / self.database_path


@lru_cache
def get_settings() -> Settings:
    return Settings()
