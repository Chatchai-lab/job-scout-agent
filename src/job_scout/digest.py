"""Daily digest: the best unnotified, qualifying jobs, max N, ranked by fit x reach."""

from typing import Any

from job_scout.config import Settings
from job_scout.notify import Notifier, format_job
from job_scout.repo import Repo
from job_scout.triage import qualifies


def select_digest(rows: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    good = [r for r in rows if qualifies(r, settings)]
    good.sort(key=lambda r: r["fit"] * r["reach"], reverse=True)
    return good[: settings.digest_max_jobs]


def run_digest(repo: Repo, settings: Settings, notifier: Notifier) -> int:
    """Send the digest. Only sent jobs are marked; qualifying overflow stays for tomorrow."""
    rows = repo.unnotified()
    chosen = select_digest(rows, settings)
    if chosen:
        notifier.send(f"☀️ <b>Dein Job-Digest</b> – {len(chosen)} Treffer")
        for row in chosen:
            notifier.send(format_job(row["jobs"], row), row["job_id"])
    else:
        notifier.send("☀️ Heute nichts, das die Schwellen erreicht.")
    repo.mark_notified([r["job_id"] for r in chosen])
    return len(chosen)
