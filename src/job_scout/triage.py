"""Daily triage: fetch -> dedupe -> prefilter -> score -> instant push.

The digest (max N jobs, once a day) lives in digest.py so it can run at its
own time. Both only talk to the Repo interface, never to Supabase directly.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from job_scout.config import Settings
from job_scout.models import JobPosting
from job_scout.notify import Notifier, format_job
from job_scout.prefilter import prefilter
from job_scout.pricing import cost_usd
from job_scout.repo import Repo
from job_scout.scoring import ScoreResult, build_system

log = logging.getLogger("job_scout.triage")

FetchFn = Callable[[str, httpx.Client, str, str], list[JobPosting]]
ScoreFn = Callable[[str, JobPosting], tuple[ScoreResult, Any]]


@dataclass
class TriageStats:
    companies_polled: int = 0
    companies_failed: int = 0
    new_jobs: int = 0
    dropped: int = 0
    scored: int = 0
    score_errors: int = 0
    instant_pushed: int = 0
    budget_stopped: bool = False
    errors: list[str] = field(default_factory=list)


def _job_row(job: JobPosting, company_id: str | None) -> dict[str, Any]:
    return {
        "company_id": company_id,
        "company_name": job.company_name,
        "source": job.source,
        "external_id": job.external_id,
        "title": job.title,
        "location": job.location,
        "remote": job.remote,
        "description": job.description,
        "url": job.url,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "dedup_key": job.dedup_key,
    }


def _posting_from_row(row: dict[str, Any]) -> JobPosting:
    return JobPosting(
        source=row["source"],
        external_id=row["external_id"],
        company_name=row["company_name"],
        title=row["title"],
        url=row["url"],
        location=row.get("location"),
        remote=row.get("remote"),
        description=row.get("description"),
    )


def qualifies(score: dict[str, Any], settings: Settings) -> bool:
    return (
        score["ring"] != "raus"
        and score.get("start_ok") is not False
        and score["fit"] >= settings.score_threshold
        and score["reach"] >= settings.score_threshold
    )


def is_instant(score: dict[str, Any], settings: Settings) -> bool:
    return qualifies(score, settings) and score["fit"] >= settings.instant_push_threshold


def fetch_new_jobs(
    repo: Repo, fetch: FetchFn, client: httpx.Client, stats: TriageStats
) -> None:
    known_ids, known_keys = repo.known_jobs()
    rows: list[dict[str, Any]] = []
    for company in repo.active_companies():
        if company["ats"] == "none" or not company.get("ats_slug"):
            continue
        try:
            postings = fetch(company["ats"], client, company["name"], company["ats_slug"])
        except Exception as exc:  # one broken board must not stop the run
            stats.companies_failed += 1
            stats.errors.append(f"{company['name']}: {exc}")
            log.warning("fetch failed for %s: %s", company["name"], exc)
            continue
        stats.companies_polled += 1
        repo.mark_polled(company["id"])
        for posting in postings:
            ident = (posting.source, posting.external_id)
            if ident in known_ids or posting.dedup_key in known_keys:
                continue
            known_ids.add(ident)
            known_keys.add(posting.dedup_key)
            rows.append(_job_row(posting, company["id"]))
    repo.insert_jobs(rows)
    stats.new_jobs = len(rows)


def score_pending(
    repo: Repo, settings: Settings, score_fn: ScoreFn, system: str, stats: TriageStats
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Prefilter and score every unscored job. Returns (job_row, score_row) pairs."""
    budget_usd = settings.monthly_budget_eur / settings.eur_per_usd
    spent = repo.month_cost_usd()
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    drops: list[dict[str, Any]] = []

    for row in repo.unscored_jobs():
        reason = prefilter(_posting_from_row(row), include_abroad=settings.include_abroad)
        if reason:
            drops.append({"job_id": row["id"], "reason": str(reason)})
            continue
        if spent >= budget_usd:
            stats.budget_stopped = True
            break
        try:
            result, usage = score_fn(system, _posting_from_row(row))
        except Exception as exc:
            stats.score_errors += 1
            stats.errors.append(f"score {row['title']}: {exc}")
            log.warning("scoring failed for %s: %s", row["title"], exc)
            continue
        cost = cost_usd(settings.model_match, usage)
        spent += cost
        score_row = {
            "job_id": row["id"],
            **result.model_dump(),
            "model": settings.model_match,
            "cost_usd": round(cost, 6),
        }
        repo.save_score(score_row)
        repo.log_usage(
            {
                "purpose": "match",
                "model": settings.model_match,
                "input_tokens": usage.input_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": round(cost, 6),
            }
        )
        stats.scored += 1
        results.append((row, score_row))

    repo.insert_drops(drops)
    stats.dropped = len(drops)
    return results


def run_triage(
    repo: Repo,
    settings: Settings,
    *,
    fetch: FetchFn,
    score_fn: ScoreFn,
    profile_text: str,
    notifier: Notifier | None,
    client: httpx.Client,
) -> TriageStats:
    stats = TriageStats()
    budget_usd = settings.monthly_budget_eur / settings.eur_per_usd
    spent_before = repo.month_cost_usd()

    fetch_new_jobs(repo, fetch, client, stats)

    system = build_system(profile_text, repo.approved_rules())
    results = score_pending(repo, settings, score_fn, system, stats)

    if notifier:
        instant = [(j, s) for j, s in results if is_instant(s, settings)]
        for job, score in instant:
            notifier.send("🔥 <b>Top-Treffer</b>\n\n" + format_job(job, score), job["id"])
        repo.mark_notified([j["id"] for j, _ in instant])
        stats.instant_pushed = len(instant)

        spent_after = repo.month_cost_usd()
        if spent_before < 0.8 * budget_usd <= spent_after:
            spent_eur = spent_after * settings.eur_per_usd
            notifier.send(
                f"⚠️ 80 % des Monatsbudgets verbraucht "
                f"({spent_eur:.2f} € von {settings.monthly_budget_eur:.2f} €)."
            )
        if stats.budget_stopped:
            notifier.send("⛔ Monatsbudget erreicht: Scoring pausiert (Pakete weiter möglich).")
    return stats
