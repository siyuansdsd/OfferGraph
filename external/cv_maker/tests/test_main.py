import unittest

from cv_maker.main import _cover_letter_output_path


class TestMainHelpers(unittest.TestCase):
    def test_cover_letter_output_path_for_docx(self):
        self.assertEqual(
            _cover_letter_output_path("user_content/generated_cvs/Role.docx"),
            "user_content/generated_cvs/Role_CoverLetter.docx",
        )

    def test_cover_letter_output_path_for_latex(self):
        self.assertEqual(
            _cover_letter_output_path("user_content/generated_cvs/Role.tex"),
            "user_content/generated_cvs/Role_CoverLetter.docx",
        )


if __name__ == "__main__":
    unittest.main()
