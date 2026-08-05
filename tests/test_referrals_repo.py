"""core/repo/contacts.py + core/repo/referrals.py — draft-only referral tracking."""
from __future__ import annotations

import pytest

from core.repo import _company_match


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)
    from core import db

    db.dispose()
    db.init_db()
    yield tmp_path
    db.dispose()


@pytest.fixture()
def user_id(store):
    from core.repo import users as users_repo
    return users_repo.create(username="tester", password="testpass123")["id"]


def _seed_job(user_id, job_id="j1", company="Acme Corp"):
    from core.repo import jobs as jobs_repo
    jobs_repo.upsert_scored(user_id, [{
        "job_id": job_id, "company": company, "role": "SWE", "location": "Remote",
        "score": 80, "application_url": "https://x.test",
    }])


# --------------------------------------------------------------------------- #
# Company matching
# --------------------------------------------------------------------------- #
def test_normalize_company_strips_suffixes_and_case():
    assert _company_match.normalize_company("Acme Corp") == "acme"
    assert _company_match.normalize_company("ACME, Inc.") == "acme"
    assert _company_match.normalize_company("  Acme  ") == "acme"


# --------------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------------- #
def test_create_and_get_contact(store, user_id):
    from core.repo import contacts as contacts_repo

    created = contacts_repo.create(user_id, company="Acme Corp", name="Jane HR", email="jane@acme.com")
    assert created["id"]
    fetched = contacts_repo.get(user_id, created["id"])
    assert fetched["name"] == "Jane HR"


def test_for_company_matches_despite_suffix_variance(store, user_id):
    from core.repo import contacts as contacts_repo

    contacts_repo.create(user_id, company="Acme Corp", name="Jane HR", email="jane@acme.com")
    matches = contacts_repo.for_company(user_id, "ACME")
    assert len(matches) == 1
    assert matches[0]["name"] == "Jane HR"


def test_for_company_returns_empty_for_no_match(store, user_id):
    from core.repo import contacts as contacts_repo

    contacts_repo.create(user_id, company="Acme Corp", name="Jane HR", email="jane@acme.com")
    assert contacts_repo.for_company(user_id, "Globex") == []


def test_bulk_import_skips_rows_with_no_company_or_email(store, user_id):
    from core.repo import contacts as contacts_repo

    result = contacts_repo.bulk_import(user_id, [
        {"company": "Acme", "name": "A", "email": "a@acme.com", "role": "HR"},
        {"company": "", "name": "B", "email": "", "role": ""},
    ])
    assert result["imported"] == 1
    assert result["skipped"] == 1
    assert contacts_repo.list_all(user_id) and len(contacts_repo.list_all(user_id)) == 1


def test_remove_contact(store, user_id):
    from core.repo import contacts as contacts_repo

    created = contacts_repo.create(user_id, company="Acme", email="a@acme.com")
    assert contacts_repo.remove(user_id, created["id"]) is True
    assert contacts_repo.get(user_id, created["id"]) is None
    assert contacts_repo.remove(user_id, created["id"]) is False


# --------------------------------------------------------------------------- #
# Referrals
# --------------------------------------------------------------------------- #
def test_create_referral_requires_a_real_job_and_contact(store, user_id):
    from core.repo import contacts as contacts_repo
    from core.repo import referrals as referrals_repo

    contact = contacts_repo.create(user_id, company="Acme", email="a@acme.com")
    with pytest.raises(ValueError, match="unknown job_id"):
        referrals_repo.create(user_id, "not-a-job", contact["id"], message="hi")

    _seed_job(user_id)
    with pytest.raises(ValueError, match="unknown contact_id"):
        referrals_repo.create(user_id, "j1", 99999, message="hi")


def test_create_referral_defaults_to_drafted_and_never_sends(store, user_id):
    from core.repo import contacts as contacts_repo
    from core.repo import referrals as referrals_repo

    _seed_job(user_id)
    contact = contacts_repo.create(user_id, company="Acme Corp", name="Jane", email="jane@acme.com")
    referral = referrals_repo.create(user_id, "j1", contact["id"], message="Hi Jane, ...")
    assert referral["status"] == "drafted"
    assert referral["message"] == "Hi Jane, ..."
    assert referral["company"] == "Acme Corp"
    assert referral["contact_name"] == "Jane"


def test_set_status_validates_and_records_history(store, user_id):
    from core.repo import contacts as contacts_repo
    from core.repo import referrals as referrals_repo

    _seed_job(user_id)
    contact = contacts_repo.create(user_id, company="Acme Corp", email="jane@acme.com")
    referral = referrals_repo.create(user_id, "j1", contact["id"], message="hi")

    with pytest.raises(ValueError, match="invalid status"):
        referrals_repo.set_status(user_id, referral["id"], "not-a-status")

    updated = referrals_repo.set_status(user_id, referral["id"], "sent", note="emailed it")
    assert updated["status"] == "sent"
    assert len(updated["status_history"]) == 2
    assert updated["status_history"][-1]["note"] == "emailed it"


def test_for_job_and_list_all(store, user_id):
    from core.repo import contacts as contacts_repo
    from core.repo import referrals as referrals_repo

    _seed_job(user_id)
    contact = contacts_repo.create(user_id, company="Acme Corp", email="jane@acme.com")
    referrals_repo.create(user_id, "j1", contact["id"], message="hi")

    assert len(referrals_repo.for_job(user_id, "j1")) == 1
    assert len(referrals_repo.list_all(user_id)) == 1
    assert len(referrals_repo.list_all(user_id, status="sent")) == 0


def test_deleting_a_job_cascades_its_referrals(store, user_id):
    """job_id FK is ondelete=CASCADE, not unique — a job can have several referral
    drafts, and removing the job must not orphan them."""
    from core.repo import contacts as contacts_repo
    from core.repo import jobs as jobs_repo
    from core.repo import referrals as referrals_repo

    _seed_job(user_id)
    contact = contacts_repo.create(user_id, company="Acme Corp", email="jane@acme.com")
    referral = referrals_repo.create(user_id, "j1", contact["id"], message="hi")

    jobs_repo.delete("j1")
    assert referrals_repo.get(user_id, referral["id"]) is None
