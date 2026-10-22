"""Daily digest: the best unnotified, qualifying jobs, max N, ranked by fit x reach."""

from datetime import UTC, datetime
from typing import Any

from job_scout.config import Settings
from job_scout.notify import Notifier, format_job
from job_scout.prefilter import prefilter
from job_scout.repo import Repo
from job_scout.triage import posting_from_row, qualifies


def _still_allowed(row: dict[str, Any], settings: Settings) -> bool:
    """Re-apply the current prefilter so rule changes also cover jobs scored earlier."""
    job = row.get("jobs")
    if not job:
        return True
    return prefilter(posting_from_row(job), include_abroad=settings.include_abroad) is None


def select_digest(rows: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    good = [r for r in rows if qualifies(r, settings) and _still_allowed(r, settings)]
    good.sort(key=lambda r: r["fit"] * r["reach"], reverse=True)
    return good[: settings.digest_max_jobs]


def open_applications_line(apps: list[dict[str, Any]], now: datetime | None = None) -> str | None:
    """'📨 3 offene Bewerbungen, älteste seit 12 Tagen', or None when nothing is open."""
    if not apps:
        return None
    now = now or datetime.now(UTC)
    since = [
        datetime.fromisoformat(a.get("applied_at") or a["updated_at"]).astimezone(UTC)
        for a in apps
    ]
    days = max((now - min(since)).days, 0)
    noun = "offene Bewerbung" if len(apps) == 1 else "offene Bewerbungen"
    unit = "Tag" if days == 1 else "Tagen"
    return f"📨 {len(apps)} {noun}, älteste seit {days} {unit}"


def run_digest(repo: Repo, settings: Settings, notifier: Notifier) -> int:
    """Send the digest. Only sent jobs are marked; qualifying overflow stays for tomorrow."""
    rows = repo.unnotified()
    chosen = select_digest(rows, settings)
    open_line = open_applications_line(repo.open_applications())
    suffix = f"\n{open_line}" if open_line else ""
    if chosen:
        notifier.send(f"☀️ <b>Dein Job-Digest</b> – {len(chosen)} Treffer{suffix}")
        for row in chosen:
            notifier.send(format_job(row["jobs"], row), row["job_id"])
    else:
        notifier.send("☀️ Heute nichts, das die Schwellen erreicht." + suffix)
    repo.mark_notified([r["job_id"] for r in chosen])
    return len(chosen)


def resend_job(repo: Repo, notifier: Notifier, job_id: str) -> bool:
    """Send one stored job again with fresh buttons (e.g. after a mis-tap). False if unknown."""
    row = repo.scored_job(job_id)
    if row is None:
        return False
    notifier.send("🔁 " + format_job(row["jobs"], row), job_id)
    return True
