"""Tests for the Plan Master agent builder."""

from unittest import TestCase
from unittest.mock import Mock, patch

from agent.agent.plan_master import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_ENV,
    PLAN_MASTER_AGENT_NAME,
    RESEARCH_AGENT_NAME,
    build_linkedin_subagent,
    PlanMasterConfig,
    build_plan_master_prompt,
    build_plan_master_subagents,
    build_research_subagent,
    build_subagent_usage_instructions,
    create_plan_master_agent,
    get_default_model,
    get_plan_master_tools,
    get_research_tools,
)


class PlanMasterTest(TestCase):
    def test_get_default_model_uses_environment_override(self) -> None:
        with patch.dict("os.environ", {DEFAULT_MODEL_ENV: "test:model"}):
            self.assertEqual(get_default_model(), "test:model")

        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_default_model(), DEFAULT_MODEL)

    def test_build_subagent_usage_instructions_uses_config(self) -> None:
        config = PlanMasterConfig(
            max_concurrent_research_units=2,
            max_researcher_iterations=4,
            date="Wed Jun 10, 2026",
        )

        prompt = build_subagent_usage_instructions(config)

        self.assertIn("2 parallel research units", prompt)
        self.assertIn("4 delegation rounds", prompt)
        self.assertIn("Wed Jun 10, 2026", prompt)
        self.assertIn("call `linkedin-editor`", prompt)
        self.assertIn("draft_only=false", prompt)
        self.assertIn("publish=true", prompt)

    def test_build_plan_master_prompt_contains_notebook_patterns(self) -> None:
        prompt = build_plan_master_prompt(
            PlanMasterConfig(
                date="Wed Jun 10, 2026",
                industry="AI infrastructure",
                extra_need="include a hiring-market angle",
            )
        )

        self.assertIn("TODO MANAGEMENT", prompt)
        self.assertIn("FILE SYSTEM USAGE", prompt)
        self.assertIn("SUB-AGENT DELEGATION", prompt)
        self.assertIn("plan-master", prompt)
        self.assertIn("linkedin-master", prompt)
        self.assertIn("LINKEDIN TASK HANDOFF", prompt)
        self.assertIn("linkedin-editor.post_text", prompt)
        self.assertIn("draft_only=false", prompt)
        self.assertIn("publish=true", prompt)
        self.assertIn("draft_ready", prompt)
        self.assertIn("AI infrastructure", prompt)
        self.assertIn("include a hiring-market angle", prompt)

    def test_plan_master_prompt_has_safe_industry_defaults(self) -> None:
        prompt = build_plan_master_prompt(PlanMasterConfig(date="Wed Jun 10, 2026"))

        self.assertIn("AI Engineer and Software Engineer", prompt)
        self.assertIn("Good performance of https://github.com/siyuansdsd/OfferGraph", prompt)

    def test_build_research_subagent(self) -> None:
        subagent = build_research_subagent(PlanMasterConfig(date="Wed Jun 10, 2026"))

        self.assertEqual(subagent["name"], RESEARCH_AGENT_NAME)
        self.assertIn("one topic at a time", subagent["description"])
        self.assertEqual([tool.name for tool in subagent["tools"]], ["tavily_search", "think_tool"])
        self.assertIn("Wed Jun 10, 2026", subagent["system_prompt"])

    def test_build_linkedin_subagent(self) -> None:
        subagent = build_linkedin_subagent(
            PlanMasterConfig(
                date="Wed Jun 10, 2026",
                industry="fintech",
                extra_need="focus on risk analysis",
            )
        )

        self.assertEqual(subagent["name"], "linkedin-master")
        self.assertIn("LinkedIn content creation", subagent["description"])
        self.assertIn("linkedin-editor", subagent["description"])
        self.assertIn("fintech", subagent["system_prompt"])
        self.assertIn("focus on risk analysis", subagent["system_prompt"])
        self.assertIn("linkedin-editor", [tool.name for tool in subagent["tools"]])

    def test_build_plan_master_subagents(self) -> None:
        subagents = build_plan_master_subagents(PlanMasterConfig(date="Wed Jun 10, 2026"))

        self.assertEqual(
            [subagent["name"] for subagent in subagents],
            ["research-agent", "linkedin-master"],
        )

    def test_tool_sets(self) -> None:
        self.assertEqual(
            [tool.name for tool in get_research_tools()],
            ["tavily_search", "think_tool"],
        )
        self.assertEqual(
            [tool.name for tool in get_plan_master_tools()],
            [
                "ls",
                "read_file",
                "write_file",
                "write_todos",
                "read_todos",
                "tavily_search",
                "think_tool",
            ],
        )

    def test_create_plan_master_agent_uses_deepagents_by_default(self) -> None:
        fake_agent = Mock()
        with patch("agent.agent.plan_master.create_deep_agent", return_value=fake_agent) as create_mock:
            result = create_plan_master_agent(
                model="test:model",
                config=PlanMasterConfig(
                    date="Wed Jun 10, 2026",
                    industry="fintech",
                    extra_need="make it concise",
                ),
            )

        self.assertIs(result, fake_agent)
        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["model"], "test:model")
        self.assertEqual(kwargs["name"], PLAN_MASTER_AGENT_NAME)
        self.assertEqual([tool.name for tool in kwargs["tools"]], ["tavily_search", "think_tool"])
        self.assertEqual(
            [subagent["name"] for subagent in kwargs["subagents"]],
            [RESEARCH_AGENT_NAME, "linkedin-master"],
        )
        self.assertIn("fintech", kwargs["system_prompt"])
        self.assertIn("make it concise", kwargs["system_prompt"])

    def test_create_plan_master_agent_can_use_langchain_agent(self) -> None:
        fake_agent = Mock()
        with patch("agent.agent.plan_master.create_agent", return_value=fake_agent) as create_mock:
            result = create_plan_master_agent(
                model="test:model",
                config=PlanMasterConfig(date="Wed Jun 10, 2026"),
                use_deepagents=False,
            )

        self.assertIs(result, fake_agent)
        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["model"], "test:model")
        self.assertEqual(kwargs["name"], PLAN_MASTER_AGENT_NAME)
        self.assertIn("plan-master", kwargs["system_prompt"])
