import httpx
from fakes import score

from job_scout.notify import TelegramNotifier, format_job, keyboard

JOB = {"title": "FDE <Berlin>", "company_name": "A&B", "location": "Berlin", "remote": True,
       "url": "https://example.com/1"}


def test_message_is_html_escaped_and_complete():
    text = format_job(JOB, score(fit=9, reach=7))
    assert "FDE &lt;Berlin&gt;" in text and "A&amp;B" in text
    assert "Fit 9/10" in text and "(remote)" in text and "https://example.com/1" in text


def test_start_warning_and_salary_shown():
    text = format_job(JOB, score(start_ok=False, salary="60-70k"))
    assert "März 2027" in text and "60-70k" in text


def test_keyboard_carries_job_id_in_all_three_buttons():
    buttons = keyboard("abc")["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["pkg:abc", "save:abc", "rej:abc"]


def test_send_document_uploads_the_file_with_caption(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 content")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    TelegramNotifier("TOKEN", "42", client).send_document(pdf, caption="CV Firma")
    assert seen["url"].endswith("/sendDocument")
    assert b'filename="cv.pdf"' in seen["body"] and b"CV Firma" in seen["body"]
    assert b"%PDF-1.4 content" in seen["body"]
