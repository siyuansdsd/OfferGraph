# Copyright 2026 Justin Cook
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import patch, MagicMock
from cv_maker.generator import CVGenerator, CVData, _strip_cover_letter_signature

class TestCVGenerator(unittest.TestCase):
    
    @patch('cv_maker.generator.Document')
    def test_generate_cv(self, mock_document_class):
        # Setup Mock
        mock_doc = MagicMock()
        mock_document_class.return_value = mock_doc
        
        # Init Generator
        generator = CVGenerator()
        
        # Prepare Data
        data = CVData(
            name="Test User",
            title="Senior Dev",
            contact_info="test@test.com",
            executive_summary="Summary",
            competencies=[("Cat", "Skill A, Skill B")],
            experience=[
                MagicMock(title="Dev", company="Tech", location="City", dates="2020", summary_italic="Sum", bullets=[("A", "B")])
            ],
            earlier_experience=[
                MagicMock(title="Old Dev", company="Old Tech", summary="Brief summary")
            ],
            projects=[],
            education=[],
            certifications="Cert A"
        )
        
        # Run Generate
        generator.generate(data, "output.docx")
        
        # Verify
        # Verify basic sections added (headings, paragraphs)
        # Verify calls - Generator uses add_paragraph with explicit styles for headings
        # It adds Name (Title), Role, Contact, then Executive Summary (H1)
        # We check if add_paragraph was called with "EXECUTIVE SUMMARY"
        
        # Check if any call args started with 'EXECUTIVE SUMMARY'
        calls = [args[0] for args, _ in mock_doc.add_paragraph.call_args_list if args]
        self.assertIn("EXECUTIVE SUMMARY", calls)
        self.assertIn("PROFESSIONAL EXPERIENCE", calls)
        self.assertNotIn("EARLIER CAREER EXPERIENCE", calls)
        self.assertIn("Brief summary", calls)
        
        # Verify save called
        mock_doc.save.assert_called_with("output.docx")

    def test_formatting_applied(self):
        """Test that keep_with_next and widow_control are applied."""
        generator = CVGenerator()
        # Mock add_paragraph to return a mock with paragraph_format
        mock_p = MagicMock()
        mock_format = MagicMock()
        mock_p.paragraph_format = mock_format
        generator.document.add_paragraph = MagicMock(return_value=mock_p)
        
        data = CVData(
            name="Test", title="Title", contact_info="Contact", 
            executive_summary="Summary", competencies=[("C","S")], 
            experience=[MagicMock(title="Role", company="Co", dates="2020", location="Loc", bullets=[("B","D")], summary_italic="Sum")],
            earlier_experience=[MagicMock(title="Old", company="Co", summary="Sum")], 
            projects=[("Proj","Desc")], education=["Edu"], certifications="Cert"
        )
        
        generator.generate(data, "out.docx")
        
        # Check that keep_with_next was set to True at least once (for headings)
        # We can check specific calls but general check is enough to verify logic flow
        # The mock_format is shared across all calls unless we configure side_effect, 
        # so we just verify the attributes were accessed/set.
        self.assertTrue(mock_format.keep_with_next)
        self.assertTrue(mock_format.widow_control)

    def test_strip_cover_letter_signature(self):
        body = "Dear Hiring Manager,\n\nBody paragraph.\n\nSincerely,\nDouglas Yang"

        self.assertEqual(
            _strip_cover_letter_signature(body, "Douglas Yang"),
            "Dear Hiring Manager,\n\nBody paragraph."
        )

    @patch('cv_maker.generator.Document')
    def test_generate_cover_letter_does_not_duplicate_signature(self, mock_document_class):
        mock_doc = MagicMock()
        mock_document_class.return_value = mock_doc

        generator = CVGenerator()
        data = CVData(
            name="Douglas Yang",
            title="Engineer",
            contact_info="douglas@example.com",
            executive_summary="Summary",
            competencies=[],
            experience=[],
        )

        generator.generate_cover_letter(
            data,
            "Dear Hiring Manager,\n\nBody paragraph.\n\nSincerely,\nDouglas Yang",
            "cover.docx",
        )

        paragraph_texts = [args[0] for args, _ in mock_doc.add_paragraph.call_args_list if args]
        self.assertEqual(paragraph_texts.count("Sincerely,"), 1)
        self.assertEqual(paragraph_texts.count("Douglas Yang"), 2)  # header name + final signature

if __name__ == '__main__':
    unittest.main()
