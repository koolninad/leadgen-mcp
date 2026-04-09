"""SQLite schema definitions and initialization."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    domain TEXT,
    company_name TEXT,
    source_platform TEXT,
    source_url TEXT,
    description TEXT,
    budget_estimate INTEGER,
    signals TEXT,  -- JSON array
    raw_data TEXT, -- JSON object
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(domain);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source_platform);

CREATE TABLE IF NOT EXISTS scan_results (
    id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(id),
    scan_type TEXT NOT NULL,  -- tech_stack, performance, security, accessibility, features
    result TEXT NOT NULL,     -- JSON object
    severity TEXT,            -- critical, warning, good
    scanned_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scans_lead ON scan_results(lead_id);

CREATE TABLE IF NOT EXISTS contacts (
    id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(id),
    name TEXT,
    title TEXT,
    email TEXT,
    email_verified INTEGER DEFAULT 0,
    phone TEXT,
    source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_lead ON contacts(lead_id);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);

CREATE TABLE IF NOT EXISTS lead_scores (
    id TEXT PRIMARY KEY,
    lead_id TEXT UNIQUE REFERENCES leads(id),
    tech_score REAL DEFAULT 0,
    opportunity_score REAL DEFAULT 0,
    budget_score REAL DEFAULT 0,
    engagement_score REAL DEFAULT 0,
    contact_score REAL DEFAULT 0,
    total_score REAL DEFAULT 0,
    scored_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scores_total ON lead_scores(total_score DESC);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'draft',  -- draft, active, paused, completed
    template TEXT,
    schedule TEXT,  -- JSON: delay between steps, send times
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS campaign_leads (
    id TEXT PRIMARY KEY,
    campaign_id TEXT REFERENCES campaigns(id),
    lead_id TEXT REFERENCES leads(id),
    sequence_step INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- pending, sent, opened, clicked, replied, bounced
    next_send_at TEXT,
    sent_at TEXT,
    opened_at TEXT,
    clicked_at TEXT,
    replied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_cl_campaign ON campaign_leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cl_status ON campaign_leads(status);

CREATE TABLE IF NOT EXISTS emails_sent (
    id TEXT PRIMARY KEY,
    campaign_lead_id TEXT REFERENCES campaign_leads(id),
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    tracking_id TEXT UNIQUE,
    sent_at TEXT DEFAULT (datetime('now')),
    opened_at TEXT,
    clicked_at TEXT,
    bounced INTEGER DEFAULT 0,
    bounce_type TEXT  -- hard, soft
);

CREATE INDEX IF NOT EXISTS idx_emails_tracking ON emails_sent(tracking_id);
"""
