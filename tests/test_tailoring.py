"""Resume tailoring — template validation, output contract, ATS scoring, API."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core import tailoring


def _valid_tex(body: str = "Built APIs in Go and Docker.") -> str:
    template = tailoring.load_template()
    return (
        template
        .replace("{{FULL_NAME}}", "Ada Lovelace")
        .replace("{{CONTACT_LINE}}", "ada@example.com")
        .replace("{{SUMMARY}}", body + " " + "Backend engineer. " * 20)
        .replace("{{SKILLS}}", "Go, Docker, Kubernetes, Kafka")
        .replace("{{EXPERIENCE}}", "\\entry{Engineer}{Acme}{2024--2026}")
        .replace("{{PROJECTS}}", "\\begin{itemize}\\item A thing\\end{itemize}")
        .replace("{{EDUCATION}}", "\\entry{BTech}{IIT}{2026}")
    )


# --------------------------------------------------------------------------- #
# Template
# --------------------------------------------------------------------------- #
def test_shipped_template_is_ats_safe():
    """The template itself must pass everything except the unfilled placeholders."""
    source = tailoring.load_template()
    result = tailoring.validate_tex(source)
    assert len(result.problems) == 1
    assert result.problems[0].startswith("still contains unfilled placeholders")
    assert "{{FULL_NAME}}" in result.problems[0]


def test_template_uses_only_overleaf_safe_packages():
    import re

    source = tailoring.load_template()
    used = set()
    for group in re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}", source):
        used.update(p.strip() for p in group.split(","))
    assert used <= tailoring.ALLOWED_PACKAGES


def test_filled_template_validates():
    assert tailoring.validate_tex(_valid_tex()).ok is True


# --------------------------------------------------------------------------- #
# Validation catches what breaks ATS parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("injected,expected", [
    ("\\begin{tabular}{ll}a&b\\end{tabular}", "tables"),
    ("\\begin{multicols}{2}x\\end{multicols}", "multi-column"),
    ("\\includegraphics{photo.png}", "images"),
    ("\\textcolor{red}{hi}", "coloured text"),
])
def test_validation_rejects_unparseable_constructs(injected, expected):
    result = tailoring.validate_tex(_valid_tex() + injected)
    assert result.ok is False
    assert any(expected in p for p in result.problems)


def test_validation_rejects_exotic_packages():
    source = _valid_tex().replace(
        "\\usepackage{parskip}", "\\usepackage{parskip}\n\\usepackage{fontawesome5}")
    result = tailoring.validate_tex(source)
    assert result.ok is False
    assert any("fontawesome5" in p for p in result.problems)


def test_validation_requires_every_section():
    source = _valid_tex().replace("\\section{Education}", "\\section{Extras}")
    result = tailoring.validate_tex(source)
    assert result.ok is False
    assert any("Education" in p for p in result.problems)


def test_validation_rejects_a_non_document():
    result = tailoring.validate_tex("just some text")
    assert result.ok is False


# --------------------------------------------------------------------------- #
# ATS scoring
# --------------------------------------------------------------------------- #
def test_ats_score_is_the_share_of_asked_for_skills_present():
    assert tailoring.ats_score("I know Go and Docker", ["Go", "Docker"]) == 100.0
    assert tailoring.ats_score("I know Go", ["Go", "Docker", "Kafka", "Rust"]) == 25.0
    assert tailoring.ats_score("anything", []) == 0.0


def test_ats_score_is_case_insensitive():
    assert tailoring.ats_score("kubernetes experience", ["Kubernetes"]) == 100.0


# --------------------------------------------------------------------------- #
# Output contract
# --------------------------------------------------------------------------- #
def test_folder_and_file_naming():
    assert tailoring.resume_basename("ashlesh tiwari") == "Ashlesh_Tiwari_Resume"
    folder = tailoring.folder_for("abc123", "Swiss Re")
    assert folder.name == "abc123-SwissRe"


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)
    from core import db
    db.dispose()
    db.init_db()
    yield tmp_path
    db.dispose()


def test_write_result_produces_the_documented_layout(store):
    from core.repo import jobs as jobs_repo

    jobs_repo.upsert_scored([{"job_id": "abc123", "company": "Swiss Re", "role": "SDE"}])

    record = tailoring.write_result(
        job_id="abc123", company="Swiss Re", full_name="Ada Lovelace",
        tex_source=_valid_tex(), jd_skills=["Go", "Docker", "Rust"],
        base_text="I know Go", engine="claude_code",
    )

    folder = store / "resumes" / "tailored" / "abc123-SwissRe"
    assert (folder / "Ada_Lovelace_Resume.tex").exists()
    assert (folder / "meta.json").exists()

    meta = json.loads((folder / "meta.json").read_text())
    assert meta["job_id"] == "abc123"
    assert meta["ats_before"] == pytest.approx(33.3, abs=0.1)   # 1 of 3
    assert meta["ats_after"] == pytest.approx(66.7, abs=0.1)    # 2 of 3, Rust absent
    assert "Rust" in meta["missing_skills"]

    assert record["folder_name"] == "abc123-SwissRe"
    assert record["has_tex"] is True


def test_write_result_records_validation_problems_without_crashing(store):
    from core.repo import jobs as jobs_repo

    jobs_repo.upsert_scored([{"job_id": "j1", "company": "Acme"}])
    record = tailoring.write_result(
        job_id="j1", company="Acme", full_name="Ada Lovelace",
        tex_source=_valid_tex() + "\\includegraphics{x.png}", jd_skills=["Go"],
    )
    # The .tex is still written — the user can fix it in Overleaf.
    assert record["has_tex"] is True
    assert record["status"] == "warning"
    assert "images" in record["error"]


def test_write_result_is_idempotent_per_job(store):
    from core.repo import jobs as jobs_repo
    from core.repo import tailored as tailored_repo

    jobs_repo.upsert_scored([{"job_id": "j1", "company": "Acme"}])
    first = tailoring.write_result(job_id="j1", company="Acme", full_name="Ada L",
                                   tex_source=_valid_tex(), jd_skills=["Go"])
    second = tailoring.write_result(job_id="j1", company="Acme", full_name="Ada L",
                                    tex_source=_valid_tex(), jd_skills=["Go"])
    assert first["id"] == second["id"]
    assert tailored_repo.count() == 1


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    from core import db
    db.dispose()
    db.init_db()

    import scheduler
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler.scheduler, "shutdown", lambda: None)

    import app as app_module
    with TestClient(app_module.app) as c:
        yield c
    db.dispose()


def _seed_ready(client, tmp_path):
    """A job, an active resume and a profile — the three preconditions for tailoring."""
    import io

    from core.repo import jobs as jobs_repo

    jobs_repo.upsert_scored([{
        "job_id": "j1", "company": "Swiss Re", "role": "Golang Engineer",
        "jd_full": "We need Go, Docker and Kubernetes.",
        "matched_skills": ["Go", "Docker"], "missing_skills": ["Kafka"],
    }])
    client.post("/api/resumes/upload",
                files={"file": ("cv.txt", io.BytesIO(b"Ada Lovelace, Go engineer"),
                                "text/plain")},
                data={"folder": "default", "make_active": "true"})
    client.put("/api/profile", json={"data": {"name": "Ada Lovelace", "skills": ["Go"]},
                                     "verified": True})


def test_tailor_requires_a_job(client):
    assert client.post("/api/tailored/jobs/nope").status_code == 404


def test_tailor_requires_a_profile_and_resume(client):
    from core.repo import jobs as jobs_repo

    jobs_repo.upsert_scored([{"job_id": "j1", "company": "Acme"}])
    r = client.post("/api/tailored/jobs/j1")
    assert r.status_code == 409
    assert "profile" in r.json()["detail"].lower()


def test_tailor_end_to_end_with_a_fake_backend(client, tmp_path, monkeypatch):
    import engines
    from engines.base import RunResult, Usage

    class FakeEngine:
        def available(self):
            return True, ""

        async def run(self, program, run_id, on_event):
            assert "Golang Engineer" in program        # the job reached the prompt
            assert "\\documentclass" in program        # so did the template
            return RunResult(
                ok=True,
                artifacts={"final_text": "```\n" + _valid_tex("Go and Docker work.") + "\n```"},
                usage=Usage(tokens_in=1000, tokens_out=500, model="claude-opus-5",
                            source="metered"),
            )

        async def stop(self):
            pass

    monkeypatch.setattr(engines, "get_engine", lambda *a, **k: FakeEngine())
    _seed_ready(client, tmp_path)

    body = client.post("/api/tailored/jobs/j1").json()
    assert body["folder_name"] == "j1-SwissRe"
    assert body["has_tex"] is True
    assert body["ats_after"] is not None

    listing = client.get("/api/tailored").json()
    assert listing["count"] == 1

    detail = client.get(f"/api/tailored/{body['id']}").json()
    assert any(f["name"].endswith(".tex") for f in detail["files"])

    tex = client.get(f"/api/tailored/{body['id']}/download/tex")
    assert tex.status_code == 200
    assert "\\documentclass" in tex.text

    # Tailoring is metered work — it must show up in the cost ledger.
    from core.repo import cost as cost_repo
    assert cost_repo.summary(window="month")["usd"] > 0

    assert client.delete(f"/api/tailored/{body['id']}").status_code == 200
    assert client.get("/api/tailored").json()["count"] == 0


def test_tailor_reports_a_backend_that_returns_junk(client, tmp_path, monkeypatch):
    import engines
    from engines.base import RunResult

    class Rambling:
        def available(self):
            return True, ""

        async def run(self, program, run_id, on_event):
            return RunResult(ok=True, artifacts={"final_text": "Sure! Here's some advice."})

        async def stop(self):
            pass

    monkeypatch.setattr(engines, "get_engine", lambda *a, **k: Rambling())
    _seed_ready(client, tmp_path)

    r = client.post("/api/tailored/jobs/j1")
    assert r.status_code == 502
    assert "LaTeX" in r.json()["detail"]
