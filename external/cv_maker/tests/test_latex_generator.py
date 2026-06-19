# Copyright 2026 Justin Cook
#
# Licensed under the Apache License, Version 2.0 (the "License");

import os
import tempfile
import unittest
from unittest.mock import patch

from cv_maker.latex_generator import McDowellLatexGenerator
from cv_maker.models import CVData, EarlierExperience, Experience


class TestMcDowellLatexGenerator(unittest.TestCase):
    def test_render_escapes_latex_and_uses_mcdowell_sections(self):
        data = CVData(
            name="Douglas Yang",
            title="AI Engineer",
            contact_info="Sydney | douglas@example.com | github.com/douglas_yang",
            executive_summary="Built AI & web systems with 90% reliability.",
            competencies=[("Languages:", "Python, C++, TypeScript")],
            experience=[
                Experience(
                    title="AI Engineer",
                    company="ACME & Co",
                    location="Sydney",
                    dates="2026 - Present",
                    summary_italic="Production AI systems",
                    bullets=[("Impact:", "Improved cost by 25% with C++ tooling.")],
                )
            ],
            earlier_experience=[
                EarlierExperience(
                    title="Junior Engineer",
                    company="Old Corp",
                    summary="Built internal tools.",
                    dates="2020 - 2021",
                )
            ],
            projects=[("Portfolio:", "github.com/douglas_yang/project")],
            education=["Master of IT"],
            certifications="AWS Certified",
            github_url="github.com/douglas_yang",
        )

        tex = McDowellLatexGenerator().render(data)

        self.assertIn("\\documentclass[]{mcdowellcv}", tex)
        self.assertIn("\\begin{cvsection}{Employment}", tex)
        self.assertNotIn("\\begin{cvsection}{Earlier Experience}", tex)
        self.assertIn("ACME \\& Co", tex)
        self.assertIn("\\begin{cvsubsection}[1]{Junior Engineer}{Old Corp}{2020 - 2021}", tex)
        self.assertIn("90\\% reliability", tex)
        self.assertIn("C++ tooling", tex)
        self.assertIn("\\begin{cvsection}{Education}", tex)
        self.assertIn("\\begin{cvsection}{Certifications}", tex)
        self.assertIn("\\begin{cvsection}{Languages and Technologies}", tex)
        self.assertLess(
            tex.index("\\begin{cvsection}{Education}"),
            tex.index("\\begin{cvsection}{Certifications}"),
        )
        self.assertLess(
            tex.index("\\begin{cvsection}{Certifications}"),
            tex.index("\\begin{cvsection}{Languages and Technologies}"),
        )
        self.assertIn("github.com/douglas\\_yang", tex)

    def test_certifications_are_separate_from_education(self):
        data = CVData(
            name="Douglas Yang",
            title="AI Engineer",
            contact_info="test@example.com",
            executive_summary="Summary.",
            competencies=[("Languages:", "Python")],
            experience=[],
            education=["Master of IT"],
            certifications="AWS Certified Cloud Practitioner | EDB Certified Essential PostgreSQL V13 DBA",
        )

        tex = McDowellLatexGenerator().render(data)

        education_section = tex[
            tex.index("\\begin{cvsection}{Education}"):
            tex.index("\\begin{cvsection}{Certifications}")
        ]
        certifications_section = tex[
            tex.index("\\begin{cvsection}{Certifications}"):
            tex.index("\\begin{cvsection}{Languages and Technologies}")
        ]

        self.assertNotIn("AWS Certified", education_section)
        self.assertIn("\\begin{cvsection}{Certifications}", certifications_section)
        self.assertIn("\\item AWS Certified Cloud Practitioner", certifications_section)
        self.assertIn("\\item EDB Certified Essential PostgreSQL V13 DBA", certifications_section)

    def test_long_left_title_is_compacted_and_dates_are_kept(self):
        data = CVData(
            name="Douglas Yang",
            title="AI Engineer",
            contact_info="test@example.com",
            executive_summary="Summary.",
            competencies=[],
            experience=[],
            earlier_experience=[
                EarlierExperience(
                    title="AI Assistant (National Crime Suppression System)",
                    company="Chinese Academy of Sciences",
                    summary="Validated CNN models.",
                    dates="06/2022 - 01/2023",
                )
            ],
        )

        tex = McDowellLatexGenerator().render(data)

        self.assertIn(
            "\\begin{cvsubsection}[1]{AI Assistant (NCSS)}{Chinese Academy of Sciences}{06/2022 - 01/2023}",
            tex,
        )
        self.assertNotIn("AI Assistant (National Crime Suppression System)", tex)

    def test_contact_info_puts_email_on_own_line(self):
        data = CVData(
            name="Douglas Yang",
            title="AI Engineer",
            contact_info="Sydney | 0421989935 | developer.douglas.yang@gmail.com | github.com/douglas_yang",
            executive_summary="Summary.",
            competencies=[],
            experience=[],
        )

        tex = McDowellLatexGenerator().render(data)

        self.assertIn("\\address{}", tex)
        self.assertIn(
            "\\contacts{Sydney \\linebreak 0421989935 \\linebreak developer.douglas.yang@gmail.com \\linebreak github.com/douglas\\_yang}",
            tex,
        )

    def test_header_contact_defaults_are_added_to_right_side(self):
        data = CVData(
            name="Douglas Yang",
            title="AI Engineer",
            contact_info="0421989935 | developer.douglas.yang@gmail.com",
            executive_summary="Summary.",
            competencies=[],
            experience=[],
        )

        with patch.dict(
            os.environ,
            {
                "CANDIDATE_ADDRESS": "108 Talavera St, Macquarie University, NSW 2113",
                "CANDIDATE_WEBSITE": "www.douglas-yang.com",
            },
            clear=False,
        ):
            tex = McDowellLatexGenerator().render(data)

        self.assertIn("\\address{}", tex)
        self.assertIn(
            "\\contacts{0421989935 \\linebreak developer.douglas.yang@gmail.com \\linebreak "
            "108 Talavera St, Macquarie University, NSW 2113 \\linebreak www.douglas-yang.com}",
            tex,
        )

    def test_env_address_replaces_address_from_contact_info(self):
        data = CVData(
            name="Douglas Yang",
            title="AI Engineer",
            contact_info=(
                "0421989935 | developer.douglas.yang@gmail.com | "
                "108 Talavera Road, Macquarie Uni, NSW 2109 | "
                "Macquarie Uni, NSW 2109 | www.douglas-yang.com"
            ),
            executive_summary="Summary.",
            competencies=[],
            experience=[],
        )

        with patch.dict(
            os.environ,
            {
                "CANDIDATE_ADDRESS": "108 Talavera St, Macquarie University, NSW 2113",
                "CANDIDATE_WEBSITE": "www.douglas-yang.com",
            },
            clear=False,
        ):
            tex = McDowellLatexGenerator().render(data)

        self.assertNotIn("108 Talavera Road, Macquarie Uni, NSW 2109", tex)
        self.assertNotIn("Macquarie Uni, NSW 2109", tex)
        self.assertIn(
            "\\contacts{0421989935 \\linebreak developer.douglas.yang@gmail.com \\linebreak "
            "108 Talavera St, Macquarie University, NSW 2113 \\linebreak www.douglas-yang.com}",
            tex,
        )
        self.assertEqual(tex.count("Talavera"), 1)

    def test_generate_writes_tex_without_compiling(self):
        data = CVData(
            name="Test User",
            title="Engineer",
            contact_info="test@example.com",
            executive_summary="Summary.",
            competencies=[],
            experience=[],
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "resume.tex")
            McDowellLatexGenerator().generate(data, output, compile_pdf=False)

            self.assertTrue(os.path.exists(output))
            self.assertTrue(os.path.exists(os.path.join(tmp, "mcdowellcv.cls")))
            with open(output, "r", encoding="utf-8") as f:
                self.assertIn("\\name{Test User}", f.read())


if __name__ == "__main__":
    unittest.main()
