from datetime import date
from pathlib import Path

import pytest
from fakes import FakeNotifier, FakeRepo, ScriptedClient, posting, score

from job_scout.config import Settings
from job_scout.package import (
    INSTRUCTIONS,
    Draft,
    build_selection,
    create_package,
    file_slug,
    run_package,
)

PROFILE = """
person:
  name: Max Mustermann
  headline: Software & AI
  email: max@example.com
  photo: foto.JPG
target:
  earliest_start: 2027-03-01
  languages: [Deutsch]
summary: Informatik-Student mit Fokus auf KI.
education:
  - {id: edu-bsc, degree: B.Sc. Informatik, school: Beispiel Uni, start: 2022-10, end: 2027-02}
experience:
  - id: exp-a
    title: Werkstudent
    company: A GmbH
    place: Bensheim
    start: 2026-07
    end: present
    bullets:
      - {id: exp-a-1, text: Baute Tools mit Python und C#.}
      - {id: exp-a-2, text: Spart 50% Zeit.}
  - id: exp-b
    title: Tester
    company: B AG
    place: Frankfurt
    start: 2025-07
    end: 2026-03
    bullets:
      - {id: exp-b-1, text: Testete Spiele.}
projects:
  - id: proj-x
    name: Projekt X
    bullets:
      - {id: proj-x-1, text: Eine Pipeline in Python.}
  - id: proj-y
    name: Projekt Y
    bullets:
      - {id: proj-y-1, text: Ein Roboter.}
skills:
  languages: [Python, C#]
"""

LETTER = (
    "Sehr geehrte Damen und Herren,\n\nich bewerbe mich als Engineer. Ich schließe im Februar 2027 "
    "ab und starte im März 2027.\n\nMit freundlichen Grüßen\nMax Mustermann"
)


INVENTED = LETTER.replace("ich bewerbe", "ich habe 7 Jahre Erfahrung, ich bewerbe")


def _draft(**over):
    base = {
        "headline": "Angehender Software Engineer",
        "summary": "Student mit Python-Erfahrung.",
        "picks": [
            {"entry_id": "exp-a", "bullet_ids": ["exp-a-2", "exp-a-1"]},
            {"entry_id": "exp-b", "bullet_ids": ["exp-b-1"]},
            {"entry_id": "proj-x", "bullet_ids": ["proj-x-1"]},
        ],
        "rewrites": [{"bullet_id": "exp-a-1", "text": "Entwickelte Werkzeuge in Python und C#."}],
        "cover_letter": LETTER,
        "gaps": [{"requirement": "Python", "status": "erfüllt", "note": "Im Profil."}],
    }
    return base | over


JOB = {"company_name": "Firma", "title": "Engineer", "location": "Berlin",
       "url": "https://example.com/1", "description": "Python, Kunden."}


def _create(drafts, checks):
    client = ScriptedClient(drafts, checks)
    return create_package(client, Settings(), PROFILE, JOB), client


def test_happy_path_selects_orders_and_rewrites():
    result, client = _create([_draft()], [[]])
    sel = result.selection
    assert sel["bullets"]["exp-a"] == ["exp-a-2", "exp-a-1"]
    assert sel["rewrites"] == {"exp-a-1": "Entwickelte Werkzeuge in Python und C#."}
    assert sel["projects_chosen"] == ["proj-x"]
    assert result.warnings == [] and result.cost_usd() > 0
    assert [name for name, _ in client.calls] == ["submit_package", "submit_factcheck"]


def test_rewrite_with_new_technology_falls_back_to_original():
    bad = _draft(rewrites=[{"bullet_id": "exp-a-1", "text": "Baute Tools mit Kubernetes."}])
    result, _ = _create([bad], [[]])
    assert result.selection["rewrites"] == {}
    assert any("verworfen" in w for w in result.warnings)


def test_rewrite_with_new_number_falls_back_to_original():
    bad = _draft(rewrites=[{"bullet_id": "exp-a-2", "text": "Spart 80% Zeit."}])
    result, _ = _create([bad], [[]])
    assert "exp-a-2" not in result.selection["rewrites"]


