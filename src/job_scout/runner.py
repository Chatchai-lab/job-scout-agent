"""Wires real clients (Supabase, Anthropic, Telegram) into the pipelines."""

import logging
import tempfile
from pathlib import Path

import anthropic
import httpx

from job_scout.config import Settings, get_settings
from job_scout.digest import notifications_paused, resend_job, run_digest
from job_scout.notify import TelegramNotifier
from job_scout.package import run_package
from job_scout.pdfbuild import build_pdf
from job_scout.profile import load_profile_text, scoring_profile_from_private
from job_scout.repo import SupabaseRepo
from job_scout.scoring import score_job
from job_scout.sources import fetch_for
from job_scout.triage import run_triage
from supabase import create_client


def _repo(settings: Settings) -> SupabaseRepo:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return SupabaseRepo(create_client(settings.supabase_url, settings.supabase_service_key))


def _scoring_profile(settings: Settings, repo: SupabaseRepo) -> str:
    private = repo.private_profile()
    return scoring_profile_from_private(private) if private else load_profile_text(settings)


def _notifier(settings: Settings) -> TelegramNotifier | None:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return None


def run_triage_command(notify: bool = True, ignore_pause: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set")
    llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    repo = _repo(settings)
    notifier = _notifier(settings) if notify else None
    if notifier is not None and not ignore_pause and notifications_paused(repo):
        notifier = None
        print("Notifications are paused (app_state).")
    if notifier is None:
        print("Running without Telegram notifications.")

    with httpx.Client(headers={"User-Agent": "job-scout-agent"}) as client:
        stats = run_triage(
            repo,
            settings,
            fetch=fetch_for,
            score_fn=lambda system, job: score_job(llm, settings.model_match, system, job),
            profile_text=_scoring_profile(settings, repo),
            notifier=notifier,
            client=client,
        )
    print(stats)
    if stats.companies_polled == 0 and stats.companies_failed:
        raise SystemExit("every company fetch failed")


def run_digest_command(ignore_pause: bool = False) -> None:
    settings = get_settings()
    notifier = _notifier(settings)
    if notifier is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
    repo = _repo(settings)
    if not ignore_pause and notifications_paused(repo):
        print("Notifications are paused (app_state): digest skipped.")
        return
    sent = run_digest(repo, settings, notifier, ignore_pause=True)
    print(f"Digest sent with {sent} jobs.")


def run_resend_command(job_id: str) -> None:
    settings = get_settings()
    notifier = _notifier(settings)
    if notifier is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
    if not resend_job(_repo(settings), notifier, job_id):
        raise SystemExit(f"No scored job with id {job_id}")
    print("Job sent again.")


def error_detail(exc: Exception) -> str:
    """Type plus, for API errors, status and the API's technical message. Never request content:
    the CV text must not reach the public Actions log."""
    if isinstance(exc, anthropic.APIStatusError):
        return f"{type(exc).__name__} {exc.status_code}: {str(exc.message)[:300]}"
    code, message = getattr(exc, "code", None), getattr(exc, "message", None)
    if code or message:  # database errors: code and the database's own message, no row content
        return f"{type(exc).__name__} {code or ''}: {str(message or '')[:200]}".strip()
    return type(exc).__name__


def run_package_command(job_id: str) -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set")
    notifier = _notifier(settings)
    if notifier is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
    llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    workdir = Path(tempfile.mkdtemp(prefix="package-"))
    try:
        found = run_package(
            _repo(settings), settings, llm, notifier, job_id, build_pdf=build_pdf, workdir=workdir
        )
    except Exception as exc:
        detail = error_detail(exc)
        notifier.send(f"📦 Paket fehlgeschlagen: {detail}")
        raise SystemExit(f"package failed: {detail}") from None
    if not found:
        raise SystemExit(f"No scored job with id {job_id}")
    print("Package sent.")


def run_import_command(job_id: str) -> None:
    from job_scout.importer import fetch_page, read_posting, run_import

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set")
    notifier = _notifier(settings)
    if notifier is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
    llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    repo = _repo(settings)
    try:
        with httpx.Client() as client:
            outcome = run_import(
                repo,
                settings,
                notifier,
                job_id,
                fetch_fn=lambda url: fetch_page(client, url),
                read_fn=lambda text, url: read_posting(llm, settings.model_match, text, url),
                score_fn=lambda system, job: score_job(llm, settings.model_match, system, job),
                profile_text=_scoring_profile(settings, repo),
            )
    except Exception as exc:
        detail = error_detail(exc)
        notifier.send(f"🔗 Import fehlgeschlagen: {detail}")
        raise SystemExit(f"import failed: {detail}") from None
    print(f"Import: {outcome}.")


def run_discover_command() -> None:
    from job_scout.discover import SupabaseCandidateStore, run_discover

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    db = create_client(settings.supabase_url, settings.supabase_service_key)
    store = SupabaseCandidateStore(db)
    with httpx.Client() as client:
        found, missing = run_discover(client, store)
    # Names stay out of the (public) Actions log: only counts.
    print(f"Discover: {found} boards found, {missing} candidates without a known board.")


def run_maintenance_command(task: str) -> None:
    from job_scout.maintenance import TASKS

    if task not in TASKS:
        raise SystemExit(f"unknown task {task!r}; allowed: {', '.join(sorted(TASKS))}")
    count = TASKS[task](_repo(get_settings()))
    print(f"Maintenance '{task}': {count} rows changed.")
