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
from unittest.mock import patch
import os

from cv_maker import ssl_helpers


class TestGetCaBundle(unittest.TestCase):
    """Test CA bundle resolution priority."""

    def setUp(self):
        # Reset any module-level override between tests
        ssl_helpers._ca_bundle_override = None

    def tearDown(self):
        ssl_helpers._ca_bundle_override = None

    def test_default_returns_true(self):
        """With no env vars and no override, system defaults are used."""
        with patch.dict(os.environ, {}, clear=True):
            result = ssl_helpers.get_ca_bundle()
            self.assertIs(result, True)

    def test_ssl_cert_file(self):
        """SSL_CERT_FILE is honoured as lowest-priority env var."""
        with patch.dict(os.environ, {"SSL_CERT_FILE": "/path/ssl.pem"}, clear=True):
            self.assertEqual(ssl_helpers.get_ca_bundle(), "/path/ssl.pem")

    def test_curl_ca_bundle_beats_ssl_cert_file(self):
        """CURL_CA_BUNDLE takes precedence over SSL_CERT_FILE."""
        with patch.dict(os.environ, {
            "SSL_CERT_FILE": "/path/ssl.pem",
            "CURL_CA_BUNDLE": "/path/curl.pem",
        }, clear=True):
            self.assertEqual(ssl_helpers.get_ca_bundle(), "/path/curl.pem")

    def test_requests_ca_bundle_beats_all_env(self):
        """REQUESTS_CA_BUNDLE takes precedence over other env vars."""
        with patch.dict(os.environ, {
            "SSL_CERT_FILE": "/path/ssl.pem",
            "CURL_CA_BUNDLE": "/path/curl.pem",
            "REQUESTS_CA_BUNDLE": "/path/requests.pem",
        }, clear=True):
            self.assertEqual(ssl_helpers.get_ca_bundle(), "/path/requests.pem")

    def test_cli_override_beats_everything(self):
        """set_ca_bundle_override takes highest priority."""
        with patch.dict(os.environ, {
            "REQUESTS_CA_BUNDLE": "/path/requests.pem",
        }, clear=True):
            ssl_helpers.set_ca_bundle_override("/path/cli.pem")
            self.assertEqual(ssl_helpers.get_ca_bundle(), "/path/cli.pem")


class TestSetCaBundleOverride(unittest.TestCase):
    def setUp(self):
        ssl_helpers._ca_bundle_override = None

    def tearDown(self):
        ssl_helpers._ca_bundle_override = None

    def test_sets_module_variable(self):
        ssl_helpers.set_ca_bundle_override("/my/bundle.pem")
        self.assertEqual(ssl_helpers._ca_bundle_override, "/my/bundle.pem")


class TestConfigureSslEnv(unittest.TestCase):
    def setUp(self):
        ssl_helpers._ca_bundle_override = None

    def tearDown(self):
        ssl_helpers._ca_bundle_override = None

    def test_sets_ssl_cert_file_when_custom_bundle(self):
        """When a custom CA bundle is configured, SSL_CERT_FILE is set for httpx SDKs."""
        ssl_helpers.set_ca_bundle_override("/my/custom.pem")
        with patch.dict(os.environ, {}, clear=True):
            ssl_helpers.configure_ssl_env()
            self.assertEqual(os.environ.get("SSL_CERT_FILE"), "/my/custom.pem")

    def test_no_op_when_default(self):
        """When using system defaults (True), SSL_CERT_FILE should not be set."""
        with patch.dict(os.environ, {}, clear=True):
            ssl_helpers.configure_ssl_env()
            self.assertNotIn("SSL_CERT_FILE", os.environ)


if __name__ == '__main__':
    unittest.main()