def test_llm_flagged_bullet_and_summary_are_reverted():
    flags = [{"target": "bullet:exp-a-1", "problem": "übertrieben"},
             {"target": "summary", "problem": "unbelegt"}]
    result, _ = _create([_draft()] * 3, [flags] * 3)  # two retries, still flagged
    assert result.selection["rewrites"] == {}
    assert result.selection["summary"] is None  # renderer falls back to the profile summary
    assert any(w.startswith("Profiltext durch Standardtext ersetzt") for w in result.warnings)


def test_flagged_summary_is_regenerated_once_and_kept_when_the_retry_is_clean():
    flagged = [{"target": "summary", "problem": "unbelegt"}]
    result, client = _create([_draft(), _draft(summary="Angehender Engineer.")], [flagged, []])
    assert result.selection["summary"] == "Angehender Engineer."
    assert result.warnings == []
    assert "Profiltext: unbelegt" in client.calls[-2][1]  # the retry carried the finding


def test_letter_with_invented_number_is_regenerated_once():
    invented = _draft(cover_letter=INVENTED)
    result, client = _create([invented, _draft()], [[], []])
    assert result.cover_letter == LETTER.strip()
    assert result.warnings == []
    second_request = [content for name, content in client.calls if name == "submit_package"][1]
    assert "unbelegte Angaben" in second_request and "'7'" in second_request


def test_letter_still_unsupported_after_retry_is_delivered_with_warning():
    invented = _draft(cover_letter=INVENTED)
    result, _ = _create([invented] * 3, [[], [], []])
    assert any(w.startswith("Anschreiben:") for w in result.warnings)


def test_llm_flagged_letter_triggers_regeneration():
    flags = [{"target": "cover_letter", "problem": "Führungserfahrung erfunden"}]
    result, client = _create([_draft(), _draft()], [flags, []])
    assert len([c for c in client.calls if c[0] == "submit_package"]) == 2
    assert result.warnings == []


def test_unknown_ids_are_dropped_not_invented():
    import yaml
    draft = Draft(**_draft(picks=[{"entry_id": "exp-a", "bullet_ids": ["exp-a-1", "fake-9"]},
                                  {"entry_id": "nope", "bullet_ids": ["x"]}],
                           rewrites=[{"bullet_id": "fake-9", "text": "Erfunden."}]))
    sel = build_selection(draft, yaml.safe_load(PROFILE))
    assert sel["bullets"] == {"exp-a": ["exp-a-1"]}
    assert sel["rewrites"] == {}


def _repo_with_job():
    repo = FakeRepo()
    repo.insert_jobs([{**{k: v for k, v in posting().model_dump().items()
                          if k in ("source", "external_id", "title", "location", "url",
                                   "description", "dedup_key")},
                       "company_name": "Firma", "remote": False}])
    repo.save_score({"job_id": "job-1", **score().model_dump()})
    repo.profile_text = PROFILE
    repo.assets[("cv-assets", "foto.JPG")] = b"jpegbytes"
    return repo


def _fake_build(tex, photo, workdir, name="cv"):
    workdir.mkdir(parents=True, exist_ok=True)
    if name == "cv":
        assert "Max Mustermann" in tex and photo == b"jpegbytes"
    else:
        assert "Bewerbung als" in tex and photo is None
    pdf = workdir / f"{name}.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + name.encode())
    return pdf


def test_run_package_builds_stores_logs_and_delivers(tmp_path: Path):
    repo, notifier = _repo_with_job(), FakeNotifier()
    client = ScriptedClient([_draft()], [[]])
    assert run_package(repo, Settings(), client, notifier, "job-1",
                       build_pdf=_fake_build, workdir=tmp_path, today=date(2026, 10, 21)) is True
    cv_key = "packages/job-1/Lebenslauf_Max_Mustermann.pdf"
    letter_key = "packages/job-1/Anschreiben_Firma_Max_Mustermann.pdf"
    assert repo.uploads[("cv-assets", cv_key)] == (b"%PDF-1.4 cv", "application/pdf")
    assert repo.uploads[("cv-assets", letter_key)][0] == b"%PDF-1.4 letter"
    assert repo.packages["job-1"]["cv_pdf_path"] == cv_key
    assert repo.packages["job-1"]["letter_pdf_path"] == letter_key
    assert [u["purpose"] for u in repo.usage] == ["package", "package"]
    # CV first, then the cover letter, each under the name it will be sent with
    assert [name for name, _ in notifier.docs] == [
        "Lebenslauf_Max_Mustermann.pdf", "Anschreiben_Firma_Max_Mustermann.pdf",
    ]
    assert "CV" in notifier.docs[0][1] and "Anschreiben" in notifier.docs[1][1]
    texts = [t for t, _ in notifier.sent]
    assert len(texts) == 1 and texts[0].startswith("🔍")  # gap analysis, no warnings


