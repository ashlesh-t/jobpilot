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
