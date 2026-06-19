# Copyright 2026 Justin Cook
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""
LaTeX resume generation using the McDowell CV structure.

The bundled McDowell class is based on:
https://github.com/dnl-blkv/mcdowell-cv
MIT License, Copyright (c) 2015 Daniil Belyakov.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from cv_maker.models import CVData, EarlierExperience, Experience

logger = logging.getLogger(__name__)


_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_SUBSECTION_LEFT_TITLE_LIMIT = 28
_SUBSECTION_CENTER_TITLE_LIMIT = 31
_SUBSECTION_RIGHT_TITLE_LIMIT = 22


def _escape_latex(value: object) -> str:
    text = str(value or "")
    return "".join(_LATEX_SPECIAL_CHARS.get(char, char) for char in text)


def _latex_linebreak_text(value: str) -> str:
    parts = [part.strip() for part in str(value or "").splitlines() if part.strip()]
    return r" \linebreak ".join(_escape_latex(part) for part in parts)


def _contact_lines(value: str) -> list[str]:
    lines: list[str] = []
    for line in str(value or "").splitlines():
        parts = [part.strip() for part in line.split("|") if part.strip()]
        lines.extend(parts or ([line.strip()] if line.strip() else []))
    return lines


def _has_contact_value(lines: list[str], value: str) -> bool:
    needle = re.sub(r"\s+", "", str(value or "").lower())
    if not needle:
        return True
    return any(needle in re.sub(r"\s+", "", line.lower()) for line in lines)


