"""Tests for persistent job application profile storage."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from tools.job_application.profile_store import (
    job_profile_read,
    job_profile_upsert,
    read_job_profile,
    resolve_job_profile_questions,
    upsert_job_profile,
)


class JobProfileStoreTest(TestCase):
    def test_read_job_profile_creates_default_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "profile.json"

            profile = read_job_profile(profile_path)

            self.assertTrue(profile_path.exists())
            self.assertIn("profile", profile)
            self.assertIn("work_authorization", profile)
            self.assertEqual(
                profile["answers"]["diversity_questions_preference"],
                "prefer_not_to_answer",
            )

    def test_upsert_job_profile_supports_dotted_keys(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "profile.json"

            profile = upsert_job_profile(
                {
                    "profile.email": "alex@example.com",
                    "work_authorization.requires_sponsorship": "No",
                },
                profile_path,
            )

            self.assertEqual(profile["profile"]["email"], "alex@example.com")
            self.assertEqual(profile["work_authorization"]["requires_sponsorship"], "No")
            saved = read_job_profile(profile_path)
            self.assertEqual(saved["profile"]["email"], "alex@example.com")

    def test_resolve_questions_uses_existing_profile_answer(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "profile.json"
            upsert_job_profile(
                {
                    "profile.legal_name": "Alex Example",
                    "work_authorization.right_to_work": "Yes",
                },
                profile_path,
            )

            result = resolve_job_profile_questions(
                [
                    {"label": "Full name", "type": "text", "name": "full_name"},
                    {
                        "label": "Do you have the right to work in Australia?",
                        "type": "select",
                        "name": "work_auth",
                    },
                ],
                profile_path=profile_path,
                interactive=False,
            )

            self.assertEqual(result["status"], "resolved")
            self.assertEqual(
                [answer["answer"] for answer in result["answers"]],
                ["Alex Example", "Yes"],
            )

    def test_resolve_questions_prompts_and_persists_missing_answer(self) -> None:
        prompts: list[str] = []
        outputs: list[str] = []

        with TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "profile.json"
            result = resolve_job_profile_questions(
                [
                    {
                        "label": "Do you require visa sponsorship?",
                        "type": "radio",
                        "name": "sponsorship",
                    }
                ],
                profile_path=profile_path,
                interactive=True,
                prompt_func=lambda prompt: prompts.append(prompt) or "No",
                output_func=outputs.append,
            )
            profile = read_job_profile(profile_path)

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["answers"][0]["answer"], "No")
        self.assertEqual(profile["work_authorization"]["requires_sponsorship"], "No")
        self.assertTrue(profile["question_history"])
        self.assertIn("visa sponsorship", prompts[0])
        self.assertTrue(any("I need a few answers" in line for line in outputs))

    def test_resolve_questions_reprompts_incomplete_answers(self) -> None:
        responses = iter(["", "120000 AUD"])

        with TemporaryDirectory() as tmp_dir:
            profile_path = Path(tmp_dir) / "profile.json"
            result = resolve_job_profile_questions(
                [{"label": "Expected salary", "type": "text", "name": "salary"}],
                profile_path=profile_path,
                interactive=True,
                max_rounds=2,
                prompt_func=lambda _: next(responses),
                output_func=lambda _: None,
            )
            profile = read_job_profile(profile_path)

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(profile["answers"]["salary_expectation"], "120000 AUD")

    def test_profile_tools_wrap_store_functions(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            profile_path = str(Path(tmp_dir) / "profile.json")

            update_result = job_profile_upsert.invoke(
                {
                    "profile_path": profile_path,
                    "updates": {"profile.phone": "+61 400 000 000"},
                }
            )
            read_result = job_profile_read.invoke({"profile_path": profile_path})

        self.assertEqual(update_result["status"], "ready")
        self.assertEqual(
            read_result["profile"]["profile"]["phone"],
            "+61 400 000 000",
        )
