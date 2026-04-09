"""Configuration management using pydantic-settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:12b"

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "LeadGen Agency"
    smtp_from_email: str = ""

    # Database
    db_path: str = "./data/leadgen.db"

    # Tracking
    tracking_base_url: str = "http://localhost:8899"

    # Rate limits
    max_scan_concurrency: int = 10
    max_platform_concurrency: int = 5
    email_rate_per_minute: int = 2
    email_rate_per_hour: int = 30

    # SearXNG (self-hosted search)
    searxng_url: str = "http://localhost:8888"  # SearXNG instance URL
    searxng_enabled: bool = True
    search_fallback_ddg: bool = True  # Fallback to DuckDuckGo if SearXNG is down

    # Proxy
    http_proxy: str | None = None
    proxy_list_file: str | None = None  # path to file with one proxy per line

    # IPv6 rotation
    ipv6_enabled: bool = False
    ipv6_prefix: str = ""  # e.g., "2001:db8::/48" - your IPv6 subnet
    ipv6_pool_size: int = 100  # how many IPs to rotate through

    # LinkedIn Stealth Browser
    linkedin_email: str = ""
    linkedin_password: str = ""
    linkedin_session_file: str = "./data/linkedin_session.json"  # Save session to avoid re-login
    linkedin_headless: bool = True
    linkedin_slow_mo: int = 500  # milliseconds between actions (human-like)

    # Agency details
    agency_name: str = "Your Agency"
    agency_website: str = "https://your-agency.com"
    agency_phone: str = ""
    agency_address: str = ""

    @property
    def db_dir(self) -> Path:
        return Path(self.db_path).parent


settings = Settings()
