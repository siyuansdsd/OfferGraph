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
import sys

# Pre-mock modules to avoid ImportErrors if not installed
sys.modules['google'] = MagicMock()
sys.modules['google.genai'] = MagicMock()
sys.modules['google'].genai = sys.modules['google.genai']
sys.modules['openai'] = MagicMock()
sys.modules['vertexai'] = MagicMock()

from cv_maker import llm_client
from cv_maker.models import JobDescription

class TestLLMClient(unittest.TestCase):
    def setUp(self):
        sys.modules['openai'].OpenAI.reset_mock()
        sys.modules['openai'].OpenAI.side_effect = None
        # Mock cache file to avoid FS errors
        with patch.object(llm_client.LLMClient, '_load_cache', return_value=[]):
             self.client = llm_client.LLMClient(provider="gemini")
        # We need to ensure cache is mocked during tests too if called
        self.mock_cache_patch = patch.object(llm_client.LLMClient, '_load_cache', return_value=[])
        self.mock_cache = self.mock_cache_patch.start()

    def tearDown(self):
        self.mock_cache_patch.stop()

    def test_call_llm_gemini(self):
        # Setup mocks
        mock_genai = sys.modules['google.genai']
        
        # Create explicit chain
        mock_client = MagicMock()
        mock_models = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.text = "Gemini Response"
        
        # Link them — code calls generate_content_stream which returns an iterable of chunks
        mock_genai.Client.return_value = mock_client
        mock_client.models = mock_models
        mock_models.generate_content_stream = MagicMock(return_value=[mock_chunk])

        # Use patch.dict for env vars
        with patch.dict(os.environ, {"GEMINI_API_KEY": "mock_key"}, clear=True):
            # Need to also patch discover_models since it's called
            with patch.object(llm_client.LLMClient, 'discover_models', return_value=['gemini-discovery']):
                client = llm_client.LLMClient(provider="gemini")
                result = client._call_llm("Test Prompt")
                
                self.assertEqual(result, "Gemini Response")

    def test_call_llm_openai(self):
        mock_openai = sys.modules['openai']
        
        # Explicit chain
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = MagicMock()
        mock_create = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        
        mock_message.content = "OpenAI Response"
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        
        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat = mock_chat
        mock_chat.completions = mock_completions
        mock_completions.create = mock_create
        mock_create.return_value = mock_response

        # Use patch.dict to set OPENAI 
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock-openai-key"}, clear=True):
            client = llm_client.LLMClient(provider="openai")
            result = client._call_llm("Test Prompt")

            self.assertEqual(result, "OpenAI Response")

    def test_call_llm_minimax(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "MiniMax Anthropic Response"}],
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            with patch.dict(
                os.environ,
                {
                    "MINIMAX_API_KEY": "minimax-mock-key",
                    "MINIMAX_API_FORMAT": "anthropic",
                    "MINIMAX_BASE_URL": "https://api.minimax.io/anthropic",
                },
                clear=True,
            ):
                client = llm_client.LLMClient(provider="minimax")
                result = client._call_llm("Test Prompt")

        self.assertEqual(result, "MiniMax Anthropic Response")
        request_kwargs = mock_post.call_args.kwargs
        self.assertEqual(request_kwargs["headers"]["X-Api-Key"], "minimax-mock-key")
        self.assertEqual(request_kwargs["json"]["model"], "MiniMax-M2.7")
        self.assertEqual(request_kwargs["json"]["max_tokens"], 32768)
        self.assertIn("valid JSON only", request_kwargs["json"]["system"])
        self.assertEqual(mock_post.call_args.args[0], "https://api.minimax.io/anthropic/v1/messages")

    def test_minimax_empty_text_response_raises(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "thinking", "thinking": "still thinking"}],
            "stop_reason": "max_tokens",
            "usage": {"input_tokens": 10, "output_tokens": 32768},
        }

        with patch("requests.post", return_value=mock_response):
            with patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-mock-key"}, clear=True):
                client = llm_client.LLMClient(provider="minimax")
                with patch.object(llm_client.LLMClient, "_attempt_with_retry", side_effect=lambda fn, m, p: fn(m, p)):
                    with self.assertRaises(ValueError) as ctx:
                        client._call_llm("Test Prompt")

        self.assertIn("returned no text content", str(ctx.exception))

    def test_call_llm_minimax_openai_format(self):
        mock_openai = sys.modules['openai']

        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = MagicMock()
        mock_create = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        mock_message.content = "MiniMax Response"
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]

        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat = mock_chat
        mock_chat.completions = mock_completions
        mock_completions.create = mock_create
        mock_create.return_value = mock_response

        with patch.dict(
            os.environ,
            {
                "MINIMAX_API_KEY": "minimax-mock-key",
                "MINIMAX_API_FORMAT": "openai",
                "MINIMAX_BASE_URL": "https://api.minimax.io/v1",
            },
            clear=True,
        ):
            client = llm_client.LLMClient(provider="minimax")
            result = client._call_llm("Test Prompt")

        self.assertEqual(result, "MiniMax Response")
        constructor_kwargs = mock_openai.OpenAI.call_args.kwargs
        self.assertEqual(constructor_kwargs["api_key"], "minimax-mock-key")
        self.assertEqual(str(constructor_kwargs["base_url"]).rstrip("/"), llm_client.MINIMAX_BASE_URL)
        call_kwargs = mock_completions.create.call_args
        self.assertEqual(call_kwargs.kwargs.get("model") or call_kwargs[1].get("model"), "MiniMax-M2.7")

    def test_explicit_minimax_failure_does_not_return_mock_data(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = RuntimeError("provider failed")

        with patch("requests.post", return_value=mock_response):
            with patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-mock-key"}, clear=True):
                client = llm_client.LLMClient(provider="minimax")

                with patch.object(llm_client.LLMClient, "_attempt_with_retry", side_effect=lambda fn, m, p: fn(m, p)):
                    with self.assertRaises(RuntimeError):
                        client._call_llm("Test Prompt")

    def test_explicit_provider_invalid_cv_json_raises(self):
        client = llm_client.LLMClient(provider="minimax")

        with patch.object(client, "_call_llm", return_value=""):
            with self.assertRaises(ValueError) as ctx:
                client.tailor_cv("Master CV", JobDescription(raw_text="JD", role_title="Role"))

        self.assertIn("refusing to generate an empty CV", str(ctx.exception))

    def test_explicit_provider_missing_experience_dates_raises(self):
        client = llm_client.LLMClient(provider="minimax")
        fake_json = """
        {
            "name": "Jane",
            "title": "Dev",
            "contact_info": "Contact",
            "executive_summary": "Sum",
            "competencies": [],
            "experience": [
                {
                    "title": "Developer",
                    "company": "Co",
                    "location": "Sydney",
                    "bullets": []
                }
            ],
            "earlier_experience": [],
            "projects": [],
            "education": [],
            "certifications": ""
        }
        """

        with patch.object(client, "_call_llm", return_value=fake_json):
            with self.assertRaises(ValueError) as ctx:
                client.tailor_cv("Master CV", JobDescription(raw_text="JD", role_title="Role"))

        self.assertIn("Missing dates for experience entries", str(ctx.exception))

    def test_tailor_cv(self):
        client = llm_client.LLMClient()
        fake_json = """
        {
            "name": "Jane",
            "title": "Dev",
            "contact_info": "Contact",
            "executive_summary": "Sum",
            "competencies": [["Cat", "Skill"]],
            "experience": [],
            "earlier_experience": [{"title": "Old Role", "company": "Old Corp", "summary": "Did stuff"}],
            "projects": [],
            "education": [],
            "certifications": ""
        }
        """
        with patch.object(client, '_call_llm', return_value=fake_json):
            jd = JobDescription(raw_text="JD", role_title="Dev", key_skills=["Python"], summary="Role")
            cv_data = client.tailor_cv("Master CV", jd)
            self.assertEqual(cv_data.name, "Jane")
            self.assertEqual(len(cv_data.earlier_experience), 1)
            self.assertEqual(cv_data.earlier_experience[0].company, "Old Corp")

    def test_tailor_cv_summary_prompt(self):
        client = llm_client.LLMClient()
        fake_json = '{}' # invalid json but we just want to check input prompt
        
        with patch.object(client, '_call_llm', return_value=fake_json):
            jd = JobDescription(raw_text="JD", role_title="Dev", key_skills=["Python"], summary="Role")
            
            # Case 1: summarize_years=10 (Default)
            client.tailor_cv("CV", jd, summarize_years=10)
            call_args = client._call_llm.call_args[0][0]
            self.assertIn("Identify ALL roles ending in", call_args)
            self.assertIn("CRITICAL: Any role that ended BEFORE", call_args)
            
            # Case 2: summarize_years=0 (Disabled)
            client.tailor_cv("CV", jd, summarize_years=0)
            call_args = client._call_llm.call_args[0][0]
            self.assertIn("Select the top most relevant roles", call_args)
            self.assertIn("Do NOT use the 'earlier_experience' array", call_args)

    def test_tailor_cv_robust_unpacking(self):
        """Test that single-element lists in JSON don't crash the unpacked tuples."""
        client = llm_client.LLMClient()
        fake_json = """
        {
            "name": "Test",
            "experience": [
                {
                    "title": "Role",
                    "company": "Co",
                    "bullets": [["Bullet 1"], ["Bullet 2", "Desc 2"], "StringBullet"]
                }
            ],
            "competencies": [["Comp 1"]],
            "projects": [["Proj 1"]]
        }
        """
        with patch.object(client, '_call_llm', return_value=fake_json):
            cv = client.tailor_cv("Master", JobDescription("JD"))
            
            # Bullets
            bullets = cv.experience[0].bullets
            self.assertEqual(len(bullets), 3)
            self.assertEqual(bullets[0], ("Bullet 1", "")) # Padded
            self.assertEqual(bullets[1], ("Bullet 2", "Desc 2")) # Normal
            self.assertEqual(bullets[2], ("StringBullet", "")) # String case
            
            # Competencies
            self.assertEqual(cv.competencies[0], ("Comp 1", ""))
            
            # Projects
            self.assertEqual(cv.projects[0], ("Proj 1", ""))

    def test_tailor_cv_selects_closest_slash_title(self):
        client = llm_client.LLMClient()
        fake_json = """
        {
            "name": "Test",
            "title": "AI Engineer / Software Engineer",
            "experience": [
                {
                    "title": "Principal AI Engineer / Software Engineer",
                    "company": "Co",
                    "location": "Sydney",
                    "dates": "2026 - Present",
                    "bullets": []
                }
            ],
            "earlier_experience": [
                {
                    "title": "AI Engineer / Full Stack Developer",
                    "company": "Old Co",
                    "summary": "Built web applications."
                }
            ],
            "competencies": [],
            "projects": [],
            "education": [],
            "certifications": ""
        }
        """
        jd = JobDescription(
            raw_text="We need a Web Developer to build React, HTML, CSS, and JavaScript applications.",
            role_title="Web Developer",
            key_skills=["React", "HTML", "CSS", "JavaScript"],
            summary="Build and maintain web applications."
        )

        with patch.object(client, '_call_llm', return_value=fake_json):
            cv = client.tailor_cv("Master", jd)

        self.assertEqual(cv.title, "Software Engineer")
        self.assertEqual(cv.experience[0].title, "Software Engineer")
        self.assertEqual(cv.earlier_experience[0].title, "Full Stack Developer")

    def test_tailor_cv_overrides_inspected_title_for_full_stack_jd(self):
        client = llm_client.LLMClient()
        fake_json = """
        {
            "name": "Test",
            "title": "Software Engineer",
            "experience": [
                {
                    "title": "Template Role",
                    "company": "Inspected Pty Ltd",
                    "location": "Sydney",
                    "dates": "2024 - Present",
                    "bullets": []
                }
            ],
            "earlier_experience": [],
            "competencies": [],
            "projects": [],
            "education": [],
            "certifications": ""
        }
        """
        jd = JobDescription(
            raw_text="We need a Full Stack Engineer building React, Node.js, APIs, and web applications.",
            role_title="Full Stack Engineer",
            key_skills=["React", "Node.js", "TypeScript", "APIs"],
            summary="Build full-stack product features."
        )

        with patch.object(client, '_call_llm', return_value=fake_json):
            cv = client.tailor_cv("Master", jd)

        self.assertEqual(cv.experience[0].title, "Full Stack Developer")

    def test_tailor_cv_overrides_inspected_title_for_ai_jd(self):
        client = llm_client.LLMClient()
        fake_json = """
        {
            "name": "Test",
            "title": "Software Engineer",
            "experience": [
                {
                    "title": "Template Role",
                    "company": "Inspected Pty Ltd",
                    "location": "Sydney",
                    "dates": "2024 - Present",
                    "bullets": []
                }
            ],
            "earlier_experience": [],
            "competencies": [],
            "projects": [],
            "education": [],
            "certifications": ""
        }
        """
        jd = JobDescription(
            raw_text="We need a Principal AI Engineer for LLM agents, machine learning systems, and AI platforms.",
            role_title="Principal AI Engineer",
            key_skills=["LLM", "AI agents", "Machine Learning", "Python"],
            summary="Lead AI engineering work."
        )

        with patch.object(client, '_call_llm', return_value=fake_json):
            cv = client.tailor_cv("Master", jd)

        self.assertEqual(cv.experience[0].title, "Principal AI Engineer")

    def test_select_relevant_title_preserves_compact_slash_terms(self):
        client = llm_client.LLMClient()
        jd = JobDescription(raw_text="JD", role_title="AI Engineer", key_skills=["Machine Learning"], summary="AI role")

        self.assertEqual(client._select_relevant_title("AI/ML Engineer", jd), "AI/ML Engineer")
        self.assertEqual(client._select_relevant_title("AI/ML Engineer / Software Engineer", jd), "AI/ML Engineer")
        self.assertEqual(
            client._select_relevant_title("Principal AI Engineer/Software Engineer", jd),
            "Principal AI Engineer"
        )
        self.assertEqual(
            client._select_relevant_title("Principal AI Engineer / Software Engineer", jd),
            "Principal AI Engineer"
        )

    def test_tailor_cv_prompt_contains_ordering_rules(self):
        """Verify the tailor_cv prompt includes explicit reverse-chronological ordering instructions."""
        client = llm_client.LLMClient()
        fake_json = '{}'

        with patch.object(client, '_call_llm', return_value=fake_json):
            jd = JobDescription(raw_text="JD", role_title="Dev", key_skills=["Python"], summary="Role")
            client.tailor_cv("CV", jd, summarize_years=10)
            call_args = client._call_llm.call_args[0][0]

            self.assertIn("reverse-chronological order", call_args)
            self.assertIn("ORDERING", call_args)
            self.assertIn("'Present' counts as the most recent", call_args)

    def test_model_passthrough_openai(self):
        """Verify that --model pins the OpenAI call to that specific model."""
        mock_openai = sys.modules['openai']

        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = MagicMock()
        mock_create = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        mock_message.content = "Pinned Model Response"
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]

        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat = mock_chat
        mock_chat.completions = mock_completions
        mock_completions.create = mock_create
        mock_create.return_value = mock_response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock-openai-key"}, clear=True):
            client = llm_client.LLMClient(provider="openai", model="gpt-4o-mini")
            result = client._call_llm("Test Prompt")

            self.assertEqual(result, "Pinned Model Response")
            # Verify the pinned model was used (first positional arg to create)
            call_kwargs = mock_completions.create.call_args
            self.assertEqual(call_kwargs.kwargs.get("model") or call_kwargs[1].get("model"), "gpt-4o-mini")

    def test_model_passthrough_init(self):
        """Verify LLMClient stores the model attribute."""
        client = llm_client.LLMClient(provider="openai", model="gpt-4o")
        self.assertEqual(client.model, "gpt-4o")
        self.assertEqual(client.provider, "openai")

        # Default: no model pinned
        client_default = llm_client.LLMClient()
        self.assertIsNone(client_default.model)

    def test_openai_default_model_priority_starts_with_54_mini(self):
        """Verify OpenAI auto-selection tries gpt-5.4-mini first."""
        mock_openai = sys.modules['openai']

        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_completions = MagicMock()
        mock_create = MagicMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()

        mock_message.content = "Default Model Response"
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]

        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat = mock_chat
        mock_chat.completions = mock_completions
        mock_completions.create = mock_create
        mock_create.return_value = mock_response

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock-openai-key"}, clear=True):
            client = llm_client.LLMClient(provider="openai")
            result = client._call_llm("Test Prompt")

        self.assertEqual(result, "Default Model Response")
        call_kwargs = mock_completions.create.call_args
        self.assertEqual(call_kwargs.kwargs.get("model") or call_kwargs[1].get("model"), "gpt-5.4-mini")

    def test_discover_models_routes_to_openai(self):
        """Verify discover_models dispatches to _discover_openai_models for openai provider."""
        client = llm_client.LLMClient(provider="openai")
        with patch.object(client, '_discover_openai_models', return_value=['gpt-4o', 'gpt-4o-mini']) as mock_disc:
            result = client.discover_models()
            mock_disc.assert_called_once()
            self.assertEqual(result, ['gpt-4o', 'gpt-4o-mini'])

    def test_discover_models_routes_to_minimax(self):
        """Verify discover_models dispatches to _discover_minimax_models for minimax provider."""
        client = llm_client.LLMClient(provider="minimax")
        with patch.object(client, '_discover_minimax_models', return_value=['MiniMax-M2.7']) as mock_disc:
            result = client.discover_models()
            mock_disc.assert_called_once()
            self.assertEqual(result, ['MiniMax-M2.7'])

    def test_clean_json_removes_minimax_thinking(self):
        client = llm_client.LLMClient(provider="minimax")
        raw = '<think>reasoning</think>\nHere is JSON:\n{"name": "Jane"}\nThanks'
        self.assertEqual(client._clean_json(raw), '{"name": "Jane"}')

    def test_auto_provider_resolution(self):
        """Verify auto-detection picks the right provider from available credentials."""
        # Case 1: Only OPENAI_API_KEY → should resolve to 'openai'
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            with patch.object(llm_client.LLMClient, '_has_adc', return_value=False):
                client = llm_client.LLMClient(provider="auto")
                self.assertEqual(client.provider, "openai")
                self.assertEqual(client.api_key, "sk-test")

        # Case 2: Only GEMINI_API_KEY → should resolve to 'gemini'
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}, clear=True):
            with patch.object(llm_client.LLMClient, '_has_adc', return_value=False):
                client = llm_client.LLMClient(provider="auto")
                self.assertEqual(client.provider, "gemini")
                self.assertEqual(client.api_key, "gemini-test")

        # Case 3: Both keys → explicit GEMINI wins (primary provider)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test", "OPENAI_API_KEY": "sk-test"}, clear=True):
            with patch.object(llm_client.LLMClient, '_has_adc', return_value=False):
                client = llm_client.LLMClient(provider="auto")
                self.assertEqual(client.provider, "gemini")

        # Case 4: OPENAI_API_KEY + ADC → explicit key wins over ambient creds
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            with patch.object(llm_client.LLMClient, '_has_adc', return_value=True):
                client = llm_client.LLMClient(provider="auto")
                self.assertEqual(client.provider, "openai")

        # Case 5: Only MINIMAX_API_KEY → should resolve to 'minimax'
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "minimax-test"}, clear=True):
            with patch.object(llm_client.LLMClient, '_has_adc', return_value=False):
                client = llm_client.LLMClient(provider="auto")
                self.assertEqual(client.provider, "minimax")
                self.assertEqual(client.api_key, "minimax-test")

        # Case 6: No credentials → stays 'auto'
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(llm_client.LLMClient, '_has_adc', return_value=False):
                client = llm_client.LLMClient(provider="auto")
                self.assertEqual(client.provider, "auto")

if __name__ == '__main__':
    unittest.main()
