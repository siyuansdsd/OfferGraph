"""Tests for the LinkedIn Master agent builder."""

from unittest import TestCase
from unittest.mock import Mock, patch

from agent.agent.linkedin_master import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_ENV,
    LINKEDIN_MASTER_AGENT_NAME,
    LinkedInMasterConfig,
    build_linkedin_master_prompt,
    create_linkedin_master_agent,
    get_default_model,
    get_linkedin_master_tools,
)


class LinkedInMasterTest(TestCase):
    def test_get_default_model_uses_environment_override(self) -> None:
        with patch.dict("os.environ", {DEFAULT_MODEL_ENV: "test:model"}):
            self.assertEqual(get_default_model(), "test:model")

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_default_model(), DEFAULT_MODEL)

    def test_build_prompt_injects_content_context(self) -> None:
        prompt = build_linkedin_master_prompt(
            LinkedInMasterConfig(
                date="Fri Jun 12, 2026",
                industry="AI infrastructure",
                extra_need="include hiring-market impact",
                brand_name="OfferGraph",
                audience="technical founders",
                tone="calm and practical",
                publish_policy="draft_only",
            )
        )

        self.assertIn("linkedin-master", prompt)
        self.assertIn("AI infrastructure", prompt)
        self.assertIn("include hiring-market impact", prompt)
        self.assertIn("technical founders", prompt)
        self.assertIn("calm and practical", prompt)
        self.assertIn("draft_only", prompt)
        self.assertIn("Structured Output", prompt)
        self.assertIn("linkedin-editor", prompt)
        self.assertIn("memory-search", prompt)
        self.assertIn("github-project-inspector", prompt)
        self.assertIn("GitHub project evidence", prompt)
        self.assertIn("linkedin-image-search", prompt)
        self.assertIn("openai-image-generator", prompt)

    def test_build_prompt_defaults_to_publish_after_confirmation(self) -> None:
        prompt = build_linkedin_master_prompt(
            LinkedInMasterConfig(date="Fri Jun 12, 2026")
        )

        self.assertIn("publish_after_confirmation", prompt)
        self.assertIn("draft_only=false", prompt)
        self.assertIn("publish=true", prompt)

    def test_tool_set_wires_auth_and_content_editor(self) -> None:
        self.assertEqual(
            [tool.name for tool in get_linkedin_master_tools()],
            [
                "memory-search",
                "tavily_search",
                "think_tool",
                "ls",
                "read_file",
                "write_file",
                "github-project-inspector",
                "linkedin-image-search",
                "openai-image-generator",
                "linkedin-editor",
            ],
        )

    def test_create_agent_uses_linkedin_master_config(self) -> None:
        fake_agent = Mock()
        with patch("agent.agent.linkedin_master.create_agent", return_value=fake_agent) as create_mock:
            result = create_linkedin_master_agent(
                model="test:model",
                config=LinkedInMasterConfig(
                    date="Fri Jun 12, 2026",
                    industry="fintech",
                    extra_need="focus on risk analysis",
                ),
            )

        self.assertIs(result, fake_agent)
        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["model"], "test:model")
        self.assertEqual(kwargs["name"], LINKEDIN_MASTER_AGENT_NAME)
        self.assertIn("fintech", kwargs["system_prompt"])
        self.assertIn("focus on risk analysis", kwargs["system_prompt"])
        self.assertIn("linkedin-editor", [tool.name for tool in kwargs["tools"]])

    def test_create_agent_appends_extra_tools(self) -> None:
        fake_agent = Mock()
        extra_tool = Mock()
        extra_tool.name = "extra-tool"

        with patch("agent.agent.linkedin_master.create_agent", return_value=fake_agent) as create_mock:
            create_linkedin_master_agent(
                model="test:model",
                config=LinkedInMasterConfig(date="Fri Jun 12, 2026"),
                extra_tools=[extra_tool],
            )

        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["tools"][-1], extra_tool)