def test_run_package_unknown_job_says_so(tmp_path: Path):
    notifier = FakeNotifier()
    assert run_package(FakeRepo(), Settings(), ScriptedClient([], []), notifier, "nope",
                       build_pdf=_fake_build, workdir=tmp_path) is False
    assert "nicht bekannt" in notifier.sent[0][0]


def test_run_package_without_profile_row_fails_loudly(tmp_path: Path):
    repo = _repo_with_job()
    repo.profile_text = None
    with pytest.raises(RuntimeError):
        run_package(repo, Settings(), ScriptedClient([], []), FakeNotifier(), "job-1",
                    build_pdf=_fake_build, workdir=tmp_path)


def test_storage_failure_still_delivers_and_warns(tmp_path: Path):
    repo, notifier = _repo_with_job(), FakeNotifier()

    def broken_upload(*_args):
        raise RuntimeError("storage down")

    repo.upload_asset = broken_upload
    client = ScriptedClient([_draft()], [[]])
    assert run_package(repo, Settings(), client, notifier, "job-1",
                       build_pdf=_fake_build, workdir=tmp_path) is True
    assert notifier.docs and "job-1" not in repo.packages
    assert [u["purpose"] for u in repo.usage] == ["package", "package"]  # cost still logged
    assert "Speichern in Supabase fehlgeschlagen" in notifier.sent[-1][0]
    assert len(notifier.docs) == 2  # CV and letter were delivered anyway


def test_usage_is_logged_even_when_the_pdf_build_fails(tmp_path: Path):
    repo = _repo_with_job()

    def broken_build(tex, photo, workdir, name="cv"):
        raise RuntimeError("LaTeX build failed")

    client = ScriptedClient([_draft()], [[]])
    with pytest.raises(RuntimeError):
        run_package(repo, Settings(), client, FakeNotifier(), "job-1",
                    build_pdf=broken_build, workdir=tmp_path)
    assert len(repo.usage) == 2 and repo.usage[0]["cost_usd"] > 0


def test_headline_and_summary_are_tailored_to_the_job():
    result, _ = _create([_draft(headline="Angehender Forward Deployed Engineer",
                                summary="Angehender Forward Deployed Engineer mit Python.")],
                        [[]])
    assert result.selection["headline"] == "Angehender Forward Deployed Engineer"
    assert result.selection["summary"].startswith("Angehender Forward Deployed Engineer")


def test_flagged_or_unsupported_headline_falls_back_to_the_profile_headline():
    one_flag = [{"target": "headline", "problem": "unbelegt"}]
    flagged, _ = _create([_draft()] * 3, [one_flag] * 3)
    assert flagged.selection["headline"] is None
    assert any(w.startswith("Überschrift durch Standardtext ersetzt") for w in flagged.warnings)
    invented, _ = _create(
        [_draft(headline="Angehender Kubernetes Engineer")] * 3, [[], [], []]
    )
    assert invented.selection["headline"] is None


def test_highlight_flag_is_guidance_for_the_model_not_a_forced_pick():
    import yaml
    profile = yaml.safe_load(PROFILE)
    profile["projects"][1]["highlight"] = True  # proj-y, which the draft did not pick
    sel = build_selection(Draft(**_draft()), profile)
    assert "proj-y" not in sel["bullets"] and sel["projects_chosen"] == ["proj-x"]
    assert "highlight: true" in INSTRUCTIONS and "EIN Projekt" in INSTRUCTIONS


