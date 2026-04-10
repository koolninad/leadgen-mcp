"""PostgreSQL schema DDL for leadgen-mcp.

All tables: original 7 + NRD 4 + new 4 (sender_accounts, warmup_log, reply_inbox, crawler_runs).
"""

SCHEMA_SQL = """
-- ============================================================
-- CORE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    domain TEXT,
    company_name TEXT,
    source_platform TEXT,
    source_url TEXT,
    description TEXT,
    budget_estimate INTEGER,
    signals JSONB DEFAULT '[]'::jsonb,
    raw_data JSONB DEFAULT '{}'::jsonb,
    vertical_match TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source_platform);
CREATE INDEX IF NOT EXISTS idx_leads_vertical ON leads USING gin(vertical_match);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at DESC);

CREATE TABLE IF NOT EXISTS scan_results (
    id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(id) ON DELETE CASCADE,
    scan_type TEXT NOT NULL,
    result JSONB NOT NULL,
    severity TEXT,
    scanned_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scans_lead ON scan_results(lead_id);
CREATE INDEX IF NOT EXISTS idx_scans_type ON scan_results(scan_type);

CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(id) ON DELETE CASCADE,
    name TEXT,
    title TEXT,
    email TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    phone TEXT,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_lead ON contacts(lead_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);

CREATE TABLE IF NOT EXISTS lead_scores (
    id TEXT PRIMARY KEY,
    lead_id TEXT UNIQUE REFERENCES leads(id) ON DELETE CASCADE,
    tech_score REAL DEFAULT 0,
    opportunity_score REAL DEFAULT 0,
    budget_score REAL DEFAULT 0,
    engagement_score REAL DEFAULT 0,
    contact_score REAL DEFAULT 0,
    total_score REAL DEFAULT 0,
    scored_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scores_total ON lead_scores(total_score DESC);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    template TEXT,
    schedule JSONB,
    listmonk_campaign_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS campaign_leads (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id TEXT REFERENCES leads(id) ON DELETE CASCADE,
    sequence_step INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    next_send_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    opened_at TIMESTAMPTZ,
    clicked_at TIMESTAMPTZ,
    replied_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cl_campaign ON campaign_leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cl_status ON campaign_leads(status);

CREATE TABLE IF NOT EXISTS emails_sent (
    id TEXT PRIMARY KEY,
    campaign_lead_id TEXT REFERENCES campaign_leads(id),
    to_email TEXT NOT NULL,
    from_email TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    tracking_id TEXT UNIQUE,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    opened_at TIMESTAMPTZ,
    clicked_at TIMESTAMPTZ,
    bounced BOOLEAN DEFAULT FALSE,
    bounce_type TEXT
);

CREATE INDEX IF NOT EXISTS idx_emails_tracking ON emails_sent(tracking_id);
CREATE INDEX IF NOT EXISTS idx_emails_from ON emails_sent(from_email);

-- ============================================================
-- NRD TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS nrd_staging (
    id SERIAL PRIMARY KEY,
    domain TEXT NOT NULL UNIQUE,
    tld TEXT NOT NULL,
    registered_date TEXT NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nrd_domains (
    id SERIAL PRIMARY KEY,
    domain TEXT NOT NULL UNIQUE,
    tld TEXT NOT NULL,
    registered_date TEXT NOT NULL,
    whois_data JSONB,
    registrant_email TEXT,
    registrant_name TEXT,
    registrant_org TEXT,
    registrar TEXT,
    creation_date TEXT,
    expiry_date TEXT,
    nameservers JSONB,
    score INTEGER DEFAULT 0,
    score_reasons JSONB,
    email_generated BOOLEAN DEFAULT FALSE,
    email_sent BOOLEAN DEFAULT FALSE,
    email_subject TEXT,
    telegram_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nrd_domain ON nrd_domains(domain);
CREATE INDEX IF NOT EXISTS idx_nrd_score ON nrd_domains(score);
CREATE INDEX IF NOT EXISTS idx_nrd_tld ON nrd_domains(tld);

CREATE TABLE IF NOT EXISTS nrd_domains_ref (
    id SERIAL PRIMARY KEY,
    domain TEXT NOT NULL UNIQUE,
    tld TEXT NOT NULL,
    registered_date TEXT NOT NULL,
    registrant_email TEXT,
    registrar TEXT,
    nameservers JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nrd_progress (
    id SERIAL PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    total_domains INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    whois_done INTEGER DEFAULT 0,
    scored_count INTEGER DEFAULT 0,
    emailed_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- NEW TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS sender_accounts (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    display_name TEXT NOT NULL,
    smtp_host TEXT NOT NULL DEFAULT 'mail.nubo.email',
    smtp_port INTEGER NOT NULL DEFAULT 587,
    smtp_user TEXT NOT NULL,
    smtp_password TEXT NOT NULL,
    imap_host TEXT DEFAULT 'mail.nubo.email',
    imap_port INTEGER DEFAULT 993,
    pool TEXT NOT NULL DEFAULT 'warming',
    warmup_day INTEGER DEFAULT 0,
    daily_quota INTEGER DEFAULT 3,
    sent_today INTEGER DEFAULT 0,
    sent_total INTEGER DEFAULT 0,
    last_sent_at TIMESTAMPTZ,
    reputation_score REAL DEFAULT 50.0,
    bounce_rate REAL DEFAULT 0.0,
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sender_pool ON sender_accounts(pool);
CREATE INDEX IF NOT EXISTS idx_sender_domain ON sender_accounts(domain);

CREATE TABLE IF NOT EXISTS warmup_log (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES sender_accounts(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    result TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_warmup_account ON warmup_log(account_id);
CREATE INDEX IF NOT EXISTS idx_warmup_created ON warmup_log(created_at DESC);

CREATE TABLE IF NOT EXISTS reply_inbox (
    id SERIAL PRIMARY KEY,
    from_email TEXT NOT NULL,
    to_account TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    lead_id TEXT REFERENCES leads(id),
    message_id TEXT,
    is_auto_reply BOOLEAN DEFAULT FALSE,
    is_bounce BOOLEAN DEFAULT FALSE,
    is_unsubscribe BOOLEAN DEFAULT FALSE,
    forwarded_to_telegram BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reply_msgid ON reply_inbox(message_id);
CREATE INDEX IF NOT EXISTS idx_reply_from ON reply_inbox(from_email);
CREATE INDEX IF NOT EXISTS idx_reply_lead ON reply_inbox(lead_id);

CREATE TABLE IF NOT EXISTS crawler_runs (
    id SERIAL PRIMARY KEY,
    crawler_name TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    leads_found INTEGER DEFAULT 0,
    error_message TEXT,
    config JSONB,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_crawler_name ON crawler_runs(crawler_name);
CREATE INDEX IF NOT EXISTS idx_crawler_started ON crawler_runs(started_at DESC);
"""


async def create_schema(pool) -> None:
    """Execute schema DDL against a PostgreSQL connection pool."""
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
