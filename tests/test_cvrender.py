import yaml

from job_scout.cvrender import format_range, latex_escape, render_cv

PROFILE = yaml.safe_load("""
person:
  name: Max Mustermann
  headline: Software & AI
  address: Musterstr. 1, 12345 Musterstadt
  phone: "+49 123 456"
  email: max@example.com
  github: https://github.com/example
  linkedin: https://www.linkedin.com/in/example/
target:
  languages: [Deutsch (Muttersprache), Englisch (fließend)]
summary: Profil mit R&D und 100% Einsatz.
education:
  - {id: edu-bsc, degree: B.Sc. Informatik, school: Beispiel Uni, start: 2022-10, end: 2027-02,
     focus: Software, Datenbanken}
experience:
  - id: exp-a
    title: Werkstudent
    company: A & B GmbH
    place: Bensheim
    start: 2026-07
    end: present
    bullets:
      - {id: exp-a-1, text: Baute Tools fuer C# und C++.}
      - {id: exp-a-2, text: Spart 50% Zeit_pro Lauf.}
  - id: exp-b
    title: Tester
    company: Firma B
    place: Frankfurt
    start: 2025-07
    end: 2026-03
    bullets:
      - {id: exp-b-1, text: Testete Spiele.}
projects:
  - id: proj-x
    name: Projekt X
    url: https://github.com/example/x
    bullets:
      - {id: proj-x-1, text: Eine Pipeline.}
skills:
  languages: [Python, C#]
  tools: [Git]
  soft: [Teamfähigkeit]
other:
  - Work & Travel
""")


def test_latex_escape_covers_special_characters():
    assert latex_escape("R&D 50% #1 a_b {x}") == r"R\&D 50\% \#1 a\_b \{x\}"


def test_format_range_uses_german_months():
    assert format_range("2025-07", "2026-03") == "Juli 2025 - März 2026"
    assert format_range("2026-07", "present") == "seit Juli 2026"


def test_full_render_contains_profile_facts_escaped():
    tex = render_cv(PROFILE, has_photo=True)
    assert r"A \& B GmbH" in tex
    assert r"Spart 50\% Zeit\_pro Lauf." in tex
    assert "seit Juli 2026" in tex
    assert r"\href{mailto:max@example.com}" in tex
    assert "photo.jpg" in tex
    assert r"\href{https://github.com/example/x}{(GitHub Repository)}" in tex
    assert "Programmiersprachen: & Python, C\\#" in tex
    assert "\\VAR" not in tex and "\\BLOCK" not in tex


def test_render_without_photo_omits_image():
    assert "includegraphics" not in render_cv(PROFILE, has_photo=False)


def test_selection_orders_bullets_and_rewrites_wording():
    selection = {
        "summary": "Neues Profil.",
        "bullets": {"exp-a": ["exp-a-2", "exp-a-1"], "exp-b": []},
        "rewrites": {"exp-a-1": "Entwickelte Werkzeuge."},
    }
    tex = render_cv(PROFILE, selection)
    assert tex.index("Zeit") < tex.index("Entwickelte Werkzeuge.")
    assert "Neues Profil." in tex
    assert "Testete Spiele" not in tex  # exp-b has no selected bullets
    assert "Firma B" not in tex


def test_selection_cannot_invent_bullets():
    tex = render_cv(PROFILE, {"bullets": {"exp-a": ["exp-a-1", "made-up-id"]}})
    assert "made-up-id" not in tex
