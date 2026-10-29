from datetime import date

from job_scout.letterrender import german_date, letter_paragraphs, render_letter

PROFILE = {"person": {"name": "Max Mustermann", "address": "Musterstr. 1, 12345 Musterstadt",
                      "phone": "+49 123 456", "email": "max@example.com"}}
JOB = {"company_name": "A & B GmbH", "title": "Forward Deployed Engineer (m/w/d)",
       "location": "München, Deutschland"}
LETTER = ("Sehr geehrte Damen und Herren,\n\nich bewerbe mich mit 100% Einsatz.\n\n"
          "Mit freundlichen Grüßen\nMax Mustermann")


def test_german_date_uses_month_names():
    assert german_date(date(2026, 10, 21)) == "21. Oktober 2026"
    assert german_date(date(2027, 3, 1)) == "1. März 2027"


def test_paragraphs_keep_closing_lines_together_and_escape():
    paragraphs = letter_paragraphs(LETTER)
    assert paragraphs[1] == r"ich bewerbe mich mit 100\% Einsatz."
    assert paragraphs[2] == r"Mit freundlichen Grüßen\\ Max Mustermann"


def test_letter_has_sender_date_recipient_subject_and_body():
    tex = render_letter(PROFILE, LETTER, JOB, date(2026, 10, 21))
    assert r"A \& B GmbH" in tex and "München, Deutschland" in tex
    assert r"Bewerbung als Forward Deployed Engineer (m/w/d)" in tex
    assert "21. Oktober 2026" in tex and "Musterstr. 1" in tex
    assert r"\href{mailto:max@example.com}" in tex
    assert "Sehr geehrte Damen und Herren," in tex
    assert "\\VAR" not in tex and "\\BLOCK" not in tex


def test_letter_without_place_omits_the_line():
    tex = render_letter(PROFILE, LETTER, {**JOB, "location": None}, date(2026, 10, 21))
    assert "München" not in tex


def test_english_letter_has_english_date_subject_and_babel():
    from job_scout.letterrender import english_date

    assert english_date(date(2026, 10, 29)) == "29 October 2026"
    job = {"company_name": "MDIS Consulting", "title": "Software Developer", "location": None}
    tex = render_letter(PROFILE, "Dear Sir or Madam,\n\nHello.\n\nKind regards,\nMax", job,
                        date(2026, 10, 29), lang="en")
    assert r"\usepackage[english]{babel}" in tex
    assert "29 October 2026" in tex and "Application as Software Developer" in tex
    assert "Bewerbung als" not in tex
