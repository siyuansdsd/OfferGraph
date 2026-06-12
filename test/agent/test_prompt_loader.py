"""Tests for agent prompt loading."""

from unittest import TestCase

from agent.prompt import load_prompt, render_prompt, required_prompt_variables


class PromptLoaderTest(TestCase):
    def test_load_prompt_adds_markdown_suffix(self) -> None:
        prompt = load_prompt("plan_master")

        self.assertIn("PLAN MASTER", prompt)
        self.assertIn("{todo_usage_instructions}", prompt)

    def test_required_prompt_variables(self) -> None:
        variables = required_prompt_variables("Hello {name}, today is {date}.")

        self.assertEqual(variables, {"name", "date"})

    def test_render_prompt_requires_values(self) -> None:
        with self.assertRaises(KeyError):
            render_prompt("researcher")

    def test_render_prompt_formats_values(self) -> None:
        prompt = render_prompt("researcher", date="Wed Jun 10, 2026")

        self.assertIn("Wed Jun 10, 2026", prompt)
        self.assertIn("research-agent", prompt)

    def test_render_linkedin_master_prompt(self) -> None:
        prompt = render_prompt(
            "linkedin_master",
            date="Fri Jun 12, 2026",
            industry="AI infrastructure",
            extra_need="include hiring-market impact",
            brand_name="OfferGraph",
            audience="technical founders",
            tone="calm and practical",
            publish_policy="draft_only",
        )

        self.assertIn("LINKEDIN MASTER", prompt)
        self.assertIn("AI infrastructure", prompt)
        self.assertIn("include hiring-market impact", prompt)
