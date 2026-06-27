CREATE TABLE IF NOT EXISTS jobs_seen (
  job_id TEXT PRIMARY KEY,
  company TEXT,
  role TEXT,
  location TEXT,
  source TEXT,
  match_score REAL,
  resume_hash TEXT,
  first_seen TEXT,
  last_seen TEXT,
  tailored_resume_path TEXT,
  status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS score_cache (
  job_id TEXT,
  resume_hash TEXT,
  score_json TEXT,
  computed_at TEXT,
  PRIMARY KEY (job_id, resume_hash)
);

CREATE TABLE IF NOT EXISTS user_feedback (
  job_id TEXT PRIMARY KEY,
  status TEXT,
  notes TEXT,
  feedback_date TEXT,
  FOREIGN KEY (job_id) REFERENCES jobs_seen(job_id)
);

CREATE TABLE IF NOT EXISTS url_security_cache (
  url_hash     TEXT PRIMARY KEY,   -- SHA256(url)[:32]
  url          TEXT NOT NULL,
  risk_score   INTEGER DEFAULT 0,
  risk_label   TEXT DEFAULT 'unknown', -- safe | suspicious | dangerous
  is_allowlist INTEGER DEFAULT 0,
  final_url    TEXT,
  redirect_hops TEXT,              -- JSON array of intermediate URLs
  threats      TEXT,               -- JSON array of matched threat names
  checked_at   TEXT,
  expires_at   TEXT                -- ISO datetime; re-check after expiry
);
