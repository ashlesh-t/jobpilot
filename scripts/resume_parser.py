"""Resume parser.

Reads a base.tex or base.docx resume, extracts structured fields, writes profile.json, and
updates resume_hash in preferences.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

# Common tech skills to detect (extend freely)
SKILL_VOCAB = [
    "python", "java", "javascript", "typescript", "go", "golang", "c++", "c#", "rust", "ruby",
    "kotlin", "scala", "swift", "php", "sql", "nosql", "react", "node", "node.js", "express",
    "django", "flask", "fastapi", "spring", "spring boot", "next.js", "vue", "angular",
    "postgres", "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "kafka", "rabbitmq",
    "docker", "kubernetes", "k8s", "aws", "gcp", "azure", "terraform", "ansible", "jenkins",
    "git", "ci/cd", "graphql", "rest", "grpc", "microservices", "pandas", "numpy", "pytorch",
    "tensorflow", "scikit-learn", "machine learning", "deep learning", "nlp", "llm", "spark",
    "hadoop", "airflow", "tableau", "power bi", "linux", "bash", "html", "css", "tailwind",
]


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def strip_latex(tex: str) -> str:
    text = re.sub(r"%.*", "", tex)                       # comments
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)  # commands + optional args
    text = re.sub(r"[{}\\$&#~^_]", " ", text)             # leftover control chars
    return re.sub(r"\s+", " ", text).strip()


def read_resume_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".tex":
        return strip_latex(path.read_text(errors="ignore"))
    if suffix == ".docx":
        try:
            import docx

            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:  # noqa: BLE001
            print(f"[parser] docx read failed: {exc}", file=sys.stderr)
            return ""
    if suffix == ".pdf":
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception as exc:  # noqa: BLE001
            print(f"[parser] pdf read failed: {exc}", file=sys.stderr)
            return ""
    return path.read_text(errors="ignore")


def extract_email(text: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    return m.group(0) if m else ""


def extract_name(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if 2 <= len(line.split()) <= 4 and line.replace(" ", "").isalpha():
            return line
    return ""


def extract_skills(text: str) -> list:
    low = text.lower()
    found = []
    for skill in SKILL_VOCAB:
        if re.search(r"(?<![a-z])" + re.escape(skill) + r"(?![a-z])", low):
            found.append(skill)
    return sorted(set(found))


def extract_experience_years(text: str) -> int:
    m = re.search(r"(\d+)\+?\s*years?\s+(?:of\s+)?experience", text, re.I)
    if m:
        return int(m.group(1))
    return 0


def extract_education(text: str) -> dict:
    edu = {}
    m = re.search(r"(b\.?\s?tech|b\.?e\.?|m\.?\s?tech|b\.?sc|m\.?sc|mca|bca|ph\.?d)[^\n,]{0,60}",
                  text, re.I)
    if m:
        edu["degree"] = m.group(0).strip()
    m = re.search(r"(20\d{2})", text)
    if m:
        edu["year"] = m.group(1)
    return edu


def parse(path: Path) -> dict:
    text = read_resume_text(path)
    return {
        "name": extract_name(text),
        "email": extract_email(text),
        "skills": extract_skills(text),
        "experience_years": extract_experience_years(text),
        "roles_held": re.findall(
            r"(software engineer|backend developer|full stack developer|data engineer|"
            r"ml engineer|sde|intern|developer)", text, re.I
        )[:10],
        "education": extract_education(text),
        "projects": [
            ln.strip() for ln in text.splitlines()
            if re.search(r"project", ln, re.I) and len(ln.strip()) > 10
        ][:10],
        "publications": [
            ln.strip() for ln in text.splitlines()
            if re.search(r"published|journal|conference|ieee|arxiv", ln, re.I)
        ][:10],
        "hash": file_hash(path),
    }


def update_preferences_hash(resume_hash: str, resume_path: str, drive_file_id: str = "") -> None:
    prefs_path = jobpilot_dir() / "options" / "preferences.json"
    prefs = {}
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text())
        except Exception:
            prefs = {}
    prefs["resume_hash"] = resume_hash
    prefs["resume_path"] = resume_path
    if drive_file_id:
        prefs["resume_drive_file_id"] = drive_file_id
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 resume_parser.py <path> [--drive-file-id <id>]", file=sys.stderr)
        sys.exit(1)
    path = Path(os.path.expanduser(sys.argv[1]))
    if not path.is_file():
        print(f"resume not found: {path}", file=sys.stderr)
        sys.exit(1)

    drive_file_id = ""
    if "--drive-file-id" in sys.argv:
        idx = sys.argv.index("--drive-file-id")
        if idx + 1 < len(sys.argv):
            drive_file_id = sys.argv[idx + 1]

    profile = parse(path)
    out = jobpilot_dir() / "cache" / "profile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False))
    update_preferences_hash(profile["hash"], str(path), drive_file_id)

    print(json.dumps(profile, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
