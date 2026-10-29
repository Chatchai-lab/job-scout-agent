"""Daily digest: the best unnotified, qualifying jobs, max N, ranked by fit x reach."""

import html
from datetime import UTC, datetime
from typing import Any

from job_scout.config import Settings
from job_scout.notify import Notifier, format_job
from job_scout.prefilter import prefilter
from job_scout.repo import NOTIFICATIONS_PAUSED, Repo
from job_scout.triage import is_manual, posting_from_row, qualifies


def _still_allowed(row: dict[str, Any], settings: Settings) -> bool:
    """Re-apply the current prefilter so rule changes also cover jobs scored earlier."""
    job = row.get("jobs")
    if not job:
        return True
    if job.get("closed_at"):
        return False  # the posting is gone from the company board
    if job.get("source") == "manual":
        return True  # chosen by hand: no rule may hide it
    reason = prefilter(
        posting_from_row(job),
        include_abroad=settings.include_abroad,
        include_working_student=settings.include_working_student,
    )
    return reason is None


def select_digest(rows: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    good = [r for r in rows if qualifies(r, settings) and _still_allowed(r, settings)]
    good.sort(key=lambda r: (is_manual(r), r["fit"] * r["reach"]), reverse=True)  # own finds first
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


def due_reminders(
    apps: list[dict[str, Any]], days: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Applications still on 'beworben' for `days` days, not reminded within the last `days`."""
    now = now or datetime.now(UTC)
    due = []
    for app in apps:
        if app["status"] != "beworben" or not app.get("applied_at") or not app.get("job_id"):
            continue
        applied = datetime.fromisoformat(app["applied_at"]).astimezone(UTC)
        reminded = app.get("reminded_at")
        recently_reminded = bool(reminded) and (
            (now - datetime.fromisoformat(reminded).astimezone(UTC)).days < days
        )
        if (now - applied).days >= days and not recently_reminded:
            due.append(app)
    return due


def send_reminders(repo: Repo, settings: Settings, notifier: Notifier) -> int:
    due = due_reminders(repo.open_applications(), settings.reminder_days)
    for app in due:
        job = app.get("jobs") or {}
        days = (datetime.now(UTC) - datetime.fromisoformat(app["applied_at"])).days
        text = (
            f"⏰ <b>Nachfassen?</b>\n{html.escape(job.get('title', ''))}\n"
            f"{html.escape(job.get('company_name', ''))}\n"
            f"Beworben vor {days} Tagen, noch keine Rückmeldung eingetragen."
        )
        notifier.send_reminder(text, app["job_id"])
    repo.mark_reminded([a["job_id"] for a in due])
    return len(due)


def notifications_paused(repo: Repo) -> bool:
    return repo.get_state(NOTIFICATIONS_PAUSED) == "true"


def run_digest(
    repo: Repo, settings: Settings, notifier: Notifier, *, ignore_pause: bool = False
) -> int:
    """Send the digest. Only sent jobs are marked; qualifying overflow stays for tomorrow.

    While notifications are paused nothing is sent or marked, unless `ignore_pause` is set
    (manual test runs).
    """
    if not ignore_pause and notifications_paused(repo):
        return 0
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
    send_reminders(repo, settings, notifier)
    return len(chosen)


def resend_job(repo: Repo, notifier: Notifier, job_id: str) -> bool:
    """Send one stored job again with fresh buttons (e.g. after a mis-tap). False if unknown."""
    row = repo.scored_job(job_id)
    if row is None:
        return False
    notifier.send("🔁 " + format_job(row["jobs"], row), job_id)
    return True
