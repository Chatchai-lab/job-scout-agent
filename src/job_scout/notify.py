"""Telegram delivery: one message per job, with inline action buttons."""

import html
from pathlib import Path
from typing import Any, Protocol

import httpx

from job_scout.scoring import ScoreResult

_API = "https://api.telegram.org/bot{token}/sendMessage"
_DOC_API = "https://api.telegram.org/bot{token}/sendDocument"
_RING_LABEL = {"kern": "Kern", "nah": "Nah dran", "beratung": "Beratung", "raus": "Raus"}


class Notifier(Protocol):
    def send(self, text: str, job_id: str | None = None) -> None: ...
    def send_reminder(self, text: str, job_id: str) -> None: ...


def format_job(job: dict[str, Any], score: dict[str, Any] | ScoreResult) -> str:
    s = score if isinstance(score, dict) else score.model_dump()
    location = job.get("location") or "Ort unbekannt"
    if job.get("remote"):
        location += " (remote)"
    lines = [
        *(["🎓 Werkstudent"] if job.get("kind") == "working_student" else []),
        f"<b>{html.escape(job['title'])}</b>",
        html.escape(job["company_name"]),
        f"📍 {html.escape(location)}",
        f"{_RING_LABEL.get(s['ring'], s['ring'])} · Fit {s['fit']}/10 · Reach {s['reach']}/10",
    ]
    if s.get("start_ok") is False:
        lines.append("⚠️ Startdatum evtl. vor März 2027")
    if s.get("salary"):
        lines.append(f"💶 {html.escape(s['salary'])}")
    lines.append("")
    lines.append(html.escape(s["reason"]))
    lines.append(html.escape(job["url"]))
    return "\n".join(lines)


def keyboard(job_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "📦 Paket", "callback_data": f"pkg:{job_id}"},
                {"text": "👀 Merken", "callback_data": f"save:{job_id}"},
                {"text": "❌ Verwerfen", "callback_data": f"rej:{job_id}"},
            ]
        ]
    }


def reminder_keyboard(job_id: str) -> dict[str, Any]:
    button = {"text": "📋 Bewerbung öffnen", "callback_data": f"app:{job_id}"}
    return {"inline_keyboard": [[button]]}


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None):
        if not token or not chat_id:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        self._url = _API.format(token=token)
        self._doc_url = _DOC_API.format(token=token)
        self._chat_id = chat_id
        self._client = client or httpx.Client()

    def send(self, text: str, job_id: str | None = None) -> None:
        self._post(text, keyboard(job_id) if job_id else None)

    def send_reminder(self, text: str, job_id: str) -> None:
        self._post(text, reminder_keyboard(job_id))

    def _post(self, text: str, markup: dict[str, Any] | None) -> None:
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if markup:
            payload["reply_markup"] = markup
        response = self._client.post(self._url, json=payload, timeout=20)
        response.raise_for_status()

    def send_document(self, path: Path, caption: str | None = None) -> None:
        data = {"chat_id": self._chat_id}
        if caption:
            data["caption"] = caption
        with path.open("rb") as handle:
            response = self._client.post(
                self._doc_url, data=data, files={"document": (path.name, handle)}, timeout=60
            )
        response.raise_for_status()
