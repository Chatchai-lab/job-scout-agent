import subprocess
from types import SimpleNamespace

import pytest

from job_scout import pdfbuild


def test_no_engine_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(pdfbuild.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="No LaTeX engine"):
        pdfbuild.build_pdf("x", None, tmp_path)


def test_pdflatex_runs_twice_and_returns_the_pdf(monkeypatch, tmp_path):
    only = "pdflatex"
    monkeypatch.setattr(pdfbuild.shutil, "which", lambda n: f"/usr/bin/{n}" if n == only else None)
    calls = []

    def fake_run(cmd, cwd, **_kw):
        calls.append(cmd[0])
        (cwd / "cv.pdf").write_bytes(b"%PDF")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf = pdfbuild.build_pdf("tex", b"jpg", tmp_path)
    assert pdf.name == "cv.pdf" and calls == ["pdflatex", "pdflatex"]
    assert (tmp_path / "photo.jpg").read_bytes() == b"jpg"


def test_build_error_shows_only_error_lines_never_cv_text(monkeypatch, tmp_path):
    only = "tectonic"
    monkeypatch.setattr(pdfbuild.shutil, "which", lambda n: f"/usr/bin/{n}" if n == only else None)
    output = "! Undefined control sequence.\nl.12 Wohnt in Musterstr. 1, 12345 Musterstadt\n"
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout=output, stderr=""))
    with pytest.raises(RuntimeError) as err:
        pdfbuild.build_pdf("tex", None, tmp_path)
    assert "Undefined control sequence" in str(err.value)
    assert "Musterstr" not in str(err.value)