def test_file_slug_makes_safe_ascii_names():
    assert file_slug("Max Mustermann") == "Max_Mustermann"
    assert file_slug("Müller & Söhne GmbH") == "Muller_Sohne_GmbH"
    assert file_slug("???") == "Datei"


def test_llm_items_without_a_real_verdict_are_ignored():
    flags = [{"target": "cover_letter", "problem": "ist belegt", "verdict": "belegt"}]
    result, _ = _create([_draft()], [flags])
    assert result.warnings == []


def test_warning_lists_at_most_three_letter_problems():
    from job_scout.package import MAX_WARNING_ISSUES

    flags = [
        {"target": "cover_letter", "problem": f"Fehler {n}", "verdict": "unbelegt"}
        for n in range(5)
    ]
    result, _ = _create([_draft()] * 3, [flags] * 3)
    assert len([w for w in result.warnings if w.startswith("Anschreiben")]) == MAX_WARNING_ISSUES


def test_initiative_job_text_asks_for_a_company_neutral_letter():
    from job_scout.package import job_text

    text = job_text({"company_name": "Beispiel AG", "title": "Initiativbewerbung", "url": "",
                     "kind": "initiative", "description": "Softwarehaus in Bonn."})
    assert "INITIATIVBEWERBUNG" in text and "Beispiel AG" in text
    assert "Softwarehaus in Bonn." in text
    assert "NICHTS über die Firma" in text


def test_package_can_be_built_for_an_unscored_initiative_job():
    from job_scout.package import run_package  # noqa: F401  (import check)

    repo = FakeRepo()
    repo.insert_jobs([{"source": "manual", "external_id": "x", "company_name": "Beispiel AG",
                       "title": "Initiativbewerbung", "url": "", "dedup_key": "manual|x",
                       "kind": "initiative"}])
    assert repo.package_job("job-1")["kind"] == "initiative"
    assert repo.package_job("missing") is None


def test_draft_message_carries_todays_date_and_tense_rule():
    from datetime import date

    from job_scout.package import INSTRUCTIONS, build_draft_user

    text = build_draft_user(JOB, None)
    assert text.startswith(f"Heutiges Datum: {date.today().isoformat()}")
    assert "Zeitform" in INSTRUCTIONS and "nie \"aktuell\"" in INSTRUCTIONS


def test_instructions_limit_the_thesis_to_one_sentence_and_ai_roles():
    assert "Bachelorarbeit" in INSTRUCTIONS and "genau EINEM" in INSTRUCTIONS
    assert "Keine Ergebnisse" in INSTRUCTIONS


def test_initiative_for_a_working_student_uses_the_part_time_rules():
    from job_scout.package import job_text

    job = {"company_name": "Beispiel AG", "title": "Initiativbewerbung", "url": "",
           "kind": "initiative", "description": "Werkstudent Informatik, Softwarehaus"}
    text = job_text(job)
    assert "INITIATIVBEWERBUNG" in text and "WERKSTUDENTENSTELLE" in text
    assert "WERKSTUDENTENSTELLE" not in job_text({**job, "description": "Softwarehaus"})


def test_a_second_rewrite_can_still_clean_up_the_letter():
    flags = [{"target": "cover_letter", "problem": "Führungserfahrung erfunden"}]
    result, client = _create([_draft()] * 3, [flags, flags, []])
    assert len([c for c in client.calls if c[0] == "submit_package"]) == 3
    assert result.warnings == []


def test_initiative_note_lets_the_company_notes_name_the_target_role():
    from job_scout.package import INITIATIVE_NOTE

    assert "Zielrolle Softwareentwickler" in INITIATIVE_NOTE
    assert "wähle keine andere" in INITIATIVE_NOTE


def test_english_note_is_added_only_for_english_packages():
    from job_scout.package import ENGLISH_NOTE, build_draft_user

    job = {"company_name": "MDIS Consulting", "title": "Initiativbewerbung", "url": "",
           "description": "x", "kind": "initiative"}
    assert ENGLISH_NOTE not in build_draft_user(job, None)
    text = build_draft_user(job, None, "en")
    assert ENGLISH_NOTE in text and "Dear Sir or Madam" in text and "gaps bleiben deutsch" in text
