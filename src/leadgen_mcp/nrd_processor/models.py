"""SQLite schema and helpers for the NRD bulk processor.

Uses the SAME database file (data/leadgen.db) but SEPARATE tables
prefixed with nrd_ to avoid any collision with the main pipeline.
"""

NRD_SCHEMA_SQL = """
-- Active leads: domains WITH registrant email (actionable)
CREATE TABLE IF NOT EXISTS nrd_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    tld TEXT NOT NULL,
    registered_date TEXT NOT NULL,
    whois_data TEXT,          -- JSON blob of full WHOIS response
    registrant_email TEXT NOT NULL,
    registrant_name TEXT,
    registrant_org TEXT,
    registrar TEXT,
    creation_date TEXT,
    expiry_date TEXT,
    nameservers TEXT,         -- JSON array
    score INTEGER DEFAULT 0,
    score_reasons TEXT,       -- JSON array of scoring reasons
    email_generated INTEGER DEFAULT 0,
    email_sent INTEGER DEFAULT 0,
    email_subject TEXT,
    telegram_sent INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(domain)
);

CREATE INDEX IF NOT EXISTS idx_nrd_domains_date ON nrd_domains(registered_date);
CREATE INDEX IF NOT EXISTS idx_nrd_domains_score ON nrd_domains(score);
CREATE INDEX IF NOT EXISTS idx_nrd_domains_tld ON nrd_domains(tld);
CREATE INDEX IF NOT EXISTS idx_nrd_domains_email_sent ON nrd_domains(email_sent);

-- Staging table: all domains before WHOIS (temporary holding)
CREATE TABLE IF NOT EXISTS nrd_staging (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    tld TEXT NOT NULL,
    registered_date TEXT NOT NULL,
    processed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(domain)
);

CREATE INDEX IF NOT EXISTS idx_nrd_staging_processed ON nrd_staging(processed);

-- Reference table: domains WITHOUT email or privacy-protected (no action, just reference)
CREATE TABLE IF NOT EXISTS nrd_domains_ref (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    tld TEXT NOT NULL,
    registered_date TEXT NOT NULL,
    registrant_email TEXT,
    registrar TEXT,
    nameservers TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(domain)
);

CREATE TABLE IF NOT EXISTS nrd_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    total_domains INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    whois_done INTEGER DEFAULT 0,
    scored_count INTEGER DEFAULT 0,
    emailed_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',   -- pending | in_progress | done | error
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nrd_progress_status ON nrd_progress(status);
CREATE INDEX IF NOT EXISTS idx_nrd_progress_date ON nrd_progress(date);
"""
