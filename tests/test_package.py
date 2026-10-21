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
    result, _ = _create([_draft()], [flags])
    assert result.selection["rewrites"] == {}
    assert result.selection["summary"] is None  # renderer falls back to the profile summary


def test_letter_with_invented_number_is_regenerated_once():
    invented = _draft(cover_letter=INVENTED)
    result, client = _create([invented, _draft()], [[], []])
    assert result.cover_letter == LETTER.strip()
    assert result.warnings == []
    second_request = [content for name, content in client.calls if name == "submit_package"][1]
    assert "unbelegte Angaben" in second_request and "'7'" in second_request


def test_letter_still_unsupported_after_retry_is_delivered_with_warning():
    invented = _draft(cover_letter=INVENTED)
    result, _ = _create([invented, invented], [[], []])
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
    assert repo.uploads[("cv-assets", "packages/job-1.pdf")] == (b"%PDF-1.4 cv", "application/pdf")
    assert repo.uploads[("cv-assets", "packages/job-1-anschreiben.pdf")][0] == b"%PDF-1.4 letter"
    assert repo.packages["job-1"]["cv_pdf_path"] == "packages/job-1.pdf"
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
    flagged, _ = _create([_draft()], [[{"target": "headline", "problem": "unbelegt"}]])
    assert flagged.selection["headline"] is None
    invented, _ = _create([_draft(headline="Angehender Kubernetes Engineer")], [[]])
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
