
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

"""
Centralised SSL/TLS CA bundle resolution for proxy environments.

Checks (in priority order):
  1. Explicit override via --ca-bundle CLI arg
  2. REQUESTS_CA_BUNDLE environment variable
  3. CURL_CA_BUNDLE environment variable
  4. SSL_CERT_FILE environment variable
  5. System defaults (True — delegates to certifi / OS trust store)
"""

import os
import logging

logger = logging.getLogger(__name__)

# Module-level override set by the CLI --ca-bundle flag
_ca_bundle_override: str | None = None


def set_ca_bundle_override(path: str) -> None:
    """Set an explicit CA bundle path from a CLI argument."""
    global _ca_bundle_override
    _ca_bundle_override = path
    logger.info(f"CA bundle override set to: {path}")


def get_ca_bundle() -> str | bool:
    """
    Resolve the CA bundle to use for outbound HTTPS requests.

    Returns:
        str: Absolute path to a CA bundle file, or
        bool: True to use the default system/certifi trust store.
    """
    # 1. CLI override takes highest priority
    if _ca_bundle_override:
        return _ca_bundle_override

    # 2-4. Check standard environment variables
    for var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
        value = os.environ.get(var)
        if value:
            logger.debug(f"Using CA bundle from {var}: {value}")
            return value

    # 5. Default: use system trust store
    return True


def configure_ssl_env() -> None:
    """
    Ensure SSL_CERT_FILE is set in the process environment when a custom
    CA bundle is configured.  This is needed for httpx-based SDKs
    (Google GenAI, OpenAI) that read SSL_CERT_FILE directly.
    """
    bundle = get_ca_bundle()
    if isinstance(bundle, str):
        # Only set if not already pointing to the same value
        if os.environ.get("SSL_CERT_FILE") != bundle:
            os.environ["SSL_CERT_FILE"] = bundle
            logger.debug(f"Set SSL_CERT_FILE={bundle} for SDK clients")
