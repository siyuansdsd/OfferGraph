
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
Handles ingestion of text from various sources (URL, DOCX, PDF, Cloud Drives).
"""

import os
import requests
from bs4 import BeautifulSoup
from docx import Document
from typing import Dict
import gdown
from pypdf import PdfReader
from onedrivedownloader import download as onedrive_download
import urllib3
import logging

from cv_maker.ssl_helpers import get_ca_bundle

logger = logging.getLogger(__name__)

def read_docx(file_path: str) -> str:
    """
    Extracts text from a DOCX file.
    """
    try:
        doc = Document(file_path)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return '\n'.join(full_text)
    except Exception as e:
        logger.error(f"Error reading {file_path}: {e}")
        return ""

def _extract_text_from_html(html: str) -> str:
    """Extracts clean text from raw HTML content."""
    soup = BeautifulSoup(html, 'html.parser')

    # Kill all script and style elements
    for script in soup(["script", "style"]):
        script.decompose()

    text = soup.get_text()

    # Break into lines and remove leading/trailing space on each
    lines = (line.strip() for line in text.splitlines())
    # Break multi-headlines into a line each
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # Drop blank lines
    text = '\n'.join(chunk for chunk in chunks if chunk)
    return text


def _read_url_js(url: str) -> str:
    """
    Fetches and extracts text from a JS-heavy URL using Playwright (headless Chromium).
    Used as a fallback when plain requests + BeautifulSoup returns empty content.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "Playwright is not installed. Install it with:\n"
            "  pip install playwright && python -m playwright install chromium"
        )
        return ""

    logger.info(f"Falling back to headless browser for: {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)

            # Give dynamic content a moment to render
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()

        return _extract_text_from_html(html)

    except Exception as e:
        logger.error(f"Playwright extraction failed: {e}")
        return ""


def read_url(url: str) -> str:
    """
    Fetches and extracts text from a URL.
    First tries plain requests + BeautifulSoup; falls back to Playwright
    for JS-rendered pages (e.g. Seek, LinkedIn).
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        ca_bundle = get_ca_bundle()
        try:
            response = requests.get(url, headers=headers, timeout=10, verify=ca_bundle)
            response.raise_for_status()
        except requests.exceptions.SSLError:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.warning(f"SSL verification failed for {url}. Retrying without verification (Unsafe)...")
            response = requests.get(url, headers=headers, timeout=10, verify=False)
            response.raise_for_status()

        text = _extract_text_from_html(response.content)

        # If BS4 got meaningful content, return it
        if text and len(text) > 50:
            return text

        # Otherwise the site likely requires JS rendering
        logger.warning("Static fetch returned minimal content. Trying headless browser...")
        return _read_url_js(url)

    except Exception as e:
        logger.error(f"Static fetch failed ({e}). Trying headless browser...")
        return _read_url_js(url)

def read_pdf(file_path: str) -> str:
    """
    Extracts text from a PDF file.
    """
    try:
        reader = PdfReader(file_path)
        full_text = []
        for page in reader.pages:
            full_text.append(page.extract_text())
        return '\n'.join(full_text)
    except Exception as e:
        logger.error(f"Error reading PDF {file_path}: {e}")
        return ""

def read_pages(file_path: str) -> str:
    """
    Placeholder for extracting text from .pages files.
    """
    logger.warning(f".pages format support is experimental/limited. Please convert {os.path.basename(file_path)} to PDF or DOCX for best results.")
    return ""

def download_from_gdrive(url: str, output_dir: str):
    """
    Downloads a folder from Google Drive using gdown.
    """
    try:
        logger.info(f"Downloading from Google Drive: {url}")
        # Monkeypatch requests.Session.request to use the configured CA bundle
        # instead of blindly disabling verification.
        import requests.sessions
        original_request = requests.sessions.Session.request
        ca_bundle = get_ca_bundle()

        def patched_request(self, method, url, *args, **kwargs):
            kwargs['verify'] = ca_bundle
            return original_request(self, method, url, *args, **kwargs)

        requests.sessions.Session.request = patched_request

        try:
            # remaining_ok=True allows downloading up to the limit without error
            gdown.download_folder(url, output=output_dir, quiet=False, use_cookies=False, remaining_ok=True)
        except Exception as e:
             logger.error(f"Error downloading from Google Drive: {e}")
        finally:
            # Restore original
            requests.sessions.Session.request = original_request

    except Exception as e:
        logger.error(f"Error downloading from Google Drive: {e}")

def download_from_onedrive(url: str, output_dir: str):
    """
    Downloads files from a shared OneDrive link.
    """
    try:
        logger.info(f"Downloading from OneDrive: {url}")
        onedrive_download(url, filename=output_dir, unzip=True, clean=True)
    except Exception as e:
        logger.error(f"Error downloading from OneDrive: {e}")

def ingest_library(library_path: str) -> Dict[str, str]:
    """
    Scans a directory for .docx files and returns a dict {filename: content}.
    """
    library_content = {}
    
    # Check if library_path is a URL
    if library_path.startswith("http"):
        # Create a local cache directory
        cache_dir = "user_content/library_cache"
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        
        if "drive.google.com" in library_path:
            # Simple caching: if cache dir exists and has files, skip download
            if os.path.exists(cache_dir) and os.listdir(cache_dir):
                logger.info(f"Using cached library in {cache_dir}")
                logger.info("    (To force refresh, delete the 'library_cache' directory)")
            else:
                download_from_gdrive(library_path, cache_dir)
            
            library_path = cache_dir # Point to the cache now
        elif "1drv.ms" in library_path or "onedrive.live.com" in library_path:
            # Same for OneDrive
            if os.path.exists(cache_dir) and os.listdir(cache_dir):
                 logger.info(f"Using cached library in {cache_dir}")
            else:
                download_from_onedrive(library_path, cache_dir)
            library_path = cache_dir

    if not os.path.exists(library_path):
        logger.error(f"Library path not found: {library_path}")
        return library_content

    for root, _, files in os.walk(library_path):
        for file in files:
            full_path = os.path.join(root, file)
            content = ""
            
            if file.lower().endswith(".docx"):
                content = read_docx(full_path)
            elif file.lower().endswith(".pdf"):
                content = read_pdf(full_path)
            elif file.lower().endswith(".pages"):
                content = read_pages(full_path)
            
            if content:
                library_content[file] = content
    
    return library_content

def ingest_github(username: str) -> str:
    """
    Fetches public repositories for a GitHub user and returns a markdown summary.
    """
    api_url = f"https://api.github.com/users/{username}/repos?sort=updated&per_page=100"
    headers = {'Accept': 'application/vnd.github.v3+json'}
    
    # Optional: Use token if available to avoid rate limits
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers['Authorization'] = f"token {token}"
        
    try:
        logger.info(f"Fetching GitHub profile for: {username}")
        response = requests.get(api_url, headers=headers, timeout=10, verify=get_ca_bundle())
        
        if response.status_code == 404:
            logger.warning(f"GitHub user '{username}' not found.")
            return ""
        
        if response.status_code != 200:
            logger.error(f"GitHub API error: {response.status_code}")
            return ""
            
        repos = response.json()
        
        # Sort by stars (descending) and then integrity/recency
        # Let's filter for relevant ones (e.g., non-forks or impactful forks)
        # For now, take top 10 by stars
        sorted_repos = sorted(repos, key=lambda r: r.get('stargazers_count', 0), reverse=True)[:15]
        
        summary_lines = [f"## GitHub Portfolio ({username})"]
        
        for repo in sorted_repos:
            name = repo.get('name')
            desc = repo.get('description') or "No description"
            lang = repo.get('language') or "N/A"
            stars = repo.get('stargazers_count', 0)
            url = repo.get('html_url')
            updated = repo.get('updated_at', '')[:10]
            
            if repo.get('fork'):
                name += " (Fork)"
            
            summary_lines.append(f"- **[{name}]({url})** (★{stars} | {lang} | Updated: {updated}): {desc}")
            
        return "\n".join(summary_lines)
        
    except Exception as e:
        logger.error(f"Failed to ingest GitHub profile: {e}")
        return ""
