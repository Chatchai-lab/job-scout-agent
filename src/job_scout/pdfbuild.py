"""Compile the rendered CV LaTeX to PDF with Tectonic (preferred) or pdflatex."""

import shutil
import subprocess
from pathlib import Path


def _engine_commands(tex_name: str) -> list[list[str]]:
    if shutil.which("tectonic"):
        return [["tectonic", tex_name]]
    if shutil.which("pdflatex"):
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_name]
        return [cmd, cmd]  # twice for stable layout
    raise RuntimeError("No LaTeX engine found (install tectonic or texlive)")


def error_lines(output: str) -> str:
    """Only the engine's own error lines. Context lines can contain CV text (contact data),
    and Actions logs of this public repo must never show that."""
    lines = [ln.strip() for ln in output.splitlines() if ln.startswith("!") or "error:" in ln]
    return "\n".join(lines[:6]) or "no error line found"


def build_pdf(tex: str, photo: bytes | None, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "cv.tex").write_text(tex, encoding="utf-8")
    if photo:
        (workdir / "photo.jpg").write_bytes(photo)
    for cmd in _engine_commands("cv.tex"):
        run = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=240)
        if run.returncode != 0:
            raise RuntimeError("LaTeX build failed: " + error_lines(run.stdout + run.stderr))
    pdf = workdir / "cv.pdf"
    if not pdf.exists():
        raise RuntimeError("LaTeX build produced no PDF")
    return pdf
