"""Wires real clients (Supabase, Anthropic, Telegram) into the pipelines."""

import logging

import anthropic
import httpx

from job_scout.config import Settings, get_settings
from job_scout.digest import run_digest
from job_scout.notify import TelegramNotifier
from job_scout.profile import load_profile_text
from job_scout.repo import SupabaseRepo
from job_scout.scoring import score_job
from job_scout.sources import fetch_for
from job_scout.triage import run_triage
from supabase import create_client


def _repo(settings: Settings) -> SupabaseRepo:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return SupabaseRepo(create_client(settings.supabase_url, settings.supabase_service_key))


def _notifier(settings: Settings) -> TelegramNotifier | None:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    return None


def run_triage_command() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set")
    llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    notifier = _notifier(settings)
    if notifier is None:
        print("Telegram not configured: running without notifications.")

    with httpx.Client(headers={"User-Agent": "job-scout-agent"}) as client:
        stats = run_triage(
            _repo(settings),
            settings,
            fetch=fetch_for,
            score_fn=lambda system, job: score_job(llm, settings.model_match, system, job),
            profile_text=load_profile_text(settings),
            notifier=notifier,
            client=client,
        )
    print(stats)
    if stats.companies_polled == 0 and stats.companies_failed:
        raise SystemExit("every company fetch failed")


def run_digest_command() -> None:
    settings = get_settings()
    notifier = _notifier(settings)
    if notifier is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
    sent = run_digest(_repo(settings), settings, notifier)
    print(f"Digest sent with {sent} jobs.")
