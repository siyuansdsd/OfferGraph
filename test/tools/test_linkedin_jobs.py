"""Tests for LinkedIn Jobs Playwright tools."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from playwright.sync_api import Error as PlaywrightError

from agent.memory.models import MemoryRecord
from tools.linkedin.jobs import (
    APPLICATION_COVER_LETTER_FILE_INPUT_SELECTORS,
    APPLICATION_FILE_INPUT_SELECTORS,
    APPLICATION_SUBMIT_BUTTON_SELECTORS,
    EASY_APPLY_BUTTON_SELECTORS,
    EXTERNAL_APPLICATION_ADVANCE_SELECTORS,
    EXTERNAL_APPLY_BUTTON_SELECTORS,
    JOB_COPY_LINK_BUTTON_SELECTORS,
    JOB_MORE_ACTIONS_BUTTON_SELECTORS,
    JOB_SHARE_BUTTON_SELECTORS,
    build_linkedin_jobs_search_url,
    copy_linkedin_job_link_from_share,
    detect_application_platform,
    extract_fit_keywords,
    fill_external_application_answers,
    explore_linkedin_jobs,
    continue_linkedin_job_application_with_materials,
    linkedin_job_apply_draft,
    linkedin_job_tailored_apply_draft,
    linkedin_jobs_explorer,
    open_linkedin_job_apply_draft,
    open_linkedin_job_tailored_apply_draft,
    score_linkedin_job_fit,
    select_application_material_paths,
)
from tools.playwright_template import PlaywrightToolSpec, PlaywrightToolTrace


class FakeJobsLocator:
    def __init__(self, *, visible: bool = True, on_click=None) -> None:
        self.visible = visible
        self.on_click = on_click
        self.clicked = False
        self.input_files = None

    @property
    def first(self):
        return self

    def wait_for(self, state: str, timeout: int) -> None:
        if not self.visible:
            raise PlaywrightError("not visible")
        self.wait_state = state
        self.wait_timeout = timeout

    def click(self) -> None:
        self.clicked = True
        if self.on_click:
            self.on_click()

    def set_input_files(self, files: str) -> None:
        self.input_files = files


class FakeJobsPage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.goto_calls = []
        self.load_state_calls = []
        self.evaluate_calls = []
        self.screenshot_calls = []
        self.easy_apply_button = FakeJobsLocator()
        self.share_button = FakeJobsLocator()
        self.more_actions_button = FakeJobsLocator(visible=False)
        self.copy_link_button = FakeJobsLocator()
        self.external_apply_button = FakeJobsLocator()
        self.external_advance_button = FakeJobsLocator(visible=False)
        self.file_input = FakeJobsLocator()
        self.cover_letter_input = FakeJobsLocator()
        self.submit_button = FakeJobsLocator()
        self.hidden_locator = FakeJobsLocator(visible=False)
        self.context = None
        self.clipboard_text = "https://www.linkedin.com/jobs/view/1/?trackingId=copied"
        self.filled_answers = []
        self.external_form_state = {
            "fields": [],
            "required_unfilled_fields": [],
            "visible_file_inputs": 1,
            "submit_ready": False,
        }

    def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.url = url
        self.goto_calls.append((url, wait_until, timeout))

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.load_state_calls.append((state, timeout))

    def wait_for_timeout(self, timeout: int) -> None:
        self.timeout = timeout

    def evaluate(self, script: str, arg=None):
        self.evaluate_calls.append((script, arg))
        if "__offergraphFillExternalApplicationAnswers" in script:
            self.filled_answers = list((arg or {}).get("answers") or [])
            self.external_form_state = {
                "fields": [
                    {
                        "label": answer.get("label", ""),
                        "tag": "select",
                        "type": "select",
                        "required": True,
                        "has_value": True,
                        "name": answer.get("name", ""),
                    }
                    for answer in self.filled_answers
                ],
                "required_unfilled_fields": [],
                "visible_file_inputs": 1,
                "submit_ready": True,
            }
            return {
                "filled_count": len(self.filled_answers),
                "filled": [
                    {
                        "question_key": answer.get("question_key"),
                        "label": answer.get("label"),
                        "name": answer.get("name"),
                        "tag": "select",
                        "type": "select",
                    }
                    for answer in self.filled_answers
                ],
                "unfilled": [],
            }
        if "navigator.clipboard.readText" in script:
            return self.clipboard_text
        if "required_unfilled_fields" in script:
            return self.external_form_state
        if "descriptionSelectors" in script:
            return {
                "title": "AI Engineer",
                "company": "OfferGraph Labs",
                "description": "Build LLM tooling with Python, LangGraph, and Playwright.",
                "url": "https://www.linkedin.com/jobs/view/1",
            }
        return [
            {
                "title": "AI Engineer",
                "company": "OfferGraph Labs",
                "location": "Sydney, NSW",
                "url": "https://www.linkedin.com/jobs/view/1",
                "easy_apply": True,
                "snippet": "Python LangGraph LLM Playwright remote friendly",
            },
            {
                "title": "Frontend Developer",
                "company": "Example Co",
                "location": "Melbourne",
                "url": "https://www.linkedin.com/jobs/view/2",
                "easy_apply": False,
                "snippet": "React CSS dashboard",
            },
        ]

    def locator(self, selector: str):
        if selector in EASY_APPLY_BUTTON_SELECTORS:
            return self.easy_apply_button
        if selector in JOB_SHARE_BUTTON_SELECTORS:
            return self.share_button
        if selector in JOB_MORE_ACTIONS_BUTTON_SELECTORS:
            return self.more_actions_button
        if selector in JOB_COPY_LINK_BUTTON_SELECTORS:
            return self.copy_link_button
        if selector in EXTERNAL_APPLY_BUTTON_SELECTORS:
            return self.external_apply_button
        if selector in EXTERNAL_APPLICATION_ADVANCE_SELECTORS:
            return self.external_advance_button
        if selector in APPLICATION_COVER_LETTER_FILE_INPUT_SELECTORS:
            return self.cover_letter_input
        if selector in APPLICATION_FILE_INPUT_SELECTORS:
            return self.file_input
        if selector in APPLICATION_SUBMIT_BUTTON_SELECTORS:
            return self.submit_button
        return self.hidden_locator

    def screenshot(self, path: str, full_page: bool) -> None:
        self.screenshot_calls.append((path, full_page))

    def content(self) -> str:
        return "<html><body>LinkedIn Jobs</body></html>"


class FakeJobsContext:
    def __init__(self, page: FakeJobsPage) -> None:
        self.page = page
        self.page.context = self
        self.permissions = []

    def new_page(self) -> FakeJobsPage:
        return self.page

    def grant_permissions(self, permissions, origin: str) -> None:
        self.permissions.append((permissions, origin))


class FakeJobsBrowser:
    def __init__(self, page: FakeJobsPage) -> None:
        self.page = page
        self.closed = False

    def new_context(self, **kwargs):
        self.context_kwargs = kwargs
        return FakeJobsContext(self.page)

    def close(self) -> None:
        self.closed = True


class FakeJobsBrowserType:
    def __init__(self, browser: FakeJobsBrowser) -> None:
        self.browser = browser

    def launch(self, headless: bool):
        self.headless = headless
        return self.browser


class FakeJobsPlaywright:
    def __init__(self, browser_type: FakeJobsBrowserType) -> None:
        self.chromium = browser_type


class FakeJobsManager:
    def __init__(self, browser_type: FakeJobsBrowserType) -> None:
        self.playwright = FakeJobsPlaywright(browser_type)

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class LinkedInJobsTest(TestCase):
    def test_build_linkedin_jobs_search_url_encodes_query_and_location(self) -> None:
        self.assertEqual(
            build_linkedin_jobs_search_url("AI Engineer", "Sydney NSW"),
            "https://www.linkedin.com/jobs/search/?keywords=AI+Engineer&location=Sydney+NSW",
        )

    def test_score_linkedin_job_fit_uses_profile_keywords(self) -> None:
        job = {
            "title": "AI Engineer",
            "company": "OfferGraph",
            "location": "Remote",
            "snippet": "Python LangGraph Playwright LLM tooling",
        }

        scored = score_linkedin_job_fit(
            job,
            candidate_profile="Python LangGraph LLM backend",
            required_keywords=["Playwright"],
        )

        self.assertGreater(scored["fit_score"], 50)
        self.assertIn("Playwright", scored["matched_keywords"])
        self.assertIn("Python", scored["matched_keywords"])

    def test_extract_fit_keywords_deduplicates_stopwords(self) -> None:
        self.assertEqual(
            extract_fit_keywords("Python Python and LangGraph", ["Python", "LLM"]),
            ["Python", "LLM", "LangGraph"],
        )

    def test_detect_application_platform_classifies_known_ats_domains(self) -> None:
        self.assertEqual(
            detect_application_platform("https://boards.greenhouse.io/example/jobs/1"),
            "greenhouse",
        )
        self.assertEqual(
            detect_application_platform("https://company.myworkdayjobs.com/job/1"),
            "workday",
        )

    def test_select_application_material_paths_classifies_generated_files(self) -> None:
        materials = select_application_material_paths(
            [
                "/tmp/Tailored_CV_CoverLetter.docx",
                "/tmp/Tailored_CV.docx",
                "/tmp/Tailored_CV.tex",
            ]
        )

        self.assertEqual(Path(materials["resume_path"]).name, "Tailored_CV.docx")
        self.assertEqual(
            Path(materials["cover_letter_path"]).name,
            "Tailored_CV_CoverLetter.docx",
        )

    def test_explore_linkedin_jobs_extracts_and_records_trace(self) -> None:
        page = FakeJobsPage()
        browser = FakeJobsBrowser(page)
        browser_type = FakeJobsBrowserType(browser)
        record = MemoryRecord(
            module="linkedin_jobs",
            kind="browser_trace",
            task="Explore jobs",
            summary="ok",
        )

        with patch(
            "tools.playwright_template.record_browser_trace_safely",
            return_value=record,
        ):
            result = explore_linkedin_jobs(
                query="AI Engineer",
                location="Sydney",
                candidate_profile="Python LangGraph",
                required_keywords=["LLM"],
                easy_apply_only=True,
                limit=5,
                session_state_path=".auth/linkedin.json",
                headless=True,
                playwright_factory=lambda: FakeJobsManager(browser_type),
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["title"], "AI Engineer")
        self.assertTrue(result["jobs"][0]["easy_apply"])
        self.assertTrue(page.screenshot_calls)
        self.assertTrue(browser.closed)

    def test_linkedin_jobs_explorer_reports_missing_auth(self) -> None:
        with patch("tools.linkedin.jobs.Path.exists", return_value=False):
            result = linkedin_jobs_explorer.invoke(
                {
                    "query": "AI Engineer",
                    "session_state_path": ".auth/missing.json",
                    "execution_mode": "approve-mode",
                }
            )

        self.assertEqual(result["status"], "needs_approval")
        self.assertIn("linkedin-auth-setup", result["approval"]["action"])

    def test_open_linkedin_job_apply_draft_stops_before_submit(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            resume_path = Path(tmp_dir) / "resume.pdf"
            resume_path.write_bytes(b"pdf")
            page = FakeJobsPage()
            browser = FakeJobsBrowser(page)
            browser_type = FakeJobsBrowserType(browser)
            record = MemoryRecord(
                module="linkedin_jobs",
                kind="browser_trace",
                task="Apply draft",
                summary="ok",
            )

            with patch(
                "tools.playwright_template.record_browser_trace_safely",
                return_value=record,
            ):
                result = open_linkedin_job_apply_draft(
                    job_url="https://www.linkedin.com/jobs/view/1",
                    resume_path=str(resume_path),
                    submit=False,
                    session_state_path=".auth/linkedin.json",
                    headless=True,
                    playwright_factory=lambda: FakeJobsManager(browser_type),
                )

        self.assertEqual(result["status"], "review_ready")
        self.assertTrue(page.easy_apply_button.clicked)
        self.assertEqual(page.file_input.input_files, str(resume_path.resolve()))
        self.assertFalse(page.submit_button.clicked)
        self.assertFalse(result["submitted"])

    def test_open_linkedin_job_apply_draft_uploads_cover_letter(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            resume_path = Path(tmp_dir) / "resume.pdf"
            cover_path = Path(tmp_dir) / "cover_letter.docx"
            resume_path.write_bytes(b"pdf")
            cover_path.write_bytes(b"docx")
            page = FakeJobsPage()
            browser = FakeJobsBrowser(page)
            browser_type = FakeJobsBrowserType(browser)

            with patch("tools.playwright_template.record_browser_trace_safely"):
                result = open_linkedin_job_apply_draft(
                    job_url="https://www.linkedin.com/jobs/view/1",
                    resume_path=str(resume_path),
                    cover_letter_path=str(cover_path),
                    submit=False,
                    session_state_path=".auth/linkedin.json",
                    headless=True,
                    playwright_factory=lambda: FakeJobsManager(browser_type),
                )

        self.assertEqual(result["status"], "review_ready")
        self.assertEqual(page.file_input.input_files, str(resume_path.resolve()))
        self.assertEqual(page.cover_letter_input.input_files, str(cover_path.resolve()))
        self.assertTrue(result["resume_uploaded"])
        self.assertTrue(result["cover_letter_uploaded"])

    def test_open_linkedin_job_tailored_apply_draft_generates_and_uploads_materials(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            resume_path = Path(tmp_dir) / "Tailored_CV.docx"
            cover_path = Path(tmp_dir) / "Tailored_CV_CoverLetter.docx"
            resume_path.write_bytes(b"resume")
            cover_path.write_bytes(b"cover")
            page = FakeJobsPage()
            browser = FakeJobsBrowser(page)
            browser_type = FakeJobsBrowserType(browser)

            def fake_tailor(**kwargs):
                self.assertEqual(
                    kwargs["job_url"],
                    "https://www.linkedin.com/jobs/view/1/?trackingId=copied",
                )
                self.assertEqual(kwargs["job_description"], "")
                return {
                    "status": "ready",
                    "message": "Tailored CV workflow finished.",
                    "generated_files": [str(resume_path), str(cover_path)],
                }

            with patch("tools.playwright_template.record_browser_trace_safely"):
                result = open_linkedin_job_tailored_apply_draft(
                    job_url="https://www.linkedin.com/jobs/view/1",
                    submit=False,
                    session_state_path=".auth/linkedin.json",
                    headless=True,
                    playwright_factory=lambda: FakeJobsManager(browser_type),
                    cv_tailoring_func=fake_tailor,
                )

        self.assertEqual(result["status"], "review_ready")
        self.assertTrue(page.share_button.clicked)
        self.assertTrue(page.copy_link_button.clicked)
        self.assertEqual(page.file_input.input_files, str(resume_path.resolve()))
        self.assertEqual(page.cover_letter_input.input_files, str(cover_path.resolve()))
        self.assertEqual(
            result["copied_job_url"],
            "https://www.linkedin.com/jobs/view/1/?trackingId=copied",
        )
        self.assertIn("copy_link", result)
        self.assertEqual(
            Path(result["application_materials"]["resume_path"]).name,
            "Tailored_CV.docx",
        )
        self.assertIn("cv_tailoring", result)

    def test_copy_job_link_uses_more_actions_when_share_hidden(self) -> None:
        page = FakeJobsPage()
        page.share_button = FakeJobsLocator(visible=False)
        page.more_actions_button = FakeJobsLocator(
            visible=True,
            on_click=lambda: setattr(page.share_button, "visible", True),
        )
        trace = PlaywrightToolTrace(
            PlaywrightToolSpec(
                tool_name="linkedin-job-copy-link",
                task="Copy job link",
                start_url="https://www.linkedin.com/jobs/view/1",
                module="linkedin_jobs",
            )
        )

        result = copy_linkedin_job_link_from_share(
            page,
            trace,
            fallback_url="https://www.linkedin.com/jobs/view/1",
        )

        self.assertTrue(page.more_actions_button.clicked)
        self.assertTrue(page.share_button.clicked)
        self.assertTrue(page.copy_link_button.clicked)
        self.assertTrue(result["copied_from_clipboard"])
        self.assertTrue(result["more_clicked"])

    def test_continue_application_records_external_platform(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            resume_path = Path(tmp_dir) / "resume.pdf"
            resume_path.write_bytes(b"pdf")
            page = FakeJobsPage()
            page.easy_apply_button = FakeJobsLocator(visible=False)
            page.external_apply_button.on_click = (
                lambda: setattr(page, "url", "https://boards.greenhouse.io/acme/jobs/1")
            )
            browser = FakeJobsBrowser(page)
            browser_type = FakeJobsBrowserType(browser)

            with patch("tools.playwright_template.record_browser_trace_safely"):
                result = continue_linkedin_job_application_with_materials(
                    job_url="https://www.linkedin.com/jobs/view/1",
                    resume_path=str(resume_path),
                    session_state_path=".auth/linkedin.json",
                    headless=True,
                    playwright_factory=lambda: FakeJobsManager(browser_type),
                )

        self.assertEqual(result["status"], "external_application_draft_open")
        self.assertEqual(result["application_platform"], "greenhouse")
        self.assertEqual(result["memory_module"], "job_application_greenhouse")
        self.assertTrue(page.external_apply_button.clicked)
        self.assertTrue(result["resume_uploaded"])

    def test_external_application_advances_until_manual_input_needed(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            resume_path = Path(tmp_dir) / "resume.pdf"
            resume_path.write_bytes(b"pdf")
            page = FakeJobsPage()
            page.easy_apply_button = FakeJobsLocator(visible=False)
            page.external_advance_button = FakeJobsLocator(visible=True)
            form_states = [
                {
                    "fields": [
                        {
                            "label": "Work authorization",
                            "tag": "select",
                            "type": "select",
                            "required": True,
                            "has_value": False,
                            "name": "work_auth",
                        }
                    ],
                    "required_unfilled_fields": [
                        {
                            "label": "Work authorization",
                            "tag": "select",
                            "type": "select",
                            "required": True,
                            "has_value": False,
                            "name": "work_auth",
                        }
                    ],
                    "visible_file_inputs": 1,
                    "submit_ready": False,
                },
            ]

            def next_form_state():
                page.external_form_state = form_states.pop(0) if form_states else page.external_form_state

            page.external_apply_button.on_click = (
                lambda: setattr(page, "url", "https://boards.greenhouse.io/acme/jobs/1")
            )
            page.external_advance_button.on_click = next_form_state
            browser = FakeJobsBrowser(page)
            browser_type = FakeJobsBrowserType(browser)

            with patch("tools.playwright_template.record_browser_trace_safely"):
                result = continue_linkedin_job_application_with_materials(
                    job_url="https://www.linkedin.com/jobs/view/1",
                    resume_path=str(resume_path),
                    session_state_path=".auth/linkedin.json",
                    headless=True,
                    playwright_factory=lambda: FakeJobsManager(browser_type),
                )

        self.assertEqual(result["status"], "external_application_needs_input")
        self.assertEqual(result["application_steps"], 1)
        self.assertEqual(
            result["application_blockers"][0]["label"],
            "Work authorization",
        )
        self.assertTrue(page.external_advance_button.clicked)

    def test_external_application_fills_resolved_profile_answers(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            resume_path = Path(tmp_dir) / "resume.pdf"
            resume_path.write_bytes(b"pdf")
            page = FakeJobsPage()
            page.easy_apply_button = FakeJobsLocator(visible=False)
            page.external_form_state = {
                "fields": [
                    {
                        "label": "Work authorization",
                        "tag": "select",
                        "type": "select",
                        "required": True,
                        "has_value": False,
                        "name": "work_auth",
                    }
                ],
                "required_unfilled_fields": [
                    {
                        "label": "Work authorization",
                        "tag": "select",
                        "type": "select",
                        "required": True,
                        "has_value": False,
                        "name": "work_auth",
                    }
                ],
                "visible_file_inputs": 1,
                "submit_ready": False,
            }
            page.external_apply_button.on_click = (
                lambda: setattr(page, "url", "https://boards.greenhouse.io/acme/jobs/1")
            )
            browser = FakeJobsBrowser(page)
            browser_type = FakeJobsBrowserType(browser)

            with patch("tools.playwright_template.record_browser_trace_safely"), patch(
                "tools.linkedin.jobs.resolve_job_profile_questions",
                return_value={
                    "status": "resolved",
                    "answers": [
                        {
                            "question_key": "work_auth",
                            "label": "Work authorization",
                            "name": "work_auth",
                            "type": "select",
                            "answer": "Yes",
                            "source": "profile",
                            "profile_path": "work_authorization.right_to_work",
                        }
                    ],
                    "unresolved_questions": [],
                    "profile_updated": False,
                    "profile_path": "/tmp/profile.json",
                },
            ):
                result = continue_linkedin_job_application_with_materials(
                    job_url="https://www.linkedin.com/jobs/view/1",
                    resume_path=str(resume_path),
                    session_state_path=".auth/linkedin.json",
                    headless=True,
                    playwright_factory=lambda: FakeJobsManager(browser_type),
                )

        self.assertEqual(result["status"], "external_review_ready")
        self.assertTrue(result["review_ready"])
        self.assertEqual(result["fill_result"]["filled_count"], 1)
        self.assertEqual(page.filled_answers[0]["answer"], "Yes")

    def test_fill_external_application_answers_records_unfilled_errors(self) -> None:
        page = FakeJobsPage()
        trace = PlaywrightToolTrace(
            PlaywrightToolSpec(
                tool_name="external-apply",
                task="Fill answers",
                start_url="https://example.com/apply",
                module="job_application_external",
            )
        )

        result = fill_external_application_answers(
            page,
            trace,
            [
                {
                    "question_key": "salary",
                    "label": "Expected salary",
                    "name": "salary",
                    "type": "text",
                    "answer": "120000 AUD",
                }
            ],
        )

        self.assertEqual(result["filled_count"], 1)
        self.assertEqual(page.filled_answers[0]["answer"], "120000 AUD")
        self.assertEqual(trace.actions[-1].type, "fill")

    def test_open_linkedin_job_apply_draft_requires_confirmation_to_submit(self) -> None:
        page = FakeJobsPage()
        browser = FakeJobsBrowser(page)
        browser_type = FakeJobsBrowserType(browser)
        with patch("tools.playwright_template.record_browser_trace_safely"):
            result = open_linkedin_job_apply_draft(
                job_url="https://www.linkedin.com/jobs/view/1",
                submit=True,
                session_state_path=".auth/linkedin.json",
                headless=True,
                confirm_submit=lambda _: "n",
                playwright_factory=lambda: FakeJobsManager(browser_type),
            )

        self.assertEqual(result["status"], "review_ready")
        self.assertFalse(page.submit_button.clicked)
        self.assertFalse(result["submit_confirmed"])

    def test_linkedin_job_apply_draft_reports_missing_auth(self) -> None:
        with patch("tools.linkedin.jobs.Path.exists", return_value=False):
            result = linkedin_job_apply_draft.invoke(
                {
                    "job_url": "https://www.linkedin.com/jobs/view/1",
                    "session_state_path": ".auth/missing.json",
                    "execution_mode": "approve-mode",
                }
            )

        self.assertEqual(result["status"], "needs_approval")

    def test_linkedin_job_tailored_apply_draft_reports_missing_auth(self) -> None:
        with patch("tools.linkedin.jobs.Path.exists", return_value=False):
            result = linkedin_job_tailored_apply_draft.invoke(
                {
                    "job_url": "https://www.linkedin.com/jobs/view/1",
                    "session_state_path": ".auth/missing.json",
                    "execution_mode": "approve-mode",
                }
            )

        self.assertEqual(result["status"], "needs_approval")
