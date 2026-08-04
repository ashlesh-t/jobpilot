"""Contacts repository — HR/recruiter contacts imported from a spreadsheet or added
by hand, matched to jobs by (normalized) company name."""
from __future__ import annotations

from sqlalchemy import func, select

from ._company_match import normalize_company
from ..db import session_scope
from ..models import Contact


def to_dict(c: Contact) -> dict:
    return {
        "id": c.id,
        "company": c.company,
        "name": c.name,
        "email": c.email,
        "role": c.role,
        "source": c.source,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def create(*, company: str, name: str = "", email: str = "", role: str = "",
          source: str = "manual") -> dict:
    with session_scope() as s:
        row = Contact(company=company.strip(), name=name.strip(), email=email.strip(),
                      role=role.strip(), source=source)
        s.add(row)
        s.flush()
        return to_dict(row)


def bulk_import(rows: list[dict]) -> dict:
    """Rows already parsed from CSV/XLSX by the route — case-insensitive keys expected:
    company, name, email, role. Skips rows with no company and no email (nothing to
    match or contact)."""
    imported = 0
    skipped = 0
    errors: list[str] = []
    with session_scope() as s:
        for i, raw in enumerate(rows):
            row = {k.strip().lower(): (v or "").strip() if isinstance(v, str) else v
                  for k, v in raw.items()}
            company = str(row.get("company", "") or "")
            email = str(row.get("email", "") or "")
            if not company and not email:
                skipped += 1
                continue
            try:
                s.add(Contact(
                    company=company,
                    name=str(row.get("name", "") or ""),
                    email=email,
                    role=str(row.get("role", "") or ""),
                    source="import",
                ))
                imported += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"row {i + 1}: {exc}")
                skipped += 1
    return {"imported": imported, "skipped": skipped, "errors": errors}


def list_all(*, company: str | None = None, limit: int = 500) -> list[dict]:
    with session_scope() as s:
        stmt = select(Contact)
        if company:
            stmt = stmt.where(func.lower(Contact.company) == company.lower())
        rows = s.scalars(stmt.order_by(Contact.company).limit(limit)).all()
        return [to_dict(c) for c in rows]


def for_company(company: str) -> list[dict]:
    """Every contact whose company normalizes to the same thing as `company` — so
    "Google" matches a contact stored as "Google LLC", "google, inc.", etc."""
    if not company:
        return []
    target = normalize_company(company)
    if not target:
        return []
    with session_scope() as s:
        rows = s.scalars(select(Contact)).all()
        return [to_dict(c) for c in rows if normalize_company(c.company) == target]


def get(contact_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(Contact, contact_id)
        return to_dict(row) if row else None


def update(contact_id: int, **fields) -> dict | None:
    allowed = {"company", "name", "email", "role"}
    with session_scope() as s:
        row = s.get(Contact, contact_id)
        if row is None:
            return None
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(row, key, value)
        s.flush()
        return to_dict(row)


def remove(contact_id: int) -> bool:
    with session_scope() as s:
        row = s.get(Contact, contact_id)
        if row is None:
            return False
        s.delete(row)
        return True
