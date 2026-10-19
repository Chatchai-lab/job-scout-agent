"""Load config/companies.yaml (gitignored, your real target list) into Supabase."""

from pathlib import Path

import yaml

from job_scout.config import get_settings
from supabase import create_client


def seed_companies(path: str) -> int:
    data = yaml.safe_load(Path(path).read_text())
    companies = data.get("companies", [])
    if not companies:
        raise ValueError(f"no companies found in {path}")

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")

    client = create_client(settings.supabase_url, settings.supabase_service_key)
    rows = [
        {
            "name": c["name"],
            "ats": c.get("ats", "none"),
            "ats_slug": c.get("ats_slug"),
            "careers_url": c.get("careers_url"),
            "source": "manual",
        }
        for c in companies
    ]
    client.table("companies").upsert(rows, on_conflict="ats,ats_slug").execute()
    return len(rows)
