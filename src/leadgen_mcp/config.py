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
    database_url: str = ""  # postgresql://user:pass@host:5432/leadgen
    pg_pool_min: int = 2
    pg_pool_max: int = 10

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

    # Telegram notifications
    telegram_bot_token: str = ""
    telegram_group_id: str = ""

    # Listmonk
    listmonk_url: str = "http://localhost:9000"
    listmonk_username: str = "admin"
    listmonk_password: str = ""

    # IMAP Aggregate
    imap_poll_interval: int = 120  # seconds
    imap_accounts_file: str = "./data/imap_accounts.json"

    # Email Warmup
    warmup_enabled: bool = True
    warmup_cycle_hours: float = 4.0
    warmup_seed_accounts: str = ""  # comma-separated seed emails

    # Nubo Mail Server
    nubo_smtp_host: str = "mail.nubo.email"
    nubo_smtp_port: int = 587
    nubo_imap_host: str = "mail.nubo.email"
    nubo_imap_port: int = 993

    # CT Log Monitor
    ctlog_keywords: str = "agency,studio,tech,digital,software,health,finance"

    # Company Registry
    opencorporates_api_key: str = ""
    companies_house_api_key: str = ""

    # Agency details
    agency_name: str = "Your Agency"
    agency_website: str = "https://your-agency.com"
    agency_phone: str = ""
    agency_address: str = ""

    # Verticals
    verticals_config: str = ""  # JSON override, otherwise defaults used

    @property
    def db_dir(self) -> Path:
        return Path(self.db_path).parent

    @property
    def warmup_seeds(self) -> list[str]:
        if not self.warmup_seed_accounts:
            return []
        return [s.strip() for s in self.warmup_seed_accounts.split(",") if s.strip()]

    @property
    def ctlog_keyword_list(self) -> list[str]:
        return [k.strip() for k in self.ctlog_keywords.split(",") if k.strip()]

    @property
    def verticals(self) -> dict[str, list[str]]:
        if self.verticals_config:
            import json
            return json.loads(self.verticals_config)
        return {
            "hostingduty": ["hosting", "domain", "server", "vps", "cloud", "website", "ssl", "dns"],
            "chandorkar": ["software", "development", "app", "web", "mobile", "custom", "developer", "freelance"],
            "nubo": ["email", "mail", "storage", "backup", "smtp", "deliverability"],
            "vikasit": ["ai", "ml", "model", "llm", "cli", "automation", "machine learning"],
            "setara": ["document", "blockchain", "verification", "notary", "contract", "legal"],
            "staff_aug": ["hiring", "developer", "engineer", "team", "augmentation", "recruit", "talent"],
        }


settings = Settings()
