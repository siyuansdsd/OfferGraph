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
import os
import shutil
import tempfile
from cv_maker import ingest

class TestIngest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_read_docx(self):
        # Difficult to test docx reading without a real file or complex mocking of docx.Document
        # For now, we trust python-docx works and test the logic flow if possible, 
        # or just ensure it handles missing files gracefully.
        content = ingest.read_docx(os.path.join(self.test_dir, "nonexistent.docx"))
        self.assertEqual(content, "")

    @patch('cv_maker.ingest.requests.get')
    def test_read_url(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<html><body><p>Hello World. This is a longer text to satisfy the minimum length requirement for static fetch success.</p></body></html>"
        mock_get.return_value = mock_response

        text = ingest.read_url("http://example.com")
        self.assertIn("Hello World", text)

    @patch('cv_maker.ingest.gdown.download_folder')
    def test_download_from_gdrive(self, mock_download):
        url = "https://drive.google.com/drive/folders/123"
        ingest.download_from_gdrive(url, self.test_dir)
        mock_download.assert_called_once()

    @patch('cv_maker.ingest.onedrive_download')
    def test_download_from_onedrive(self, mock_download):
        url = "https://1drv.ms/f/s!Ap..."
        ingest.download_from_onedrive(url, self.test_dir)
        mock_download.assert_called_once()