def _looks_like_postal_address(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False

    lowered = text.lower()
    if "@" in lowered or re.search(r"\b(www\.|https?://|github\.com|linkedin\.com)\b", lowered):
        return False

    street_terms = (
        "street",
        "st",
        "road",
        "rd",
        "avenue",
        "ave",
        "drive",
        "dr",
        "lane",
        "ln",
        "place",
        "pl",
        "boulevard",
        "blvd",
        "court",
        "ct",
    )
    has_street_number = bool(re.search(r"\b\d{1,6}[A-Za-z]?\s+[A-Za-z]", text))
    has_street_term = bool(re.search(r"\b(" + "|".join(street_terms) + r")\.?\b", lowered))
    has_au_state_postcode = bool(re.search(r"\b(?:NSW|VIC|QLD|ACT|SA|WA|TAS|NT)\b\s+\d{4}\b", text))

    return has_au_state_postcode or (has_street_number and has_street_term)


def _normalized_website_domain(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = text.rstrip("/")
    if text.startswith("www."):
        text = text[4:]
    return text.split("/", 1)[0]


def _right_header_contacts(contact_info: str) -> str:
    lines = _contact_lines(contact_info)

    candidate_address = os.environ.get("CANDIDATE_ADDRESS", "").strip()
    candidate_website = os.environ.get("CANDIDATE_WEBSITE", "").strip()
    candidate_website_domain = _normalized_website_domain(candidate_website)

    if candidate_address:
        lines = [line for line in lines if not _looks_like_postal_address(line)]
    if candidate_website_domain:
        lines = [
            line for line in lines
            if _normalized_website_domain(line) != candidate_website_domain
        ]

    if candidate_address and not _has_contact_value(lines, candidate_address):
        lines.append(candidate_address)
    if candidate_website and not _has_contact_value(lines, candidate_website):
        lines.append(candidate_website)

    return "\n".join(lines)


def _abbreviate_phrase(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value or "")
    stop_words = {"and", "of", "the", "for", "to", "in", "on", "with"}
    initials = [word[0].upper() for word in words if word.lower() not in stop_words]
    if len(initials) >= 2:
        return "".join(initials)
    return ""


def _compact_left_title(value: str, limit: int = _SUBSECTION_LEFT_TITLE_LIMIT) -> str:
    title = str(value or "").strip()
    if len(title) <= limit:
        return title

    def replace_parenthetical(match):
        acronym = _abbreviate_phrase(match.group(1))
        return f" ({acronym})" if acronym else ""

    abbreviated = re.sub(r"\(([^()]*)\)", replace_parenthetical, title)
    abbreviated = re.sub(r"\s+", " ", abbreviated).strip()
    if abbreviated and len(abbreviated) <= limit:
        return abbreviated

    without_parenthetical = re.sub(r"\s*\([^()]*\)", "", title)
    without_parenthetical = re.sub(r"\s+", " ", without_parenthetical).strip()
    return without_parenthetical or abbreviated or title


def _estimated_header_lines(left: str, center: str, right: str) -> int:
    limits = (
        _SUBSECTION_LEFT_TITLE_LIMIT,
        _SUBSECTION_CENTER_TITLE_LIMIT,
        _SUBSECTION_RIGHT_TITLE_LIMIT,
    )
    values = (left, center, right)
    line_counts = []
    for text, limit in zip(values, limits):
        visible_len = len(str(text or ""))
        line_counts.append(max(1, (visible_len + limit - 1) // limit))
    return min(max(line_counts), 3)


def _itemize(items: list[str], indent: str = "\t\t\t") -> list[str]:
    if not items:
        return []

    lines = [f"{indent}\\begin{{itemize}}"]
    for item in items:
        if item.strip():
            lines.append(f"{indent}\t\\item {item}")
    lines.append(f"{indent}\\end{{itemize}}")
    return lines


class McDowellLatexGenerator:
    """Renders CVData into the McDowell CV LaTeX template."""

    def __init__(self, class_file: str | Path | None = None):
        self.class_file = Path(class_file) if class_file else Path(__file__).parent / "latex" / "mcdowellcv.cls"

    def generate(self, data: CVData, output_filename: str, compile_pdf: bool = True) -> str | None:
        output_path = Path(output_filename)
        if output_path.suffix.lower() not in {".tex", ".pdf"}:
            output_path = output_path.with_suffix(".tex")

        tex_path = output_path.with_suffix(".tex")
        tex_path.parent.mkdir(parents=True, exist_ok=True)
        tex_path.write_text(self.render(data), encoding="utf-8")

        class_target = tex_path.parent / "mcdowellcv.cls"
        if self.class_file.exists():
            shutil.copyfile(self.class_file, class_target)
        else:
            logger.warning(f"McDowell class file not found: {self.class_file}")

        logger.info(f"LaTeX CV generated successfully: {tex_path}")

        if not compile_pdf:
            return None

        pdf_path = self.compile(tex_path)
        return str(pdf_path) if pdf_path else None

    def compile(self, tex_path: Path) -> Path | None:
        lualatex = shutil.which("lualatex")
        if lualatex:
            return self._compile_lualatex(tex_path, lualatex)

        tectonic = shutil.which("tectonic")
        if tectonic:
            return self._compile_tectonic(tex_path, tectonic)

        logger.warning("No LaTeX compiler found; generated .tex only. Install Tectonic or BasicTeX, or compile in Overleaf.")
        return None

    def _compile_lualatex(self, tex_path: Path, lualatex: str) -> Path | None:
        try:
            for _ in range(2):
                subprocess.run(
                    [lualatex, "-interaction=nonstopmode", tex_path.name],
                    cwd=str(tex_path.parent),
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=90,
                )
            pdf_path = tex_path.with_suffix(".pdf")
            logger.info(f"LaTeX PDF generated successfully: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"LuaLaTeX PDF compilation failed: {e}")
            return None

    def _compile_tectonic(self, tex_path: Path, tectonic: str) -> Path | None:
        try:
            subprocess.run(
                [tectonic, tex_path.name],
                cwd=str(tex_path.parent),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
            pdf_path = tex_path.with_suffix(".pdf")
            logger.info(f"Tectonic PDF generated successfully: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"Tectonic PDF compilation failed: {e}")
            return None

    def render(self, data: CVData) -> str:
        address, contacts = self._split_contact_info(data.contact_info)
        lines = [
            "%% Generated by CV Maker.",
            "%% McDowell CV class: MIT License, Copyright (c) 2015 Daniil Belyakov.",
            "\\documentclass[]{mcdowellcv}",
            "\\usepackage{amsmath}",
            "",
            f"\\name{{{_escape_latex(data.name)}}}",
            f"\\address{{{_latex_linebreak_text(address)}}}",
            f"\\contacts{{{_latex_linebreak_text(contacts)}}}",
            "",
            "\\begin{document}",
            "\t\\makeheader",
        ]

        lines.extend(self._summary_section(data))
        lines.extend(self._experience_section(data))
        lines.extend(self._projects_section(data))
        lines.extend(self._education_section(data))
        lines.extend(self._certifications_section(data))
        lines.extend(self._competencies_section(data))

        lines.append("\\end{document}")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _split_contact_info(contact_info: str) -> tuple[str, str]:
        return "", _right_header_contacts(contact_info)

    def _summary_section(self, data: CVData) -> list[str]:
        if not data.executive_summary:
            return []
        return [
            "\t\\begin{cvsection}{Executive Summary}",
            "\t\t\\begin{cvsubsection}{}{}{}",
            f"\t\t\t{_escape_latex(data.executive_summary)}",
            "\t\t\\end{cvsubsection}",
            "\t\\end{cvsection}",
        ]

    def _experience_section(self, data: CVData) -> list[str]:
        lines: list[str] = []
        if not data.experience and not data.earlier_experience:
            return lines

        lines.append("\t\\begin{cvsection}{Employment}")
        for job in data.experience:
            lines.extend(self._experience_entry(job))
        for job in data.earlier_experience:
            lines.extend(self._earlier_experience_entry(job))
        lines.append("\t\\end{cvsection}")

        return lines

    def _experience_entry(self, job: Experience) -> list[str]:
        raw_left = _compact_left_title(job.title)
        raw_center = str(job.company or "")
        raw_right = str(job.dates or "")
        left = _escape_latex(raw_left)
        center = _escape_latex(raw_center)
        right = _escape_latex(raw_right)
        header_lines = _estimated_header_lines(raw_left, raw_center, raw_right)
        lines = [f"\t\t\\begin{{cvsubsection}}[{header_lines}]{{{left}}}{{{center}}}{{{right}}}"]
        context_parts = [part for part in [job.location, job.summary_italic] if part]
        if context_parts:
            lines.append(f"\t\t\t{_escape_latex(' - '.join(context_parts))}")

        bullet_lines = []
        for title, desc in job.bullets:
            title_text = _escape_latex(title).strip()
            desc_text = _escape_latex(desc).strip()
            if title_text and desc_text:
                bullet_lines.append(f"\\textbf{{{title_text}}} {desc_text}")
            else:
                bullet_lines.append(title_text or desc_text)
        lines.extend(_itemize(bullet_lines))
        lines.append("\t\t\\end{cvsubsection}")
        return lines

    def _earlier_experience_entry(self, job: EarlierExperience) -> list[str]:
        raw_left = _compact_left_title(job.title)
        raw_center = str(job.company or "")
        raw_right = str(job.dates or "")
        header_lines = _estimated_header_lines(raw_left, raw_center, raw_right)
        lines = [
            f"\t\t\\begin{{cvsubsection}}[{header_lines}]{{{_escape_latex(raw_left)}}}{{{_escape_latex(raw_center)}}}{{{_escape_latex(raw_right)}}}"
        ]
        if job.summary:
            lines.append(f"\t\t\t{_escape_latex(job.summary)}")
        lines.append("\t\t\\end{cvsubsection}")
        return lines

    def _projects_section(self, data: CVData) -> list[str]:
        if not data.projects:
            return []

        project_items = []
        if data.github_url:
            project_items.append(f"Visible at: {_escape_latex(data.github_url)}")
        for title, desc in data.projects:
            title_text = _escape_latex(title).strip()
            desc_text = _escape_latex(desc).strip()
            if title_text and desc_text:
                project_items.append(f"\\textbf{{{title_text}}} {desc_text}")
            else:
                project_items.append(title_text or desc_text)

        lines = [
            "\t\\begin{cvsection}{Technical Experience}",
            "\t\t\\begin{cvsubsection}{Projects}{}{}",
        ]
        lines.extend(_itemize(project_items))
        lines.extend(["\t\t\\end{cvsubsection}", "\t\\end{cvsection}"])
        return lines

    def _education_section(self, data: CVData) -> list[str]:
        if not data.education:
            return []

        items = [_escape_latex(edu) for edu in data.education]
        lines = [
            "\t\\begin{cvsection}{Education}",
            "\t\t\\begin{cvsubsection}{}{}{}",
        ]
        lines.extend(_itemize(items))
        lines.extend(["\t\t\\end{cvsubsection}", "\t\\end{cvsection}"])
        return lines

    def _certifications_section(self, data: CVData) -> list[str]:
        if not data.certifications:
            return []

        raw_items = [
            item.strip()
            for item in re.split(r"\s*(?:\||;|\n)\s*", str(data.certifications))
            if item.strip()
        ]
        items = [_escape_latex(item) for item in raw_items] or [_escape_latex(data.certifications)]

        lines = [
            "\t\\begin{cvsection}{Certifications}",
            "\t\t\\begin{cvsubsection}{}{}{}",
        ]
        lines.extend(_itemize(items))
        lines.extend(["\t\t\\end{cvsubsection}", "\t\\end{cvsection}"])
        return lines

    def _competencies_section(self, data: CVData) -> list[str]:
        if not data.competencies:
            return []

        items = []
        for category, skills in data.competencies:
            category_text = _escape_latex(category).strip()
            skills_text = _escape_latex(skills).strip()
            if category_text and skills_text:
                items.append(f"\\textbf{{{category_text}}} {skills_text}")
            else:
                items.append(category_text or skills_text)

        lines = [
            "\t\\begin{cvsection}{Languages and Technologies}",
            "\t\t\\begin{cvsubsection}{}{}{}",
        ]
        lines.extend(_itemize(items))
        lines.extend(["\t\t\\end{cvsubsection}", "\t\\end{cvsection}"])
        return lines
