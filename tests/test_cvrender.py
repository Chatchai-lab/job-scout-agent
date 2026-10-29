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


def test_optional_person_fields_may_be_missing():
    import copy
    minimal = copy.deepcopy(PROFILE)
    for key in ("headline", "address", "phone", "github", "linkedin"):
        minimal["person"].pop(key)
    tex = render_cv(minimal)
    assert "Max Mustermann" in tex and "Adresse" not in tex


def test_selection_headline_overrides_the_profile_headline():
    tex = render_cv(PROFILE, {"headline": "Angehender Forward Deployed Engineer"})
    assert "Angehender Forward Deployed Engineer" in tex
    assert "Software \\& AI" not in tex
    assert "Software \\& AI" in render_cv(PROFILE, {"headline": None})


def test_thesis_line_is_rendered_under_the_degree():
    profile = yaml.safe_load(yaml.safe_dump(PROFILE))
    profile["education"][0]["thesis"] = "Bachelorarbeit (in Arbeit): Quality-Gates & LLMs"
    tex = render_cv(profile)
    assert r"Bachelorarbeit (in Arbeit): Quality-Gates \& LLMs" in tex
    assert "Bachelorarbeit" not in render_cv(PROFILE)


def test_english_cv_uses_english_headings_months_and_labels():
    tex = render_cv(PROFILE, lang="en")
    assert r"\usepackage[english]{babel}" in tex
    for heading in ("Work Experience", "Education", "Skills", "Profile", "Personal Projects"):
        assert heading in tex
    assert "Berufserfahrung" not in tex and "Ausbildung" not in tex
    assert "since July 2026" in tex and "July 2025 - March 2026" in tex
    assert "Phone:" in tex and "Programming languages" in tex and "Focus areas" in tex


def test_german_cv_is_unchanged_by_default():
    tex = render_cv(PROFILE)
    assert r"\usepackage[ngerman]{babel}" in tex
    assert "Berufserfahrung" in tex and "seit Juli 2026" in tex
    assert format_range("2025-07", "2026-03", "en") == "July 2025 - March 2026"
    assert format_range("2025-07", "2026-03") == "Juli 2025 - März 2026"


def test_translated_context_replaces_texts_but_keeps_everything_else():
    from job_scout.cvrender import build_context
    from job_scout.translate import apply_units, context_units

    ctx = build_context(PROFILE, None, False, "de")
    units = context_units(ctx)
    assert units["exp.0.b.0"] == "Baute Tools fuer C# und C++."
    tech = ctx["tech_rows"]
    assert all(f"skill.{i}" not in units for i in range(tech))  # technology names stay as they are
    assert f"skill.{tech}" in units  # spoken languages are translated
    english = {k: "EN " + v for k, v in units.items()}
    out = apply_units(ctx, english)
    assert out["experience"][0]["bullets"][0]["text"] == "EN Baute Tools fuer C# und C++."
    assert out["experience"][0]["company"] == "A & B GmbH"  # names are not translated
    assert out["education"][0]["degree"] == "EN B.Sc. Informatik"
    assert out["skill_rows"][0] == ctx["skill_rows"][0]
    tex = render_cv(PROFILE, None, lang="en", translate=lambda c: apply_units(c, english))
    assert "EN Baute Tools" in tex and "Work Experience" in tex
