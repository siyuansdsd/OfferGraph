
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
Client for interacting with Large Language Models (LLMs).
Supports Google Vertex AI, Google AI Studio, OpenAI, and MiniMax.
"""

import os
import json
import time
import logging
import re
from pathlib import Path
from typing import List
from cv_maker.models import CVData, JobDescription, Experience, EarlierExperience
from cv_maker.ssl_helpers import configure_ssl_env

# Logger is configured in main.py
logger = logging.getLogger(__name__)

MINIMAX_BASE_URL = "https://api.minimax.io/v1"
MINIMAX_ANTHROPIC_BASE_URL = "https://api.minimax.io/anthropic"
MINIMAX_DEFAULT_MODEL = "MiniMax-M2.7"

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")
_TITLE_ROLE_TERMS = {
    "administrator",
    "analyst",
    "architect",
    "ceo",
    "cfo",
    "cio",
    "consultant",
    "cto",
    "developer",
    "devops",
    "director",
    "engineer",
    "head",
    "lead",
    "manager",
    "programmer",
    "scientist",
    "specialist",
    "sre",
    "vp",
}
_TITLE_TOKEN_SYNONYMS = {
    "ai": {"artificial", "intelligence", "ml", "machine", "learning", "llm", "genai"},
    "artificial": {"ai", "intelligence"},
    "intelligence": {"ai", "artificial"},
    "ml": {"ai", "machine", "learning"},
    "machine": {"ai", "ml", "learning"},
    "learning": {"ai", "ml", "machine"},
    "developer": {"engineer", "software", "programmer", "web"},
    "engineer": {"developer", "software"},
    "software": {"developer", "engineer", "programmer"},
    "web": {"developer", "frontend", "front", "end", "javascript", "typescript", "react", "vue", "angular", "html", "css"},
    "frontend": {"front", "end", "web", "ui", "react", "vue", "angular", "javascript", "typescript", "html", "css"},
    "front": {"frontend", "web", "ui"},
    "backend": {"back", "end", "api", "server", "node", "python"},
    "fullstack": {"full", "stack", "frontend", "backend", "web"},
    "full": {"fullstack", "stack"},
    "stack": {"fullstack", "full"},
    "cloud": {"aws", "gcp", "azure"},
}

class LLMClient:
    """
    Abstraction layer for LLM providers.
    Handles prompted requests for CV analysis and tailoring.
    """
    def __init__(self, provider: str = "auto", model: str = None):
        self.model = model
        self.cache_file = Path("user_content/.model_cache.json")
        self._vertex_region_cache = {}

        # Resolve 'auto' to a concrete provider based on available credentials
        if provider == "auto":
            provider = self._resolve_auto_provider()

        self.provider = provider

        # Set api_key for the resolved provider
        if self.provider == "openai":
            self.api_key = os.environ.get("OPENAI_API_KEY")
        elif self.provider == "minimax":
            self.api_key = os.environ.get("MINIMAX_API_KEY")
        elif self.provider in ("gemini", "vertex"):
            self.api_key = os.environ.get("GEMINI_API_KEY")
        else:
            self.api_key = (
                os.environ.get("GEMINI_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("MINIMAX_API_KEY")
            )

        if not self.api_key and self.provider not in ["vertex", "github", "anthropic"]:
            logger.warning("No API key found. LLM features will fallback to Mock Data.")

        logger.info(f"LLMClient initialised: provider={self.provider}, model={self.model or 'auto-select'}")

    @staticmethod
    def _tokens(text: str) -> set[str]:
        normalized = (text or "").lower()
        normalized = normalized.replace("front-end", "frontend")
        normalized = normalized.replace("back-end", "backend")
        normalized = normalized.replace("full-stack", "fullstack")
        return set(_TOKEN_RE.findall(normalized))

    @classmethod
    def _expanded_tokens(cls, text: str) -> set[str]:
        tokens = cls._tokens(text)
        expanded = set(tokens)
        for token in tokens:
            expanded.update(_TITLE_TOKEN_SYNONYMS.get(token, set()))
        return expanded

    @staticmethod
    def _split_slash_title(title: str) -> List[str]:
        title = str(title or "").strip()
        if "/" not in title:
            return [title]

        options = []
        current = []
        for index, char in enumerate(title):
            if char != "/":
                current.append(char)
                continue

            left = "".join(current).strip()
            right = title[index + 1:].split("/", 1)[0].strip()
            has_spaced_slash = (
                (index > 0 and title[index - 1].isspace())
                or (index + 1 < len(title) and title[index + 1].isspace())
            )
            has_role_titles = (
                LLMClient._tokens(left) & _TITLE_ROLE_TERMS
                and LLMClient._tokens(right) & _TITLE_ROLE_TERMS
            )

            if has_spaced_slash or has_role_titles:
                cleaned = left.strip(" \t\r\n-–—,")
                if cleaned:
                    options.append(cleaned)
                current = []
            else:
                current.append(char)

        remainder = "".join(current).strip(" \t\r\n-–—,")
        if remainder:
            options.append(remainder)
        return options if len(options) > 1 else [title]

    @classmethod
    def _select_relevant_title(cls, title: str, jd: JobDescription) -> str:
        options = cls._split_slash_title(title)
        if len(options) == 1:
            return options[0]

        role_text = jd.role_title or jd.summary or ""
        skill_text = " ".join(jd.key_skills or [])
        summary_text = jd.summary or ""
        raw_text = (jd.raw_text or "")[:4000]

        role_tokens = cls._tokens(role_text)
        role_expanded = cls._expanded_tokens(role_text)
        skill_expanded = cls._expanded_tokens(skill_text)
        summary_expanded = cls._expanded_tokens(summary_text)
        raw_expanded = cls._expanded_tokens(raw_text)
        role_phrase = role_text.lower().strip()

        best_option = options[0]
        best_score = None
        for option in options:
            option_lower = option.lower()
            option_tokens = cls._tokens(option)
            option_expanded = cls._expanded_tokens(option)

            score = 0
            if role_phrase and (option_lower in role_phrase or role_phrase in option_lower):
                score += 40
            score += 15 * len(option_tokens & role_tokens)
            score += 5 * len(option_expanded & role_expanded)
            score += 3 * len(option_expanded & skill_expanded)
            score += 2 * len(option_expanded & summary_expanded)
            score += len(option_expanded & raw_expanded)

            if best_score is None or score > best_score:
                best_option = option
                best_score = score

        if best_option != title:
            logger.debug(f"Selected slash-separated title '{best_option}' from '{title}' for target role '{jd.role_title}'")
        return best_option

    @classmethod
    def _select_role_title_for_company(cls, title: str, company: str, jd: JobDescription) -> str:
        company_tokens = cls._tokens(company)
        if {"inspected", "pty", "ltd"}.issubset(company_tokens):
            return cls._select_relevant_title("Full Stack Developer / Principal AI Engineer", jd)
        return cls._select_relevant_title(title, jd)

    def _resolve_auto_provider(self) -> str:
        """
        Detects the best provider from available credentials.
        Explicit API keys take precedence over ambient GCP credentials (ADC).
        """
        has_openai = bool(os.environ.get("OPENAI_API_KEY"))
        has_minimax = bool(os.environ.get("MINIMAX_API_KEY"))
        has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
        has_gcp = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")) or self._has_adc()

        if has_minimax and not has_openai and not has_gemini and not has_gcp:
            logger.info("Auto-detected provider: minimax (MINIMAX_API_KEY found)")
            return "minimax"
        if has_openai and not has_gemini and not has_gcp:
            logger.info("Auto-detected provider: openai (OPENAI_API_KEY found)")
            return "openai"
        if has_gemini:
            logger.info("Auto-detected provider: gemini (GEMINI_API_KEY found)")
            return "gemini"
        if has_openai:
            # OpenAI key present alongside GCP credentials — prefer explicit key
            logger.info("Auto-detected provider: openai (OPENAI_API_KEY found)")
            return "openai"
        if has_minimax:
            logger.info("Auto-detected provider: minimax (MINIMAX_API_KEY found)")
            return "minimax"
        if has_gcp:
            logger.info("Auto-detected provider: vertex (GCP credentials found)")
            return "vertex"

        logger.debug("No provider credentials detected; staying in auto mode.")
        return "auto"

    def _load_cache(self) -> List[str]:
        """Loads valid models from local cache if less than 24h old."""
        try:
            if not self.cache_file.exists():
                return []
            
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
            
            # Check expiry (24 hours = 86400 seconds)
            if time.time() - data.get("timestamp", 0) > 86400:
                logger.info("Model cache expired.")
                return []
            
            return data.get("models", [])
        except Exception as e:
            logger.warning(f"Failed to load model cache: {e}")
            return []

    def _save_cache(self, models: List[str]):
        """Saves discovered models to local cache."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump({
                    "timestamp": time.time(),
                    "models": models
                }, f)
        except Exception as e:
            logger.warning(f"Failed to save model cache: {e}")

    def _attempt_with_retry(self, generate_func, model_name, prompt, max_retries=3, base_delay=2.0) -> str:
        """Attempts to call a model with exponential backoff on transient errors."""
        for attempt in range(max_retries):
            try:
                return generate_func(model_name, prompt)
            except Exception as e:
                error_msg = str(e).lower()
                # Do not retry for model not found or invalid inputs
                unrecoverable = ["not found", "404", "invalid", "does not exist", "400", "bad request"]
                if any(x in error_msg for x in unrecoverable) or attempt == max_retries - 1:
                    logger.warning(f"Model {model_name} failed (attempt {attempt + 1}/{max_retries}): {e}")
                    raise
                
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Model {model_name} encountered transient error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay}s...")
                time.sleep(delay)

    def _has_adc(self) -> bool:
        """Checks if Google Application Default Credentials are valid."""
        try:
            import google.auth
            credentials, _ = google.auth.default()
            return credentials is not None
        except Exception:
            return False

    def _get_vertex_models_for_region(self, region: str) -> List[str]:
        """Dynamically discovers and caches models available in a specific Vertex AI region."""
        if region in self._vertex_region_cache:
            return self._vertex_region_cache[region]
            
        try:
            import warnings
            from google import genai
            import os
            
            with warnings.catch_warnings():
                 warnings.filterwarnings("ignore", category=UserWarning, module="google.genai")
                 _temp_api_key = os.environ.pop("GEMINI_API_KEY", None)
                 try:
                     client = genai.Client(vertexai=True, location=region)
                     models = []
                     for m in client.models.list():
                         name = m.name.split("/")[-1]
                         if "gemini" in name:
                             models.append(name)
                     self._vertex_region_cache[region] = models
                     logger.info(f"Discovered {len(models)} Gemini models in Vertex AI region {region}.")
                     return models
                 finally:
                     if _temp_api_key is not None:
                         os.environ["GEMINI_API_KEY"] = _temp_api_key
        except Exception as e:
            logger.warning(f"Failed to list Vertex models in region {region}: {e}")
            self._vertex_region_cache[region] = []
            return []

    def _call_llm(self, prompt: str) -> str:
        """
        Mockable wrapper for LLM calls.
        Supports Google Generative AI (Gemini) and OpenAI.
        Falls back to Mock Data if calls fail.
        """
        # Ensure custom CA bundle is visible to httpx-based SDKs
        configure_ssl_env()

        # Define Mock Data inner function for reuse
        def get_mock_data():
            logger.warning("[!] Using MOCK DATA for demonstration (API keys missing or validation failed).")
            return """
            {
                "name": "Jane Doe",
                "title": "Senior Engineer",
                "contact_info": "City, Country | +1 555 0101 | jane@example.com\\ngithub.com/janedoe",
                "executive_summary": "A senior engineer with experience in distributed systems.",
                "competencies": [
                    ["Category A:", "Skill 1, Skill 2."],
                    ["Category B:", "Skill 3, Skill 4."]
                ],
                "experience": [
                    {
                        "company": "COMPANY A",
                        "location": "City, Country",
                        "dates": "Jan 2020 – Present",
                        "title": "Senior Engineer",
                        "summary_italic": "Led key initiatives.",
                        "bullets": [
                            ["Project A:", "Delivered X."],
                            ["Project B:", "Optimized Y."]
                        ]
                    }
                ],
                "projects": [
                    ["Project X:", "Description of project X."],
                    ["Project Y:", "Description of project Y."]
                ],
                "education": ["BS in Computer Science, University Name"],
                "certifications": "Certification A | Certification B"
            }
            """

        def should_fallback_to_mock() -> bool:
            return self.provider == "auto" or not self.api_key

        if not self.api_key and not self._has_adc() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            return get_mock_data()

        _call_start = time.time()
        _prompt_len = len(prompt)
        logger.info(f"_call_llm: provider={self.provider}, model={self.model or 'auto-select'}, prompt_chars={_prompt_len}")
        logger.debug(f"_call_llm: prompt preview: {prompt[:200]}...")
        
        try:
            # 0. Github & Anthropic (Placeholders for future implementation)
            if self.provider == "github":
                # TODO: Implement GitHub Models API
                raise NotImplementedError("GitHub provider is not yet implemented.")
            if self.provider == "anthropic":
                # TODO: Implement Anthropic API
                raise NotImplementedError("Anthropic provider is not yet implemented.")

            last_exception = None
                
            # 1. Vertex AI (Priority if provider is 'auto' or 'vertex')
            if self.provider in ["auto", "vertex"] and (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or self._has_adc()):
                try:
                    import warnings
                    from google import genai
                    import httpx
                    from cv_maker.ssl_helpers import get_ca_bundle
                    
                    # Create a custom httpx client to enforce the CA bundle (same as gemini provider)
                    ca_bundle = get_ca_bundle()
                    
                    # CV Maker sends very large prompts (Master CV + JD). Increase timeout.
                    timeout_sec = 120.0  # 2 minutes
                    verify_val = ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True
                    
                    _hclient = httpx.Client(timeout=httpx.Timeout(timeout_sec), verify=verify_val)
                    http_options = {'httpx_client': _hclient}

                    # If user pinned a model, use it directly; otherwise iterate priority list
                    vertex_models = [self.model] if self.model else [
                        "gemini-2.5-pro-preview",
                        "gemini-2.5-pro",
                        "gemini-2.5-flash",
                        "gemini-2.0-flash",
                        "gemini-2.5-flash-lite"
                    ]
                    
                    PRIORITY_REGIONS = [
                        "australia-southeast1",
                        "asia-southeast1",
                        "us-central1"
                    ]
                    
                    for model_name in vertex_models:
                        for region in PRIORITY_REGIONS:
                            # 1. Check if model exists in this region dynamically
                            available_models = self._get_vertex_models_for_region(region)
                            if model_name not in available_models:
                                logger.debug(f"Vertex model {model_name} not available in {region}. Skipping.")
                                continue
                                
                            try:
                                logger.info(f"Attempting Vertex AI model: {model_name} in {region}")
                                
                                with warnings.catch_warnings():
                                     warnings.filterwarnings("ignore", category=UserWarning, module="google.genai")
                                     # Do not pass api_key when vertexai=True, otherwise it overrides ADC.
                                     # Also hide the env var so google.genai doesn't automatically load it.
                                     _temp_api_key = os.environ.pop("GEMINI_API_KEY", None)
                                     try:
                                         client = genai.Client(vertexai=True, location=region, http_options=http_options)
                                     finally:
                                         if _temp_api_key is not None:
                                             os.environ["GEMINI_API_KEY"] = _temp_api_key
                                
                                def _gen_vertex(m, p, c=client):
                                    with warnings.catch_warnings():
                                        warnings.filterwarnings("ignore", category=UserWarning, module="google.genai")
                                        response = c.models.generate_content_stream(model=m, contents=p)
                                        return "".join([chunk.text for chunk in response if chunk.text])
                                
                                return self._attempt_with_retry(_gen_vertex, model_name, prompt)
                            except Exception as e:
                                last_exception = e
                                logger.warning(f"Vertex AI failed for {model_name} in {region}: {e}")
                                continue
                            
                    if last_exception:
                        if self.provider == "vertex":
                            raise last_exception
                        else:
                            logger.warning(f"Vertex AI models failed: {last_exception}. Falling back to next provider...")
                except ImportError:
                    logger.warning("google-genai not installed. Skipping Vertex ai.")
                    if self.provider == "vertex":
                        raise
                except Exception as e:
                    logger.warning(f"Vertex AI failed: {e}. Falling back...")
                    if self.provider == "vertex":
                        raise

            # 2. MiniMax (Anthropic-compatible by default for Token Plan; OpenAI-compatible optional)
            _minimax_key = os.environ.get("MINIMAX_API_KEY") or (
                self.api_key if self.provider == "minimax" else None
            )
            if self.provider in ["auto", "minimax"] and _minimax_key:
                base_url = os.environ.get("MINIMAX_BASE_URL", MINIMAX_ANTHROPIC_BASE_URL).rstrip("/")
                api_format = os.environ.get("MINIMAX_API_FORMAT", "").strip().lower()
                if not api_format:
                    api_format = "anthropic" if "/anthropic" in base_url else "openai"
                minimax_models = [self.model] if self.model else [
                    MINIMAX_DEFAULT_MODEL,
                    "MiniMax-M2.7-highspeed",
                    "MiniMax-M2.5",
                    "MiniMax-M2.1",
                ]

                if api_format == "anthropic":
                    import requests
                    from cv_maker.ssl_helpers import get_ca_bundle

                    ca_bundle = get_ca_bundle()
                    verify_val = ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True
                    endpoint = self._minimax_anthropic_messages_url(base_url)
                    max_tokens = int(os.environ.get("MINIMAX_MAX_TOKENS", "32768"))

                    for model_name in minimax_models:
                        try:
                            logger.info(f"Attempting MiniMax Anthropic model: {model_name}")

                            def _gen_minimax_anthropic(m, p):
                                _t0 = time.time()
                                response = requests.post(
                                    endpoint,
                                    headers={
                                        "X-Api-Key": _minimax_key,
                                        "Content-Type": "application/json",
                                        "anthropic-version": "2023-06-01",
                                    },
                                    json={
                                        "model": m,
                                        "max_tokens": max_tokens,
                                        "system": (
                                            "You are a precise structured-output engine. "
                                            "No deep analysis is needed. Do not use tools. "
                                            "Return the requested final answer directly. "
                                            "For JSON tasks, return valid JSON only with no markdown or explanation."
                                        ),
                                        "messages": [{"role": "user", "content": p}],
                                    },
                                    timeout=240,
                                    verify=verify_val,
                                )
                                response.raise_for_status()
                                data = response.json()
                                result = self._extract_anthropic_text(data)
                                if not result.strip():
                                    raise ValueError(
                                        "MiniMax returned no text content "
                                        f"(stop_reason={data.get('stop_reason')}, "
                                        f"content_blocks={self._anthropic_content_block_types(data)}, "
                                        f"usage={data.get('usage')}). "
                                        "This usually means the model exhausted MINIMAX_MAX_TOKENS in thinking "
                                        "before writing the final answer. Increase MINIMAX_MAX_TOKENS or use a shorter prompt."
                                    )
                                _elapsed = time.time() - _t0
                                _usage = data.get("usage") if isinstance(data, dict) else None
                                logger.info(f"MiniMax Anthropic response: model={m}, elapsed={_elapsed:.1f}s, response_chars={len(result)}")
                                if _usage:
                                    logger.info(f"MiniMax tokens: usage={_usage}")
                                return result

                            result = self._attempt_with_retry(_gen_minimax_anthropic, model_name, prompt)
                            logger.info(f"_call_llm completed: total_elapsed={time.time() - _call_start:.1f}s")
                            return result
                        except Exception as e:
                            last_exception = e
                            continue
                elif api_format == "openai":
                    import openai
                    import httpx
                    from cv_maker.ssl_helpers import get_ca_bundle

                    ca_bundle = get_ca_bundle()
                    http_client = httpx.Client(
                        timeout=httpx.Timeout(120.0),
                        verify=ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True,
                    )
                    client = openai.OpenAI(api_key=_minimax_key, base_url=base_url, http_client=http_client)

                    for model_name in minimax_models:
                        try:
                            logger.info(f"Attempting MiniMax OpenAI-compatible model: {model_name}")

                            def _gen_minimax_openai(m, p):
                                _t0 = time.time()
                                response = client.chat.completions.create(
                                    model=m,
                                    messages=[{"role": "user", "content": p}],
                                    temperature=0.7,
                                )
                                result = response.choices[0].message.content
                                _elapsed = time.time() - _t0
                                _usage = getattr(response, 'usage', None)
                                logger.info(f"MiniMax OpenAI-compatible response: model={m}, elapsed={_elapsed:.1f}s, response_chars={len(result)}")
                                if _usage:
                                    logger.info(f"MiniMax tokens: prompt={_usage.prompt_tokens}, completion={_usage.completion_tokens}, total={_usage.total_tokens}")
                                return result

                            result = self._attempt_with_retry(_gen_minimax_openai, model_name, prompt)
                            logger.info(f"_call_llm completed: total_elapsed={time.time() - _call_start:.1f}s")
                            return result
                        except Exception as e:
                            last_exception = e
                            continue
                else:
                    raise ValueError("MINIMAX_API_FORMAT must be either 'anthropic' or 'openai'.")

                if last_exception:
                    if self.provider == "minimax":
                        raise last_exception
                    else:
                        logger.warning(f"MiniMax failed: {last_exception}. Falling back...")

            # 3. OpenAI
            _openai_key = os.environ.get("OPENAI_API_KEY") or (
                self.api_key if self.api_key and self.api_key.startswith("sk-") else None
            )
            if self.provider in ["auto", "openai"] and _openai_key:
                import openai
                import httpx
                from cv_maker.ssl_helpers import get_ca_bundle
                
                # Configure httpx client for OpenAI with CA bundle
                ca_bundle = get_ca_bundle()
                http_client = httpx.Client(verify=ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True)
                
                client = openai.OpenAI(api_key=_openai_key, http_client=http_client)

                # If user pinned a model, use it directly; otherwise iterate priority list
                openai_models = [self.model] if self.model else [
                    'gpt-5.4-mini', 'gpt-5.4', 'gpt-5.4-nano',
                    'gpt-5-mini', 'gpt-5-nano', 'gpt-5',
                    'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano',
                    'o4-mini', 'gpt-4o', 'gpt-4o-mini',
                ]
                
                for model_name in openai_models:
                    try:
                        logger.info(f"Attempting OpenAI model: {model_name}")
                        def _gen_openai(m, p):
                            _t0 = time.time()
                            response = client.chat.completions.create(
                                model=m,
                                messages=[{"role": "user", "content": p}],
                                temperature=0.7
                            )
                            result = response.choices[0].message.content
                            _elapsed = time.time() - _t0
                            _usage = getattr(response, 'usage', None)
                            logger.info(f"OpenAI response: model={m}, elapsed={_elapsed:.1f}s, response_chars={len(result)}")
                            if _usage:
                                logger.info(f"OpenAI tokens: prompt={_usage.prompt_tokens}, completion={_usage.completion_tokens}, total={_usage.total_tokens}")
                            return result
                        result = self._attempt_with_retry(_gen_openai, model_name, prompt)
                        logger.info(f"_call_llm completed: total_elapsed={time.time() - _call_start:.1f}s")
                        return result
                    except Exception as e:
                        last_exception = e
                        continue
                        
                if last_exception:
                    if self.provider == "openai":
                        raise last_exception
                    else:
                        logger.warning(f"OpenAI failed: {last_exception}. Falling back...")

            # 4. Google GenAI (New SDK)
            if self.provider in ["auto", "gemini"] and self.api_key:
                from google import genai
                import httpx
                from cv_maker.ssl_helpers import get_ca_bundle
                
                # Create a custom httpx client to enforce the CA bundle
                ca_bundle = get_ca_bundle()
                
                # CV Maker sends very large prompts (Master CV + JD). Increase timeout.
                timeout_sec = 120.0  # 2 minutes
                verify_val = ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True
                
                _hclient = httpx.Client(timeout=httpx.Timeout(timeout_sec), verify=verify_val)
                http_options = {'httpx_client': _hclient}
                    
                client = genai.Client(api_key=self.api_key, http_options=http_options)

                # If user pinned a model, use it directly; otherwise iterate priority list
                gemini_models = [self.model] if self.model else [
                    'gemini-2.5-pro-preview',
                    'gemini-2.5-pro',
                    'gemini-2.5-flash',
                    'gemini-2.0-flash',
                    'gemini-2.5-flash-lite'
                ]
                
                # 1. Try our preferred priority models first
                for model_name in gemini_models:
                    try:
                        logger.info(f"Attempting GenAI priority model: {model_name}")
                        def _gen_genai(m, p):
                            _t0 = time.time()
                            response = client.models.generate_content_stream(
                                model=m,
                                contents=p
                            )
                            result = "".join([chunk.text for chunk in response if chunk.text])
                            logger.info(f"GenAI response: model={m}, elapsed={time.time() - _t0:.1f}s, response_chars={len(result)}")
                            return result
                        result = self._attempt_with_retry(_gen_genai, model_name, prompt)
                        logger.info(f"_call_llm completed: total_elapsed={time.time() - _call_start:.1f}s")
                        return result
                    except Exception as e:
                        last_exception = e
                        continue
                
                # Skip cache/discovery fallbacks when user pinned a model
                if not self.model:
                    # 2. Try Cached Models as fallback
                    cached_models = self._load_cache()
                    if cached_models:
                        logger.info(f"Loaded {len(cached_models)} models from cache.")
                        for model_name in cached_models:
                            if model_name in gemini_models:
                                continue # Already tried
                            try:
                                logger.info(f"Attempting cached model: {model_name}")
                                def _gen_cached(m, p):
                                    response = client.models.generate_content_stream(
                                        model=m,
                                        contents=p
                                    )
                                    return "".join([chunk.text for chunk in response if chunk.text])
                                return self._attempt_with_retry(_gen_cached, model_name, prompt)
                            except Exception as e:
                                logger.warning(f"Cached model {model_name} failed: {e}")
                    
                    # 3. If Cache failed/empty, try Auto-Discovery
                    logger.info("Cache failed or empty. Attempting auto-discovery...")
                    try:
                         discovered = self.discover_models(client)
                         
                         # Save discovered to cache immediately so next run is fast
                         if discovered:
                             self._save_cache(discovered)
                             
                             # Only call discovered models IF the cache was empty to begin with 
                             # (Meaning we had to discover them). We don't want to call models that 
                             # are NOT in the cache (which is what the original logic did by accident).
                             if not cached_models:
                                 for model_name in discovered:
                                     if model_name in gemini_models:
                                         continue
                                     try:
                                         logger.info(f"Attempting discovered model: {model_name}")
                                         def _gen_disc(m, p):
                                             response = client.models.generate_content_stream(
                                                 model=m,
                                                 contents=p
                                             )
                                             return "".join([chunk.text for chunk in response if chunk.text])
                                         return self._attempt_with_retry(_gen_disc, model_name, prompt)
                                     except Exception as e:
                                         # Keep trying others
                                         logger.warning(f"Model {model_name} failed: {e}")
                    except Exception as e:
                        logger.warning(f"Auto-discovery failed: {e}")

            if last_exception:
                raise last_exception
                
            # If no provider responded and auto fell through
            raise ValueError(f"No configured LLM provider was able to generate content. Provider mode: {self.provider}")

        except ImportError as e:
            logger.error(f"Missing dependency for specific provider: {e}")
            if should_fallback_to_mock():
                return get_mock_data()
            raise
        except Exception as e:
            logger.error(f"LLM call failed after {time.time() - _call_start:.1f}s: {e}")
            if should_fallback_to_mock():
                return get_mock_data()
            raise

    def discover_models(self, client=None) -> List[str]:
        """
        Dynamically finds available models for the active provider.
        Supports Gemini (google-genai SDK), OpenAI, and MiniMax.
        """
        # --- OpenAI discovery ---
        if self.provider == "openai":
            return self._discover_openai_models()

        # --- MiniMax discovery ---
        if self.provider == "minimax":
            return self._discover_minimax_models()

        # --- Gemini / Vertex discovery ---
        if not client:
             if self.provider == "vertex": 
                 return None # Not implemented for vertex dynamic yet
             try:
                 from google import genai
                 if not self.api_key: return None
                 client = genai.Client(api_key=self.api_key)
             except:
                 return None

        try:
            # Correct method for new SDK is often client.models.list()
            pager = client.models.list() 
            
            candidates = []
            for model in pager:
                methods = getattr(model, 'supported_actions', [])
                if not methods:
                     methods = getattr(model, 'supported_generation_methods', []) # Fallback check 
                
                # Include all Gemini models that support generateContent
                if methods and any("generatecontent" == m.lower() for m in methods):
                     name = model.name.split("/")[-1] 
                     if "gemini" in name.lower():
                         candidates.append(name)
            
            return candidates

        except Exception as e:
            logger.warning(f"Failed to list models: {e}")
            return []

    def _discover_openai_models(self) -> List[str]:
        """Lists available OpenAI models via the OpenAI API."""
        try:
            import openai
            import httpx
            from cv_maker.ssl_helpers import get_ca_bundle

            api_key = os.environ.get("OPENAI_API_KEY") or self.api_key
            if not api_key:
                logger.warning("No OpenAI API key found for model discovery.")
                return []

            ca_bundle = get_ca_bundle()
            http_client = httpx.Client(
                verify=ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True
            )
            client = openai.OpenAI(api_key=api_key, http_client=http_client)

            models = client.models.list()
            # Exclude non-chat models (embeddings, audio, image, moderation,
            # realtime, transcription, TTS, codex, search, computer-use, etc.)
            _EXCLUDE = (
                "text-embedding", "tts-", "dall-e", "whisper", "davinci",
                "babbage", "curie", "ada", "moderation", "embedding",
                "gpt-image", "chatgpt-image", "gpt-audio", "gpt-realtime",
                "gpt-4o-audio", "gpt-4o-realtime", "gpt-4o-transcribe",
                "gpt-4o-mini-audio", "gpt-4o-mini-realtime",
                "gpt-4o-mini-transcribe", "gpt-4o-mini-tts",
                "gpt-4o-search", "gpt-4o-mini-search",
                "computer-use", "omni-moderation", "text-moderation",
                "sora", "codex-mini", "gpt-oss",
                "o3-deep-research", "o4-mini-deep-research",
            )
            candidates = sorted(
                [m.id for m in models.data if not m.id.startswith(_EXCLUDE)]
            )
            return candidates

        except ImportError:
            logger.warning("openai package not installed. Cannot discover OpenAI models.")
            return []
        except Exception as e:
            logger.warning(f"Failed to list OpenAI models: {e}")
            return []

    @staticmethod
    def _minimax_anthropic_messages_url(base_url: str) -> str:
        base = str(base_url or MINIMAX_ANTHROPIC_BASE_URL).rstrip("/")
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    @staticmethod
    def _minimax_anthropic_models_url(base_url: str) -> str:
        base = str(base_url or MINIMAX_ANTHROPIC_BASE_URL).rstrip("/")
        if base.endswith("/models"):
            return base
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"

    @staticmethod
    def _extract_anthropic_text(data: object) -> str:
        if not isinstance(data, dict):
            return str(data or "")

        content = data.get("content", "")
        if isinstance(content, str):
            return content

        parts = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif isinstance(item, dict) and "text" in item:
                    parts.append(str(item.get("text", "")))
        return "".join(parts).strip()

    @staticmethod
    def _anthropic_content_block_types(data: object) -> list[str]:
        if not isinstance(data, dict):
            return []
        content = data.get("content", [])
        if not isinstance(content, list):
            return []
        return [
            str(item.get("type", "unknown"))
            for item in content
            if isinstance(item, dict)
        ]

    def _discover_minimax_models(self) -> List[str]:
        """Lists available MiniMax models."""
        try:
            from cv_maker.ssl_helpers import get_ca_bundle

            api_key = os.environ.get("MINIMAX_API_KEY") or self.api_key
            if not api_key:
                logger.warning("No MiniMax API key found for model discovery.")
                return []

            base_url = os.environ.get("MINIMAX_BASE_URL", MINIMAX_ANTHROPIC_BASE_URL).rstrip("/")
            api_format = os.environ.get("MINIMAX_API_FORMAT", "").strip().lower()
            if not api_format:
                api_format = "anthropic" if "/anthropic" in base_url else "openai"

            ca_bundle = get_ca_bundle()
            verify_val = ca_bundle if isinstance(ca_bundle, str) and os.path.exists(ca_bundle) else True

            if api_format == "anthropic":
                import requests

                response = requests.get(
                    self._minimax_anthropic_models_url(base_url),
                    headers={
                        "X-Api-Key": api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    timeout=60,
                    verify=verify_val,
                )
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                return sorted([row.get("id") for row in rows if isinstance(row, dict) and row.get("id")])

            if api_format == "openai":
                import openai
                import httpx

                http_client = httpx.Client(timeout=httpx.Timeout(60.0), verify=verify_val)
                client = openai.OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

                models = client.models.list()
                candidates = sorted([m.id for m in models.data if "minimax" in m.id.lower()])
                return candidates

            logger.warning("MINIMAX_API_FORMAT must be either 'anthropic' or 'openai'.")
            return []

        except ImportError:
            logger.warning("Required package not installed. Cannot discover MiniMax models.")
            return []
        except Exception as e:
            logger.warning(f"Failed to list MiniMax models: {e}")
            return []

    def analyze_job_description(self, text: str) -> JobDescription:
        """
        Extracts key skills and summary from raw JD text.
        """
        logger.info(f"analyze_job_description: input_chars={len(text)}")
        _start = time.time()
        prompt = f"""
        You are an expert technical recruiter. Analyze the following Job Description.
        Extract a specific 'role_title' (e.g. 'Senior Python Engineer').
        Extract the 'company_name' (e.g. 'Google', 'Acme Corp') if mentioned, otherwise use an empty string.
        Extract a list of 5-10 'key_skills' (technologies, methodologies) required.
        Provide a 1-sentence 'summary' of the role.
        
        Return ONLY valid JSON in this format:
        {{
            "role_title": "Title",
            "company_name": "Company",
            "key_skills": ["Skill 1", "Skill 2"],
            "summary": "This role involves..."
        }}

        JOB DESCRIPTION:
        {text[:4000]}  # Truncate to avoid context limits
        """
        json_str = self._clean_json(self._call_llm(prompt))
        try:
            data = json.loads(json_str)
            jd = JobDescription(
                raw_text=text,
                role_title=data.get("role_title", "Top Candidate"),
                company_name=data.get("company_name", ""),
                key_skills=data.get("key_skills", []),
                summary=data.get("summary", "")
            )
            logger.info(f"analyze_job_description completed: elapsed={time.time() - _start:.1f}s, role='{jd.role_title}', company='{jd.company_name}', skills={len(jd.key_skills)}")
            return jd
        except json.JSONDecodeError:
            logger.error(f"Failed to decode LLM response for JD analysis (elapsed={time.time() - _start:.1f}s)")
            logger.debug(f"Raw JD analysis response: {json_str[:500]}")
            if self.provider != "auto":
                raise ValueError("LLM returned invalid JSON for JD analysis; refusing to continue with empty JD data.")
            return JobDescription(raw_text=text)

    def tailor_cv(self, master_cv_text: str, jd: JobDescription, github_context: str = "", summarize_years: int = 10) -> CVData:
        """
        Selects relevant experience from the master CV to match the JD.
        """
        logger.info(f"tailor_cv: master_cv_chars={len(master_cv_text)}, target_role='{jd.role_title}', summarize_years={summarize_years}")
        _start = time.time()
        github_section = ""
        if github_context:
            github_section = f"\nTECHNICAL PORTFOLIO (GITHUB):\n{github_context}\n"

        # Calculate cutoff year
        import datetime
        current_year = datetime.datetime.now().year
        
        if summarize_years > 0:
            cutoff_year = current_year - summarize_years
            
            # Rule 1: Strict inclusion of recent roles
            rule_1 = f"1. Identify ALL roles ending in {cutoff_year} or later (including 'Present'). You MUST include these in the 'experience' array in FULL DETAIL, listed in strict reverse-chronological order (most recent first)."
            
            # Rule 6: Strict summarization of older roles
            rule_6 = f"""
            6. CRITICAL: Any role that ended BEFORE {cutoff_year} MUST be placed in the separate 'earlier_experience' array.
               For these older roles: Provide Title, Company, and Dates. Provide a single detailed summary paragraph.
            """
        else:
            # Default/Disable mode: Focus on relevance
            rule_1 = "1. Select the top most relevant roles from the Master CV. Provide these in FULL DETAIL in the 'experience' array, listed in strict reverse-chronological order (most recent first)."
            rule_6 = "6. Do NOT use the 'earlier_experience' array. Include all relevant roles in the main 'experience' section."

        prompt = f"""
        You are an expert CV writer. I will provide a MASTER CV text and a target JOB DESCRIPTION.
        Your goal is to tailor the CV content to perfectly match the job.
        
        RULES:
        {rule_1}
        2. JOB TITLES: If a role in the Master CV has multiple titles separated by slashes (e.g. "Senior Dev / Lead Architect"), you MUST select ONLY the one title that is most relevant to the Target Role and use it. Do not include the slashes or alternative titles.
           For Inspected Pty Ltd, choose the role title dynamically from ONLY these two options based on the Target Role and Target Skills: "Full Stack Developer" for web/full-stack/software roles, or "Principal AI Engineer" for AI/ML/LLM/agent roles. Do not copy a fixed template title for this company.
        3. For each of these detailed roles, include 5-7 bullet points. Prioritize technical depth, specific metrics, and leadership achievements.
        4. Rewrite the Executive Summary to be targeted, substantial, and authoritative (keep it 4-6 sentences).
        5. Reorder/Select 'Core Competencies' to match the JD, preserving technical specificity.
        6. TONE: Expert, Senior Executive, Technical Leader. Avoid generic fluff. Focus on "what" and "how".
        {rule_6}
        8. Use the TECHNICAL PORTFOLIO to substantiate skills in the 'Projects' or 'Competencies' sections, citing specific repositories where relevant.
        9. ORDERING: Within the 'experience' array, roles MUST be ordered reverse-chronologically by end date ('Present' counts as the most recent). The 'earlier_experience' array MUST also be ordered reverse-chronologically.

        Target Role: {jd.summary}
        Target Skills: {', '.join(jd.key_skills)}
        
        MASTER CV CONTENT:
        {master_cv_text[:100000]}
        
        {github_section}

        Return JSON matching this structure:
        {{
            "name": "Applicant Name",
            "title": "Target Title",
            "contact_info": "Phone | Email | Address | Website",
            "executive_summary": "Tailored summary...",
            "competencies": [["Category", "Skill string"], ...],
            "experience": [
                {{
                    "title": "Role Title",
                    "company": "Company",
                    "location": "Loc",
                    "dates": "Date range",
                    "summary_italic": "Brief role context",
                    "bullets": [["Skill/Outcome", "Description"], ...]
                }}
            ],
            "earlier_experience": [
                {{
                    "title": "Role Title",
                    "company": "Company",
                    "dates": "Date range",
                    "summary": "Detailed summary paragraph..."
                }}
            ],
            "projects": [["Title", "Desc"], ...],
            "education": ["Degree 1"],
            "certifications": "Cert string"
        }}
        
        Return ONLY valid JSON. Do not include markdown, commentary, XML, or explanation.
        """
        json_str = self._clean_json(self._call_llm(prompt))
        
        # Default empty data
        default_data = CVData(name="Candidate", title="N/A", contact_info="", executive_summary="", competencies=[], experience=[], earlier_experience=[], projects=[], education=[], certifications="")

        try:
            raw = json.loads(json_str)
            if not isinstance(raw, dict) or not raw:
                raise ValueError("LLM returned an empty or non-object JSON response.")
            
            # Helper to ensure 2-element tuple
            def to_tuple_2(item):
                if isinstance(item, list):
                    if len(item) >= 2: return (str(item[0]), str(item[1]))
                    elif len(item) == 1: return (str(item[0]), "")
                    else: return ("", "")
                return (str(item), "")

            # Map raw JSON to dataclasses
            exp_list = []
            for job in raw.get("experience", []):
                # Ensure bullets are list of tuples
                clean_bullets = [to_tuple_2(b) for b in job.get("bullets", [])]
                
                exp_list.append(Experience(
                    title=self._select_role_title_for_company(job.get("title", ""), job.get("company", ""), jd),
                    company=job.get("company", ""),
                    location=job.get("location", ""),
                    dates=job.get("dates", ""),
                    summary_italic=job.get("summary_italic"),
                    bullets=clean_bullets
                ))
            
            # Map Earlier Experience
            earlier_list = []
            for job in raw.get("earlier_experience", []):
                earlier_list.append(EarlierExperience(
                    title=self._select_role_title_for_company(job.get("title", ""), job.get("company", ""), jd),
                    company=job.get("company", ""),
                    summary=job.get("summary", ""),
                    dates=job.get("dates", "")
                ))
            
            # Map Competencies to tuples
            comps = [to_tuple_2(c) for c in raw.get("competencies", [])]
            # Map Projects to tuples
            projs = [to_tuple_2(p) for p in raw.get("projects", [])]

            missing_dates = []
            for job in exp_list:
                if not str(job.dates or "").strip():
                    missing_dates.append(f"{job.title or 'Untitled role'} at {job.company or 'Unknown company'}")
            for job in earlier_list:
                if not str(job.dates or "").strip():
                    missing_dates.append(f"{job.title or 'Untitled earlier role'} at {job.company or 'Unknown company'}")
            if missing_dates:
                missing_dates_message = "Missing dates for experience entries: " + "; ".join(missing_dates)
                if self.provider != "auto":
                    raise ValueError(missing_dates_message)
                logger.warning(missing_dates_message)

            logger.info(f"tailor_cv completed: elapsed={time.time() - _start:.1f}s, experience_entries={len(exp_list)}, earlier_entries={len(earlier_list)}")

            return CVData(
                name=raw.get("name", ""),
                title=self._select_relevant_title(raw.get("title", ""), jd),
                contact_info=raw.get("contact_info", ""),
                executive_summary=raw.get("executive_summary", ""),
                competencies=comps,
                earlier_experience=earlier_list,
                experience=exp_list, # Fixed order matching dataclass? No, keyword args are safe.
                projects=projs,
                education=raw.get("education", []),
                certifications=raw.get("certifications", "")
            )

        except Exception as e:
            logger.error(f"Failed to map LLM response to CVData (elapsed={time.time() - _start:.1f}s): {e}")
            logger.debug(f"Raw tailor_cv response: {json_str[:500]}")
            if self.provider != "auto":
                raise ValueError(f"LLM returned invalid CV JSON; refusing to generate an empty CV. Details: {e}") from e
            return default_data

    def generate_cover_letter(self, master_cv_text: str, jd: JobDescription) -> str:
        """
        Generates a tailored cover letter based on the JD and Master CV.
        """
        logger.info(f"generate_cover_letter: target_role='{jd.role_title}', master_cv_chars={len(master_cv_text)}")
        _start = time.time()
        prompt = f"""
        You are an expert executive CV writer. Write a high-impact, professional cover letter for the following role.
        
        TARGET ROLE SUMMARY: {jd.summary}
        KEY SKILLS REQUIRED: {', '.join(jd.key_skills)}
        
        MY BACKGROUND (MASTER CV):
        {master_cv_text[:50000]}
        
        GUIDELINES:
        1. Salutation: "Dear Hiring Manager," (unless a specific name is clear in the JD description).
        2. Hook: Strong opening statement explaining why I am the perfect strategic fit for *this specific* role.
        3. Body: Connect 2-3 specific achievements from my Master CV directly to the Key Skills required.
        4. Tone: Confident, Senior Executive, Concise.
        5. Length: 300-400 words maximum.
        6. Format: Return ONLY the body of the letter. Do not include address blocks, closing, signature, or my name at the end (the system handles those). Start with the Salutation.
        """
        result = self._call_llm(prompt)
        logger.info(f"generate_cover_letter completed: elapsed={time.time() - _start:.1f}s, output_chars={len(result)}")
        return result

    def _clean_json(self, text: str) -> str:
        """Helper to strip reasoning tags/code fences and extract JSON."""
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        text = text.strip()

        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]

        return text.strip()
