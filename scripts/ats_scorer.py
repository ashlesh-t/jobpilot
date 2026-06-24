"""ATS scorer (Layer B helper).

Scores one job description against the parsed resume profile:
  final = 0.6 * semantic + 0.4 * keyword

Semantic uses sentence-transformers all-MiniLM-L6-v2 (small, fast, local). If the library or
model is unavailable, it degrades gracefully to a token-overlap proxy so the pipeline never
hard-fails. Results are cached in SQLite score_cache keyed on (job_id, resume_hash).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

FILTERED_IN = "/tmp/jobpilot_filtered.json"
_STOP = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "have", "this", "that",
    "from", "they", "their", "who", "what", "all", "can", "but", "not", "job", "role", "work",
    "team", "experience", "years", "year", "ability", "strong", "good", "plus", "etc",
}
_MODEL = None


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def db_path() -> Path:
    return jobpilot_dir() / "cache" / "jobs.sqlite"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def tokens(text: str) -> set:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-]{1,}", (text or "").lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


def get_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as exc:  # noqa: BLE001
        print(f"[ats] sentence-transformers unavailable ({exc}); using token proxy.",
              file=sys.stderr)
        _MODEL = False
    return _MODEL


def semantic_similarity(a: str, b: str) -> float:
    model = get_model()
    if model:
        try:
            import numpy as np

            emb = model.encode([a, b], normalize_embeddings=True)
            sim = float(np.dot(emb[0], emb[1]))
            return max(0.0, min(1.0, sim))
        except Exception as exc:  # noqa: BLE001
            print(f"[ats] embedding failed ({exc}); using token proxy.", file=sys.stderr)
    # Fallback: Jaccard token overlap as a rough semantic proxy
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def profile_text(profile: dict) -> str:
    parts = []
    parts.extend(profile.get("skills", []))
    parts.extend(profile.get("roles_held", []))
    for p in profile.get("projects", []):
        parts.append(p if isinstance(p, str) else json.dumps(p))
    edu = profile.get("education", {})
    if isinstance(edu, dict):
        parts.extend(str(v) for v in edu.values())
    return " ".join(str(p) for p in parts if p)


def score_job(job: dict, profile: dict) -> dict:
    jd = job.get("jd_full", "") or ""
    jd_lower = jd.lower()
    resume_txt = profile_text(profile)
    profile_skills = [s for s in profile.get("skills", []) if s]

    jd_tokens = tokens(jd)
    skill_tokens = {s.lower() for s in profile_skills}

    matched = sorted({s for s in profile_skills if s.lower() in jd_lower})
    # Important JD terms the resume lacks (top by appearance, minus stopwords/skills)
    missing = sorted(jd_tokens - skill_tokens)[:15]

    total_jd_keywords = max(len(jd_tokens), 1)
    keyword_score = min(100.0, (len(matched) / total_jd_keywords) * 100 * 5)
    # (scaled x5 since a JD has many more tokens than a resume lists skills)

    semantic_score = semantic_similarity(jd, resume_txt) * 100
    final = round(0.6 * semantic_score + 0.4 * keyword_score, 1)

    suggested = [f"Add '{kw}' to your skills or a bullet" for kw in missing[:5]]

    why = (
        f"Semantic fit {semantic_score:.0f}/100 and {len(matched)} matched skills "
        f"give a {final:.0f}/100 overall match for {job.get('role', 'this role')}."
    )

    return {
        "score": final,
        "keyword_score": round(keyword_score, 1),
        "semantic_score": round(semantic_score, 1),
        "matched_keywords": matched,
        "missing_keywords": missing,
        "suggested_additions": suggested,
        "why": why,
    }


def cached_score(conn, job_id: str, resume_hash: str):
    try:
        row = conn.execute(
            "SELECT score_json FROM score_cache WHERE job_id=? AND resume_hash=?",
            (job_id, resume_hash),
        ).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def cache_score(conn, job_id: str, resume_hash: str, result: dict) -> None:
    try:
        conn.execute(
            "INSERT OR REPLACE INTO score_cache (job_id, resume_hash, score_json, computed_at) "
            "VALUES (?,?,?,?)",
            (job_id, resume_hash, json.dumps(result),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[ats] cache write failed: {exc}", file=sys.stderr)


def find_job(job_id: str) -> dict | None:
    for job in load_json(FILTERED_IN, []):
        if job.get("job_id") == job_id:
            return job
    return None


def score_by_id(job_id: str) -> dict:
    prefs = load_json(jobpilot_dir() / "options" / "preferences.json", {})
    profile = load_json(jobpilot_dir() / "cache" / "profile.json", {})
    resume_hash = prefs.get("resume_hash", "")

    conn = None
    if db_path().exists():
        conn = sqlite3.connect(str(db_path()))
        cached = cached_score(conn, job_id, resume_hash)
        if cached:
            conn.close()
            return cached

    job = find_job(job_id)
    if not job:
        if conn:
            conn.close()
        return {"error": f"job_id {job_id} not found in {FILTERED_IN}"}

    result = score_job(job, profile)
    if conn:
        cache_score(conn, job_id, resume_hash, result)
        conn.close()
    return result


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 ats_scorer.py <job_id>", file=sys.stderr)
        sys.exit(1)
    result = score_by_id(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
