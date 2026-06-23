"""LinkedIn Jobs Playwright tools."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote_plus, urlparse

from langchain_core.tools import tool
from playwright.sync_api import sync_playwright
from pydantic import BaseModel, Field

from tools.approval import ApprovalRequest, request_user_approval
from tools.linkedin.content_editor import (
    DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    LINKEDIN_AUTH_SETUP_COMMAND,
)
from tools.job_application.profile_store import (
    question_key,
    resolve_job_profile_questions,
)
from tools.playwright_template import (
    PlaywrightToolSpec,
    PlaywrightToolTrace,
    click_first_visible,
    compact_text,
    first_attached_locator,
    first_visible_locator,
    navigate,
    run_playwright_flow,
    set_first_file_input,
    wait_for_load_state,
)


LINKEDIN_JOBS_URL = "https://www.linkedin.com/jobs/"
LINKEDIN_JOBS_MODULE = "linkedin_jobs"
JOB_CARD_SELECTORS = (
    "li[data-occludable-job-id]",
    ".jobs-search-results__list-item",
    ".job-card-container",
    "[data-job-id]",
)
EASY_APPLY_BUTTON_SELECTORS = (
    'button:has-text("Easy Apply")',
    'button[aria-label*="Easy Apply"]',
    ".jobs-apply-button",
)
JOB_SHARE_BUTTON_SELECTORS = (
    'button[aria-label*="Share"]',
    'button[aria-label*="share"]',
    'button:has-text("Share")',
)
JOB_MORE_ACTIONS_BUTTON_SELECTORS = (
    'button[aria-label*="More actions"]',
    'button[aria-label*="More options"]',
    'button[aria-label*="More"]',
    'button:has-text("More")',
)
JOB_COPY_LINK_BUTTON_SELECTORS = (
    'button[aria-label*="Copy link"]',
    'button[aria-label*="Copy Link"]',
    'button:has-text("Copy link")',
    'button:has-text("Copy Link")',
    '[role="button"]:has-text("Copy link")',
    '[role="button"]:has-text("Copy Link")',
)
EXTERNAL_APPLY_BUTTON_SELECTORS = (
    'button[aria-label*="Apply"]',
    'a[aria-label*="Apply"]',
    'button:has-text("Apply")',
    'a:has-text("Apply")',
)
EXTERNAL_APPLICATION_ADVANCE_SELECTORS = (
    'button:has-text("Apply now")',
    'a:has-text("Apply now")',
    'button:has-text("Apply for this job")',
    'a:has-text("Apply for this job")',
    'button:has-text("Start application")',
    'a:has-text("Start application")',
    'button:has-text("Start your application")',
    'a:has-text("Start your application")',
    'button:has-text("Continue")',
    'a:has-text("Continue")',
    'button:has-text("Next")',
    'a:has-text("Next")',
    'button:has-text("Review")',
    'a:has-text("Review")',
)
APPLICATION_FILE_INPUT_SELECTORS = (
    'input[type="file"]',
    'input[name*="resume"]',
    'input[id*="resume"]',
)
APPLICATION_COVER_LETTER_FILE_INPUT_SELECTORS = (
    'input[type="file"][name*="cover"]',
    'input[type="file"][name*="letter"]',
    'input[type="file"][id*="cover"]',
    'input[type="file"][id*="letter"]',
    'input[type="file"][aria-label*="Cover"]',
    'input[type="file"][aria-label*="cover"]',
    'input[type="file"][aria-label*="Letter"]',
    'input[type="file"][aria-label*="letter"]',
)
APPLICATION_SUBMIT_BUTTON_SELECTORS = (
    'button:has-text("Submit application")',
    'button[aria-label*="Submit application"]',
    'button:has-text("Submit")',
)
EXTERNAL_APPLICATION_SUBMIT_BUTTON_SELECTORS = (
    'button:has-text("Submit application")',
    'button:has-text("Submit Application")',
    'button:has-text("Submit")',
    'button:has-text("Send application")',
    'button:has-text("Apply")',
    'input[type="submit"]',
)
APPLICATION_REVIEW_BUTTON_SELECTORS = (
    'button:has-text("Review")',
    'button:has-text("Next")',
    'button[aria-label*="Review"]',
    'button[aria-label*="Next"]',
)
RESUME_UPLOAD_SUFFIX_PREFERENCE = (".pdf", ".docx", ".doc")
PLATFORM_DOMAIN_KEYWORDS = {
    "linkedin": ("linkedin.com",),
    "greenhouse": ("greenhouse.io", "boards.greenhouse.io", "grnh.se"),
    "lever": ("lever.co", "jobs.lever.co"),
    "workday": ("workdayjobs.com", "myworkdayjobs.com", "wd1.myworkdaysite.com"),
    "ashby": ("ashbyhq.com", "jobs.ashbyhq.com"),
    "smartrecruiters": ("smartrecruiters.com", "jobs.smartrecruiters.com"),
    "workable": ("workable.com", "apply.workable.com"),
    "bamboohr": ("bamboohr.com",),
    "icims": ("icims.com",),
    "jobvite": ("jobvite.com",),
    "successfactors": ("successfactors.com", "sapsf.com"),
    "oracle": ("oraclecloud.com",),
    "eightfold": ("eightfold.ai",),
}


class LinkedInJobsExplorerInput(BaseModel):
    """Input schema for exploring LinkedIn Jobs without applying."""

    query: str = Field(..., description="Job search query, for example AI Engineer.")
    location: str = Field(default="", description="Location filter, or empty for default.")
    candidate_profile: str = Field(
        default="",
        description="Candidate profile, preferences, and constraints for fit scoring.",
    )
    required_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords that should increase fit score when present.",
    )
    easy_apply_only: bool = Field(
        default=False,
        description="When true, keep only jobs that appear to support Easy Apply.",
    )
    limit: int = Field(default=10, ge=1, le=25, description="Maximum jobs to return.")
    session_state_path: str = Field(
        default=DEFAULT_LINKEDIN_SESSION_STATE_PATH,
        description="Playwright storage_state path for LinkedIn auth.",
    )
    headless: bool = Field(default=False, description="Run browser headless.")
    capture_screenshot: bool = Field(
        default=True,
        description="Save a local screenshot path into ignored memory artifacts.",
    )
    capture_dom_snapshot: bool = Field(
        default=True,
        description="Save a compact DOM snapshot into ignored memory artifacts.",
    )
    execution_mode: str | None = Field(
        default=None,
        description="Tool mode override: auto-mode or approve-mode.",
    )


class LinkedInJobApplyDraftInput(BaseModel):
    """Input schema for opening an Easy Apply draft safely."""

    job_url: str = Field(..., description="LinkedIn job detail URL.")
    resume_path: str | None = Field(
        default=None,
        description="Optional local resume/CV path to upload if a file input appears.",
    )
    cover_letter_path: str | None = Field(
        default=None,
        description="Optional local cover-letter path to upload if a cover-letter input appears.",
    )
    advance_application: bool = Field(
        default=True,
        description="Click safe Next/Review steps until Submit is visible or manual input is required.",
    )
    max_application_steps: int = Field(
        default=5,
        ge=0,
        le=10,
        description="Maximum safe Next/Review clicks before stopping for manual review.",
    )
    submit: bool = Field(
        default=False,
        description="When true, ask for terminal y/n before clicking Submit.",
    )
    session_state_path: str = Field(
        default=DEFAULT_LINKEDIN_SESSION_STATE_PATH,
        description="Playwright storage_state path for LinkedIn auth.",
    )
    headless: bool = Field(default=False, description="Run browser headless.")
    capture_screenshot: bool = Field(
        default=True,
        description="Save a local screenshot path into ignored memory artifacts.",
    )
    capture_dom_snapshot: bool = Field(
        default=True,
        description="Save a compact DOM snapshot into ignored memory artifacts.",
    )
    execution_mode: str | None = Field(
        default=None,
        description="Tool mode override: auto-mode or approve-mode.",
    )


class LinkedInJobTailoredApplyDraftInput(LinkedInJobApplyDraftInput):
    """Input schema for tailoring materials and opening an Easy Apply draft."""

    library: str = Field(
        default="user_content/library",
        description="CV Maker library path containing master CV material.",
    )
    template: str = Field(default="", description="Optional CV Maker DOCX template path.")
    output: str = Field(
        default="Tailored_CV.docx",
        description="CV Maker output filename. Default lets CV Maker derive a job-specific name.",
    )
    output_format: str = Field(
        default="docx",
        description="CV Maker output format: docx or latex.",
    )
    provider: str = Field(
        default="auto",
        description="CV Maker LLM provider, for example auto, minimax, openai, gemini.",
    )
    model: str = Field(default="", description="Optional model override for CV Maker.")
    github: str = Field(default="", description="Optional GitHub profile/context for CV Maker.")
    suggestions: str = Field(default="", description="Optional comma-separated CV style suggestions.")
    summarize_years: int = Field(
        default=10,
        ge=0,
        description="Years of experience to preserve before summarizing older work.",
    )
    no_compile: bool = Field(
        default=False,
        description="When using latex output, skip PDF compilation.",
    )
    timeout_seconds: int | None = Field(
        default=None,
        description="Optional CV Maker timeout override.",
    )
    upload_cover_letter: bool = Field(
        default=True,
        description="Upload the generated cover letter when LinkedIn exposes a matching file input.",
    )


def build_linkedin_jobs_search_url(query: str, location: str = "") -> str:
    """Build a LinkedIn Jobs search URL."""
    url = f"{LINKEDIN_JOBS_URL}search/?keywords={quote_plus(query.strip())}"
    if location.strip():
        url += f"&location={quote_plus(location.strip())}"
    return url


def build_missing_linkedin_jobs_auth_result(
    session_state_path: str,
    *,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Return an approval/manual result when LinkedIn auth state is missing."""
    decision = request_user_approval(
        ApprovalRequest(
            action="linkedin-auth-setup",
            reason=(
                "LinkedIn Jobs tools need a saved Playwright session before they can "
                "browse jobs as your account."
            ),
            automated_flow=(
                "Open a visible browser, let you log in manually, and save LinkedIn "
                f"session state to {session_state_path}."
            ),
            manual_steps=[
                "./.venv/bin/python -m playwright install chromium",
                LINKEDIN_AUTH_SETUP_COMMAND,
                "Log in to LinkedIn in the opened Playwright browser.",
                "After the feed is visible, return to the terminal and press Enter.",
            ],
        ),
        mode=execution_mode,
        interactive=False,
    )
    return {
        "status": decision.status,
        "success": False,
        "message": decision.message,
        "approval": decision.model_dump(mode="json"),
        "url": LINKEDIN_JOBS_URL,
    }


def explore_linkedin_jobs(
    *,
    query: str,
    location: str = "",
    candidate_profile: str = "",
    required_keywords: list[str] | None = None,
    easy_apply_only: bool = False,
    limit: int = 10,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    playwright_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Explore LinkedIn Jobs and save a trace, without applying."""
    search_url = build_linkedin_jobs_search_url(query, location)
    spec = PlaywrightToolSpec(
        tool_name="linkedin-jobs-explorer",
        task=f"Explore LinkedIn Jobs for {query}",
        start_url=search_url,
        module=LINKEDIN_JOBS_MODULE,
        tags=["linkedin", "jobs", "explorer"],
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
    )

    def flow(page: Any, trace: PlaywrightToolTrace) -> dict[str, Any]:
        navigate(page, trace, search_url, timeout=60_000)
        wait_for_load_state(page, trace, timeout=10_000)
        jobs = extract_linkedin_job_cards(page, limit=max(limit * 2, limit))
        if easy_apply_only:
            jobs = [job for job in jobs if job.get("easy_apply")]
        scored_jobs = [
            score_linkedin_job_fit(
                job,
                candidate_profile=candidate_profile,
                required_keywords=required_keywords or [],
            )
            for job in jobs[:limit]
        ]
        trace.action(
            "extract",
            "Extract LinkedIn job cards",
            url=getattr(page, "url", search_url),
            success=bool(scored_jobs),
            details={
                "query": query,
                "location": location,
                "count": len(scored_jobs),
                "easy_apply_only": easy_apply_only,
            },
        )
        trace.add_extracted_data("jobs", scored_jobs)
        trace.add_extracted_data(
            "search",
            {
                "query": query,
                "location": location,
                "easy_apply_only": easy_apply_only,
                "limit": limit,
            },
        )
        return {
            "status": "ok",
            "success": True,
            "message": f"Found {len(scored_jobs)} LinkedIn job candidate(s).",
            "url": getattr(page, "url", search_url),
            "jobs": scored_jobs,
            "extracted_data": {"jobs": scored_jobs},
        }

    factory = playwright_factory or sync_playwright
    return run_playwright_flow(spec, flow, playwright_factory=factory)


def open_linkedin_job_apply_draft(
    *,
    job_url: str,
    resume_path: str | None = None,
    cover_letter_path: str | None = None,
    advance_application: bool = True,
    max_application_steps: int = 5,
    submit: bool = False,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    confirm_submit: Callable[[str], str] = input,
    playwright_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Open an Easy Apply draft and stop before Submit unless y/n confirms."""
    spec = PlaywrightToolSpec(
        tool_name="linkedin-job-apply-draft",
        task=f"Open LinkedIn Easy Apply draft for {job_url}",
        start_url=job_url,
        module=LINKEDIN_JOBS_MODULE,
        tags=["linkedin", "jobs", "apply-draft"],
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
    )

    def flow(page: Any, trace: PlaywrightToolTrace) -> dict[str, Any]:
        navigate(page, trace, job_url, timeout=60_000)
        wait_for_load_state(page, trace, timeout=10_000)
        return continue_application_from_job_page(
            page,
            trace,
            job_url=job_url,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            advance_application=advance_application,
            max_application_steps=max_application_steps,
            submit=submit,
            confirm_submit=confirm_submit,
        )

    factory = playwright_factory or sync_playwright
    return run_playwright_flow(spec, flow, playwright_factory=factory)


def continue_application_from_job_page(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    job_url: str,
    resume_path: str | None = None,
    cover_letter_path: str | None = None,
    advance_application: bool = True,
    max_application_steps: int = 5,
    submit: bool = False,
    confirm_submit: Callable[[str], str] = input,
) -> dict[str, Any]:
    """Continue an application from a LinkedIn job page, including external ATS links."""
    easy_apply_result = fill_linkedin_easy_apply_draft(
        page,
        trace,
        job_url=job_url,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        advance_application=advance_application,
        max_application_steps=max_application_steps,
        submit=submit,
        confirm_submit=confirm_submit,
    )
    if easy_apply_result.get("status") != "not_easy_apply":
        return with_application_memory(
            easy_apply_result,
            platform="linkedin",
            phase="easy_apply",
            source_url=job_url,
            tool_name=trace.spec.tool_name,
        )

    external_result = open_external_application_from_linkedin(
        page,
        trace,
        job_url=job_url,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        advance_application=advance_application,
        max_application_steps=max_application_steps,
    )
    platform = str(external_result.get("application_platform") or "external")
    return with_application_memory(
        external_result,
        platform=platform,
        phase="external_apply",
        source_url=job_url,
        tool_name=trace.spec.tool_name,
    )


def fill_linkedin_easy_apply_draft(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    job_url: str,
    resume_path: str | None = None,
    cover_letter_path: str | None = None,
    advance_application: bool = True,
    max_application_steps: int = 5,
    submit: bool = False,
    confirm_submit: Callable[[str], str] = input,
) -> dict[str, Any]:
    """Click Easy Apply, upload available materials, and stop before final submit."""
    easy_apply_selector, clicked = click_first_visible(
        page,
        trace,
        EASY_APPLY_BUTTON_SELECTORS,
        label="Open Easy Apply modal",
        timeout=8_000,
    )
    if not clicked:
        return {
            "status": "not_easy_apply",
            "success": False,
            "message": "No visible Easy Apply button was found for this job.",
            "url": getattr(page, "url", job_url),
            "easy_apply_selector": easy_apply_selector,
        }

    missing_path = first_missing_application_material_path(
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
    )
    if missing_path:
        return {
            "status": "error",
            "success": False,
            "message": f"Application material file not found: {missing_path}",
            "url": getattr(page, "url", job_url),
            "easy_apply_selector": easy_apply_selector,
        }

    upload_state = {
        "resume_uploaded": False,
        "resume_upload_selector": None,
        "cover_letter_uploaded": False,
        "cover_letter_upload_selector": None,
    }
    attempt_application_material_uploads(
        page,
        trace,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        upload_state=upload_state,
    )

    review_selector, review_ready, application_steps = advance_application_to_review(
        page,
        trace,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        upload_state=upload_state,
        advance_application=advance_application,
        max_application_steps=max_application_steps,
    )
    trace.action(
        "inspect",
        "Inspect application review/submit controls",
        url=getattr(page, "url", job_url),
        selector=review_selector,
        success=review_ready,
        details={"submit_requested": submit},
    )

    submitted = False
    submit_confirmed = False
    if submit:
        answer = confirm_submit(
            "LinkedIn application draft is open. Type y to click Submit, "
            "or anything else to leave it for review: "
        ).strip().lower()
        submit_confirmed = answer in {"y", "yes"}
        if submit_confirmed:
            submit_selector, submitted = click_first_visible(
                page,
                trace,
                APPLICATION_SUBMIT_BUTTON_SELECTORS,
                label="Submit LinkedIn application after terminal confirmation",
                timeout=5_000,
            )
            review_selector = submit_selector or review_selector

    status: Literal["manual_required", "review_ready", "submitted"] = (
        "submitted"
        if submitted
        else "review_ready"
        if review_ready
        else "manual_required"
    )
    return {
        "status": status,
        "success": True,
        "message": (
            "LinkedIn application submitted after y/n confirmation."
            if submitted
            else "LinkedIn Easy Apply draft is ready for final review."
            if review_ready
            else "LinkedIn Easy Apply draft is open, but manual form input may be required."
        ),
        "url": getattr(page, "url", job_url),
        "easy_apply_selector": easy_apply_selector,
        **upload_state,
        "review_selector": review_selector,
        "review_ready": review_ready,
        "application_steps": application_steps,
        "submit_requested": submit,
        "submit_confirmed": submit_confirmed,
        "submitted": submitted,
        "extracted_data": {
            "job_url": job_url,
            **upload_state,
            "submitted": submitted,
        },
    }


def open_external_application_from_linkedin(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    job_url: str,
    resume_path: str | None,
    cover_letter_path: str | None,
    advance_application: bool = True,
    max_application_steps: int = 5,
) -> dict[str, Any]:
    """Open a non-Easy-Apply application and record the target platform."""
    missing_path = first_missing_application_material_path(
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
    )
    if missing_path:
        return {
            "status": "error",
            "success": False,
            "message": f"Application material file not found: {missing_path}",
            "url": getattr(page, "url", job_url),
            "application_platform": detect_application_platform(getattr(page, "url", job_url)),
        }

    external_apply_selector, clicked, application_page = click_external_apply_button(
        page,
        trace,
        timeout=8_000,
    )
    if clicked:
        wait_for_load_state(application_page, trace, timeout=15_000)
        try:
            application_page.wait_for_timeout(1_000)
        except Exception:
            pass

    current_url = getattr(application_page, "url", job_url)
    platform = detect_application_platform(current_url)
    upload_state = {
        "resume_uploaded": False,
        "resume_upload_selector": None,
        "cover_letter_uploaded": False,
        "cover_letter_upload_selector": None,
    }
    external_progress: dict[str, Any] = {
        "status": "manual_required",
        "message": "External application page was not opened.",
        "application_steps": 0,
        "application_blockers": [],
        "form_state": {},
        "review_ready": False,
    }
    if clicked:
        external_progress = advance_external_application_draft(
            application_page,
            trace,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            upload_state=upload_state,
            advance_application=advance_application,
            max_steps=max_application_steps,
        )
        current_url = getattr(application_page, "url", current_url)
        platform = detect_application_platform(current_url)

    status = (
        str(external_progress.get("status") or "external_application_opened")
        if clicked
        else "manual_required"
    )
    return {
        "status": status,
        "success": clicked,
        "message": (
            str(external_progress.get("message") or f"External application opened on {platform}.")
            if clicked
            else "No Easy Apply or external Apply button was found; manual application is required."
        ),
        "url": current_url,
        "memory_url": current_url,
        "job_url": job_url,
        "application_platform": platform,
        "external_apply_selector": external_apply_selector,
        **upload_state,
        "review_ready": bool(external_progress.get("review_ready")),
        "application_steps": int(external_progress.get("application_steps") or 0),
        "application_blockers": list(external_progress.get("application_blockers") or []),
        "profile_resolution": external_progress.get("profile_resolution") or {},
        "fill_result": external_progress.get("fill_result") or {},
        "form_state": external_progress.get("form_state") or {},
        "submitted": False,
        "extracted_data": {
            "job_url": job_url,
            "application_platform": platform,
            "external_application_url": current_url,
            **upload_state,
            "review_ready": bool(external_progress.get("review_ready")),
            "application_steps": int(external_progress.get("application_steps") or 0),
            "application_blockers": list(external_progress.get("application_blockers") or []),
            "profile_resolution": external_progress.get("profile_resolution") or {},
            "fill_result": external_progress.get("fill_result") or {},
            "form_state": external_progress.get("form_state") or {},
        },
    }


def advance_external_application_draft(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    resume_path: str | None,
    cover_letter_path: str | None,
    upload_state: dict[str, Any],
    advance_application: bool = True,
    max_steps: int = 6,
) -> dict[str, Any]:
    """Advance a generic external ATS draft until review, blockers, or no next step."""
    steps_taken = 0
    clicked_selectors: list[str] = []
    attempted_answer_keys: set[str] = set()
    profile_resolution: dict[str, Any] = {}
    fill_result: dict[str, Any] = {}
    form_state = inspect_external_application_form_state(page)
    application_blockers = list(form_state.get("required_unfilled_fields") or [])

    while steps_taken <= max_steps:
        attempt_application_material_uploads(
            page,
            trace,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            upload_state=upload_state,
        )
        form_state = inspect_external_application_form_state(page)
        application_blockers = list(form_state.get("required_unfilled_fields") or [])

        if form_state.get("submit_ready"):
            trace.action(
                "inspect",
                "External application submit/review control is visible",
                url=getattr(page, "url", None),
                success=True,
                details={"form_state": form_state},
            )
            return {
                "status": "external_review_ready",
                "message": (
                    "External application is at a review/submit step. "
                    "Stopped before Submit."
                ),
                "application_steps": steps_taken,
                "application_blockers": application_blockers,
                "profile_resolution": profile_resolution,
                "fill_result": fill_result,
                "form_state": form_state,
                "review_ready": True,
                "clicked_selectors": clicked_selectors,
            }

        if application_blockers:
            blocker_keys = {
                str(blocker.get("question_key") or question_key(blocker))
                for blocker in application_blockers
            }
            if blocker_keys and not blocker_keys.issubset(attempted_answer_keys):
                profile_resolution = resolve_job_profile_questions(application_blockers)
                unresolved_questions = list(
                    profile_resolution.get("unresolved_questions") or []
                )
                answers = list(profile_resolution.get("answers") or [])
                if answers and not unresolved_questions:
                    fill_result = fill_external_application_answers(
                        page,
                        trace,
                        answers,
                    )
                    attempted_answer_keys.update(
                        str(answer.get("question_key") or "")
                        for answer in answers
                        if answer.get("question_key")
                    )
                    if fill_result.get("filled_count"):
                        try:
                            page.wait_for_timeout(500)
                        except Exception:
                            pass
                        continue

            trace.action(
                "inspect",
                "External application needs user input",
                url=getattr(page, "url", None),
                success=False,
                details={
                    "application_blockers": application_blockers,
                    "profile_resolution": profile_resolution,
                    "fill_result": fill_result,
                },
            )
            return {
                "status": "external_application_needs_input",
                "message": (
                    "External application opened but needs manual answers before it "
                    "can safely continue."
                ),
                "application_steps": steps_taken,
                "application_blockers": application_blockers,
                "profile_resolution": profile_resolution,
                "fill_result": fill_result,
                "form_state": form_state,
                "review_ready": False,
                "clicked_selectors": clicked_selectors,
            }

        if not advance_application or steps_taken >= max_steps:
            break

        advance_selector, advanced = click_first_visible(
            page,
            trace,
            EXTERNAL_APPLICATION_ADVANCE_SELECTORS,
            label="Advance external application draft",
            timeout=3_000,
        )
        if not advanced:
            break

        clicked_selectors.append(str(advance_selector))
        steps_taken += 1
        wait_for_load_state(page, trace, timeout=10_000)
        try:
            page.wait_for_timeout(1_000)
        except Exception:
            pass

    attempt_application_material_uploads(
        page,
        trace,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        upload_state=upload_state,
    )
    form_state = inspect_external_application_form_state(page)
    application_blockers = list(form_state.get("required_unfilled_fields") or [])
    status = (
        "external_application_needs_input"
        if application_blockers
        else "external_application_draft_open"
    )
    message = (
        "External application opened but needs manual answers before it can safely continue."
        if application_blockers
        else "External application draft is open; no further safe automated step was found."
    )
    return {
        "status": status,
        "message": message,
        "application_steps": steps_taken,
        "application_blockers": application_blockers,
        "profile_resolution": profile_resolution,
        "fill_result": fill_result,
        "form_state": form_state,
        "review_ready": False,
        "clicked_selectors": clicked_selectors,
    }


def fill_external_application_answers(
    page: Any,
    trace: PlaywrightToolTrace,
    answers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fill generic external ATS fields with resolved profile answers."""
    safe_answers = [
        {
            "question_key": str(answer.get("question_key") or ""),
            "label": str(answer.get("label") or ""),
            "name": str(answer.get("name") or ""),
            "type": str(answer.get("type") or ""),
            "answer": answer.get("answer"),
        }
        for answer in answers
        if answer.get("answer") is not None
    ]
    if not safe_answers:
        return {"filled_count": 0, "filled": [], "unfilled": []}

    try:
        result = page.evaluate(
            """
            ({ answers }) => {
              window.__offergraphFillExternalApplicationAnswers = true;
              const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
              const norm = (value) => clean(value).toLowerCase();
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.visibility !== "hidden" &&
                  style.display !== "none" &&
                  rect.width > 0 &&
                  rect.height > 0;
              };
              const fire = (el) => {
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
              };
              const labelFor = (el) => {
                const explicit = el.id ? clean(document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText) : "";
                const wrapped = clean(el.closest("label")?.innerText);
                const direct = clean(el.getAttribute("aria-label")) ||
                  clean(el.getAttribute("placeholder")) ||
                  clean(el.getAttribute("name")) ||
                  clean(el.id);
                const group = clean(el.closest("[role='group'], fieldset, .field, .form-group, .question, li, div")?.innerText);
                return explicit || wrapped || direct || group || clean(el.tagName);
              };
              const elements = Array.from(document.querySelectorAll("input, textarea, select"))
                .filter((el) => {
                  const type = norm(el.getAttribute("type") || el.tagName);
                  return visible(el) && !["hidden", "button", "submit", "reset", "file", "image"].includes(type);
                });
              const scoreElement = (el, item) => {
                const haystack = norm([
                  labelFor(el),
                  el.getAttribute("name"),
                  el.id,
                  el.getAttribute("aria-label"),
                  el.getAttribute("placeholder")
                ].join(" "));
                const label = norm(item.label);
                const name = norm(item.name);
                let score = 0;
                if (name && haystack.includes(name)) score += 8;
                if (label && haystack.includes(label)) score += 10;
                if (label && label.includes(haystack) && haystack.length > 4) score += 5;
                for (const token of label.split(/\\s+/).filter((part) => part.length > 3)) {
                  if (haystack.includes(token)) score += 1;
                }
                return score;
              };
              const chooseSelectOption = (select, answer) => {
                const answerText = norm(answer);
                const boolYes = ["yes", "true"].includes(answerText);
                const boolNo = ["no", "false"].includes(answerText);
                const options = Array.from(select.options || []);
                let option = options.find((candidate) => norm(candidate.value) === answerText || norm(candidate.text) === answerText);
                if (!option) {
                  option = options.find((candidate) => norm(candidate.text).includes(answerText) || norm(candidate.value).includes(answerText));
                }
                if (!option && (boolYes || boolNo)) {
                  option = options.find((candidate) => {
                    const value = norm(`${candidate.text} ${candidate.value}`);
                    return boolYes ? /\\byes\\b|\\btrue\\b/.test(value) : /\\bno\\b|\\bfalse\\b/.test(value);
                  });
                }
                if (!option && answerText === "prefer_not_to_answer") {
                  option = options.find((candidate) => /prefer|decline|not answer/i.test(`${candidate.text} ${candidate.value}`));
                }
                if (!option) return false;
                select.value = option.value;
                fire(select);
                return true;
              };
              const chooseCheckable = (el, item) => {
                const answerText = norm(item.answer);
                const name = el.getAttribute("name");
                const group = name ? elements.filter((candidate) => candidate.getAttribute("name") === name) : [el];
                let target = group.find((candidate) => {
                  const text = norm(`${labelFor(candidate)} ${candidate.value || ""}`);
                  return text.includes(answerText);
                });
                if (!target && ["yes", "true", "no", "false"].includes(answerText)) {
                  target = group.find((candidate) => {
                    const text = norm(`${labelFor(candidate)} ${candidate.value || ""}`);
                    return ["yes", "true"].includes(answerText)
                      ? /\\byes\\b|\\btrue\\b/.test(text)
                      : /\\bno\\b|\\bfalse\\b/.test(text);
                  });
                }
                if (!target && el.type === "checkbox") target = el;
                if (!target) return false;
                target.checked = true;
                fire(target);
                return true;
              };
              const filled = [];
              const unfilled = [];
              for (const item of answers) {
                const candidates = elements
                  .map((el) => ({ el, score: scoreElement(el, item) }))
                  .filter((candidate) => candidate.score > 0)
                  .sort((a, b) => b.score - a.score);
                const candidate = candidates[0]?.el;
                if (!candidate) {
                  unfilled.push({ question_key: item.question_key, reason: "no matching field" });
                  continue;
                }
                const tag = candidate.tagName.toLowerCase();
                const type = norm(candidate.getAttribute("type") || tag);
                const answer = clean(item.answer);
                let ok = false;
                if (tag === "select") {
                  ok = chooseSelectOption(candidate, answer);
                } else if (["radio", "checkbox"].includes(type)) {
                  ok = chooseCheckable(candidate, item);
                } else {
                  candidate.value = answer;
                  fire(candidate);
                  ok = true;
                }
                if (ok) {
                  filled.push({
                    question_key: item.question_key,
                    label: item.label,
                    name: item.name,
                    tag,
                    type
                  });
                } else {
                  unfilled.push({ question_key: item.question_key, reason: "could not set value" });
                }
              }
              return { filled_count: filled.length, filled, unfilled };
            }
            """,
            {"answers": safe_answers},
        )
    except Exception as exc:
        result = {
            "filled_count": 0,
            "filled": [],
            "unfilled": [
                {"question_key": answer.get("question_key"), "reason": str(exc)}
                for answer in safe_answers
            ],
        }

    if not isinstance(result, dict):
        result = {"filled_count": 0, "filled": [], "unfilled": safe_answers}

    trace.action(
        "fill",
        "Fill external application answers from local job profile",
        url=getattr(page, "url", None),
        success=bool(result.get("filled_count")),
        details=result,
    )
    return result


def inspect_external_application_form_state(page: Any) -> dict[str, Any]:
    """Return visible external ATS form state without exposing entered values."""
    try:
        state = page.evaluate(
            """
            () => {
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.visibility !== "hidden" &&
                  style.display !== "none" &&
                  rect.width > 0 &&
                  rect.height > 0;
              };
              const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
              const labelFor = (el) => {
                const direct = clean(el.getAttribute("aria-label")) ||
                  clean(el.getAttribute("placeholder")) ||
                  clean(el.getAttribute("name")) ||
                  clean(el.id);
                const explicit = el.id ? clean(document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText) : "";
                const wrapped = clean(el.closest("label")?.innerText);
                const group = clean(el.closest("[role='group'], .field, .form-group, .question, li, div")?.innerText);
                return explicit || wrapped || direct || group || clean(el.tagName);
              };
              const fields = [];
              const requiredUnfilled = [];
              const nodes = Array.from(document.querySelectorAll("input, textarea, select"));
              for (const el of nodes) {
                const tag = el.tagName.toLowerCase();
                const type = clean(el.getAttribute("type") || tag).toLowerCase();
                if (["hidden", "button", "submit", "reset", "file", "image"].includes(type)) continue;
                if (!visible(el)) continue;
                const label = labelFor(el).slice(0, 160);
                const required = Boolean(el.required || el.getAttribute("aria-required") === "true");
                const value = clean(el.value);
                const options = tag === "select"
                  ? Array.from(el.options || []).map((option) => clean(option.text || option.value)).filter(Boolean).slice(0, 20)
                  : ["radio", "checkbox"].includes(type) && el.getAttribute("name")
                    ? Array.from(document.querySelectorAll(`input[name="${CSS.escape(el.getAttribute("name"))}"]`))
                        .map((candidate) => clean(labelFor(candidate) || candidate.value))
                        .filter(Boolean)
                        .slice(0, 20)
                    : [];
                const item = {
                  label,
                  tag,
                  type,
                  required,
                  has_value: Boolean(value),
                  name: clean(el.getAttribute("name") || el.id).slice(0, 120),
                  options
                };
                fields.push(item);
                if (required && !value) requiredUnfilled.push(item);
              }
              const fileInputs = Array.from(document.querySelectorAll("input[type='file']")).filter(visible).length;
              const submitReady = Array.from(document.querySelectorAll("button, a, input[type='submit']")).some((el) => {
                if (!visible(el)) return false;
                const text = clean(el.innerText || el.value || el.getAttribute("aria-label"));
                return /^(submit|submit application|send application|review application)$/i.test(text);
              });
              return {
                fields,
                required_unfilled_fields: requiredUnfilled,
                visible_file_inputs: fileInputs,
                submit_ready: submitReady
              };
            }
            """
        )
    except Exception as exc:
        return {
            "fields": [],
            "required_unfilled_fields": [],
            "visible_file_inputs": 0,
            "submit_ready": False,
            "inspection_error": str(exc),
        }
    return state if isinstance(state, dict) else {}


def click_external_apply_button(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    timeout: int = 8_000,
) -> tuple[str | None, bool, Any]:
    """Click the first external Apply control, capturing popup tabs when possible."""
    selector, locator = first_visible_locator(
        page,
        EXTERNAL_APPLY_BUTTON_SELECTORS,
        timeout=timeout,
    )
    if not selector or locator is None:
        trace.action(
            "click",
            "Open external job application",
            url=getattr(page, "url", None),
            selector=None,
            success=False,
            details={
                "reason": "no visible selector matched",
                "selectors": EXTERNAL_APPLY_BUTTON_SELECTORS,
            },
        )
        return None, False, page

    clicked = False
    popup_page = None
    popup_error = ""
    try:
        with page.expect_popup(timeout=2_000) as popup_info:
            locator.click()
            clicked = True
        popup_page = popup_info.value
    except Exception as exc:
        popup_error = str(exc)
        if not clicked:
            try:
                locator.click()
                clicked = True
            except Exception as click_exc:
                trace.action(
                    "click",
                    "Open external job application",
                    url=getattr(page, "url", None),
                    selector=selector,
                    success=False,
                    details={"error": str(click_exc)},
                )
                return selector, False, page

    active_page = popup_page or page
    trace.action(
        "click",
        "Open external job application",
        url=getattr(active_page, "url", getattr(page, "url", None)),
        selector=selector,
        success=clicked,
        details={"popup_opened": popup_page is not None, "popup_error": popup_error},
    )
    return selector, clicked, active_page


def open_linkedin_job_tailored_apply_draft(
    *,
    job_url: str,
    submit: bool = False,
    library: str = "user_content/library",
    template: str = "",
    output: str = "Tailored_CV.docx",
    output_format: str = "docx",
    provider: str = "auto",
    model: str = "",
    github: str = "",
    suggestions: str = "",
    summarize_years: int = 10,
    no_compile: bool = False,
    timeout_seconds: int | None = None,
    upload_cover_letter: bool = True,
    advance_application: bool = True,
    max_application_steps: int = 5,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    confirm_submit: Callable[[str], str] = input,
    playwright_factory: Callable[[], Any] | None = None,
    cv_tailoring_func: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Copy the LinkedIn JD link, generate materials, then reopen Playwright to apply."""
    copy_result = copy_linkedin_job_share_link(
        job_url=job_url,
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
        playwright_factory=playwright_factory,
    )
    copied_job_url = str(copy_result.get("copied_job_url") or job_url)
    if copy_result.get("status") == "error":
        return {
            "status": "copy_link_error",
            "success": False,
            "message": copy_result.get("message", "Could not copy LinkedIn JD link."),
            "url": job_url,
            "copy_link": copy_result,
        }

    tailoring_result = tailor_linkedin_job_application_materials(
        job_url=copied_job_url,
        library=library,
        template=template,
        output=output,
        output_format=output_format,
        provider=provider,
        model=model,
        github=github,
        suggestions=suggestions,
        summarize_years=summarize_years,
        no_compile=no_compile,
        timeout_seconds=timeout_seconds,
        cv_tailoring_func=cv_tailoring_func,
    )
    if tailoring_result.get("status") != "ready":
        return {
            "status": "cv_tailoring_error",
            "success": False,
            "message": tailoring_result.get("message", "CV tailoring failed."),
            "url": copied_job_url,
            "copy_link": copy_result,
            "cv_tailoring": tailoring_result,
        }

    materials = select_application_material_paths(
        tailoring_result.get("generated_files", [])
    )
    resume_path = materials.get("resume_path")
    cover_letter_path = materials.get("cover_letter_path") if upload_cover_letter else None
    if not resume_path:
        return {
            "status": "cv_tailoring_error",
            "success": False,
            "message": "CV tailoring finished but no uploadable resume/CV file was produced.",
            "url": copied_job_url,
            "copy_link": copy_result,
            "cv_tailoring": tailoring_result,
            "application_materials": materials,
        }

    apply_result = continue_linkedin_job_application_with_materials(
        job_url=copied_job_url,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        advance_application=advance_application,
        max_application_steps=max_application_steps,
        submit=submit,
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
        confirm_submit=confirm_submit,
        playwright_factory=playwright_factory,
    )
    apply_result["copy_link"] = copy_result
    apply_result["cv_tailoring"] = tailoring_result
    apply_result["application_materials"] = materials
    apply_result["copied_job_url"] = copied_job_url
    apply_result["copy_link_memory_record_id"] = copy_result.get("memory_record_id")
    apply_result["apply_memory_record_id"] = apply_result.get("memory_record_id")
    apply_result.setdefault("extracted_data", {})
    apply_result["extracted_data"]["copy_link"] = copy_result
    apply_result["extracted_data"]["cv_tailoring"] = tailoring_result
    apply_result["extracted_data"]["application_materials"] = materials
    return apply_result


def copy_linkedin_job_share_link(
    *,
    job_url: str,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    playwright_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Open LinkedIn and get the JD URL via Share -> Copy link."""
    spec = PlaywrightToolSpec(
        tool_name="linkedin-job-copy-link",
        task=f"Copy LinkedIn JD link for {job_url}",
        start_url=job_url,
        module=LINKEDIN_JOBS_MODULE,
        tags=["linkedin", "jobs", "copy-link"],
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
    )

    def flow(page: Any, trace: PlaywrightToolTrace) -> dict[str, Any]:
        navigate(page, trace, job_url, timeout=60_000)
        wait_for_load_state(page, trace, timeout=10_000)
        copy_data = copy_linkedin_job_link_from_share(page, trace, fallback_url=job_url)
        copied_job_url = str(copy_data.get("copied_job_url") or job_url)
        trace.add_extracted_data("copied_job_url", copied_job_url)
        trace.add_extracted_data("copy_link", copy_data)
        result = {
            "status": "ok",
            "success": True,
            "message": (
                "Copied LinkedIn JD link from Share -> Copy link."
                if copy_data.get("copied_from_clipboard")
                else "Used LinkedIn JD URL fallback because Share -> Copy link could not be read."
            ),
            "url": getattr(page, "url", job_url),
            "copied_job_url": copied_job_url,
            "copy_link": copy_data,
            "extracted_data": {
                "copied_job_url": copied_job_url,
                "copy_link": copy_data,
            },
        }
        return with_application_memory(
            result,
            platform="linkedin",
            phase="copy_link",
            source_url=job_url,
            tool_name=trace.spec.tool_name,
        )

    factory = playwright_factory or sync_playwright
    return run_playwright_flow(spec, flow, playwright_factory=factory)


def continue_linkedin_job_application_with_materials(
    *,
    job_url: str,
    resume_path: str,
    cover_letter_path: str | None = None,
    advance_application: bool = True,
    max_application_steps: int = 5,
    submit: bool = False,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    confirm_submit: Callable[[str], str] = input,
    playwright_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Reopen Playwright after CV generation and continue the application."""
    initial_platform = detect_application_platform(job_url)
    spec = PlaywrightToolSpec(
        tool_name="linkedin-job-application-platform-draft",
        task=f"Continue job application for {job_url}",
        start_url=job_url,
        module=application_memory_module(initial_platform),
        tags=[
            "linkedin-job-application-platform-draft",
            "jobs",
            "application",
            f"platform-{initial_platform}",
            "apply",
        ],
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
    )

    def flow(page: Any, trace: PlaywrightToolTrace) -> dict[str, Any]:
        navigate(page, trace, job_url, timeout=60_000)
        wait_for_load_state(page, trace, timeout=10_000)
        return continue_application_from_job_page(
            page,
            trace,
            job_url=job_url,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            advance_application=advance_application,
            max_application_steps=max_application_steps,
            submit=submit,
            confirm_submit=confirm_submit,
        )

    factory = playwright_factory or sync_playwright
    return run_playwright_flow(spec, flow, playwright_factory=factory)


def copy_linkedin_job_link_from_share(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    fallback_url: str,
) -> dict[str, Any]:
    """Click Share -> Copy link and read the copied JD URL from the browser clipboard."""
    grant_clipboard_permissions(page)
    share_selector, share_clicked = click_first_visible(
        page,
        trace,
        JOB_SHARE_BUTTON_SELECTORS,
        label="Open LinkedIn job share menu",
        timeout=8_000,
    )
    more_selector = None
    more_clicked = False
    if not share_clicked:
        more_selector, more_clicked = click_first_visible(
            page,
            trace,
            JOB_MORE_ACTIONS_BUTTON_SELECTORS,
            label="Open LinkedIn job more-actions menu",
            timeout=4_000,
        )
        if more_clicked:
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass
            share_selector, share_clicked = click_first_visible(
                page,
                trace,
                JOB_SHARE_BUTTON_SELECTORS,
                label="Open LinkedIn job share menu from more actions",
                timeout=4_000,
            )
    if share_clicked:
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass

    copy_selector = None
    copy_clicked = False
    if share_clicked:
        copy_selector, copy_clicked = click_first_visible(
            page,
            trace,
            JOB_COPY_LINK_BUTTON_SELECTORS,
            label="Copy LinkedIn job link from share menu",
            timeout=8_000,
        )
        if copy_clicked:
            try:
                page.wait_for_timeout(500)
            except Exception:
                pass

    clipboard_text = read_browser_clipboard(page) if copy_clicked else ""
    copied_job_url = extract_first_url(clipboard_text) or normalize_job_url(
        getattr(page, "url", fallback_url) or fallback_url
    )
    copied_from_clipboard = bool(extract_first_url(clipboard_text))
    trace.action(
        "clipboard",
        "Read LinkedIn job link from clipboard",
        url=getattr(page, "url", fallback_url),
        selector=copy_selector,
        success=copied_from_clipboard,
        details={
            "share_clicked": share_clicked,
            "more_selector": more_selector,
            "more_clicked": more_clicked,
            "copy_clicked": copy_clicked,
            "copied_job_url": copied_job_url,
            "fallback_used": not copied_from_clipboard,
        },
    )
    return {
        "copied_job_url": copied_job_url,
        "copied_from_clipboard": copied_from_clipboard,
        "share_selector": share_selector,
        "share_clicked": share_clicked,
        "more_selector": more_selector,
        "more_clicked": more_clicked,
        "copy_selector": copy_selector,
        "copy_clicked": copy_clicked,
    }


def grant_clipboard_permissions(page: Any) -> None:
    """Best-effort clipboard permissions for Playwright browser contexts."""
    try:
        context = page.context
        context.grant_permissions(
            ["clipboard-read", "clipboard-write"],
            origin="https://www.linkedin.com",
        )
    except Exception:
        pass


def read_browser_clipboard(page: Any) -> str:
    """Read clipboard text from inside the browser context."""
    try:
        value = page.evaluate("async () => await navigator.clipboard.readText()")
    except Exception:
        return ""
    return str(value or "")


def extract_first_url(value: str) -> str:
    """Extract the first URL-like token from copied clipboard text."""
    match = re.search(r"https?://[^\s\"'<>]+", value or "")
    if not match:
        return ""
    return normalize_job_url(match.group(0))


def normalize_job_url(value: str) -> str:
    """Trim common punctuation around a copied job URL."""
    return (value or "").strip().rstrip(").,;]")


def extract_linkedin_job_cards(page: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    """Extract normalized job cards from the current LinkedIn Jobs page."""
    jobs = page.evaluate(
        """
        ({ selectors, limit }) => {
          const seen = new Set();
          const cards = [];
          const text = (node) => (node?.innerText || node?.textContent || "").trim();
          const clean = (value) => value.replace(/\\s+/g, " ").trim();
          const titleSelectors = [
            ".job-card-list__title",
            ".job-card-container__link",
            "a[href*='/jobs/view/']",
            "[aria-label*='View job']"
          ];
          const companySelectors = [
            ".artdeco-entity-lockup__subtitle",
            ".job-card-container__primary-description",
            "[class*='company-name']"
          ];
          const locationSelectors = [
            ".job-card-container__metadata-item",
            ".job-card-container__metadata-wrapper",
            "[class*='job-card-container__metadata']"
          ];
          const firstText = (root, candidates) => {
            for (const selector of candidates) {
              const match = root.querySelector(selector);
              const value = clean(text(match));
              if (value) return value;
            }
            return "";
          };
          const firstHref = (root) => {
            const anchor = root.querySelector("a[href*='/jobs/view/']");
            if (!anchor) return "";
            return new URL(anchor.getAttribute("href"), window.location.origin).toString();
          };
          const nodes = [];
          for (const selector of selectors) {
            nodes.push(...document.querySelectorAll(selector));
          }
          for (const node of nodes) {
            if (cards.length >= limit) break;
            const link = firstHref(node);
            const title = firstText(node, titleSelectors);
            const key = link || title;
            if (!key || seen.has(key)) continue;
            seen.add(key);
            const raw = clean(text(node));
            cards.push({
              title,
              company: firstText(node, companySelectors),
              location: firstText(node, locationSelectors),
              url: link,
              easy_apply: /easy apply/i.test(raw),
              snippet: raw.slice(0, 900)
            });
          }
          return cards;
        }
        """,
        {"selectors": JOB_CARD_SELECTORS, "limit": limit},
    )
    return [normalize_linkedin_job(item) for item in jobs if item]


def normalize_linkedin_job(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one LinkedIn job extraction result."""
    return {
        "title": compact_text(str(item.get("title") or ""), max_chars=160),
        "company": compact_text(str(item.get("company") or ""), max_chars=120),
        "location": compact_text(str(item.get("location") or ""), max_chars=120),
        "url": str(item.get("url") or ""),
        "easy_apply": bool(item.get("easy_apply")),
        "snippet": compact_text(str(item.get("snippet") or ""), max_chars=900),
    }


def score_linkedin_job_fit(
    job: dict[str, Any],
    *,
    candidate_profile: str = "",
    required_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Add a simple deterministic fit score to one job record."""
    keywords = extract_fit_keywords(candidate_profile, required_keywords or [])
    haystack = " ".join(
        str(job.get(field) or "")
        for field in ("title", "company", "location", "snippet")
    ).lower()
    matched = [keyword for keyword in keywords if keyword.lower() in haystack]
    score = int(round((len(matched) / max(len(keywords), 1)) * 100)) if keywords else 0
    return {
        **job,
        "fit_score": score,
        "matched_keywords": matched[:20],
    }


def tailor_linkedin_job_application_materials(
    *,
    job_url: str,
    job_description: str = "",
    library: str = "user_content/library",
    template: str = "",
    output: str = "Tailored_CV.docx",
    output_format: str = "docx",
    provider: str = "auto",
    model: str = "",
    github: str = "",
    suggestions: str = "",
    summarize_years: int = 10,
    no_compile: bool = False,
    timeout_seconds: int | None = None,
    cv_tailoring_func: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run CV tailoring using authenticated JD text, falling back to the URL."""
    active_tailoring_func = cv_tailoring_func
    if active_tailoring_func is None:
        from mcp_servers.cv_tailoring.server import cv_tailor_resume

        active_tailoring_func = cv_tailor_resume

    result = active_tailoring_func(
        job_description=job_description,
        job_url="" if job_description.strip() else job_url,
        library=library,
        template=template,
        output=output,
        output_format=output_format,
        provider=provider,
        model=model,
        github=github,
        suggestions=suggestions,
        summarize_years=summarize_years,
        no_compile=no_compile,
        timeout_seconds=timeout_seconds,
    )
    return dict(result or {})


def extract_linkedin_job_description(page: Any) -> dict[str, str]:
    """Extract job title, company, and description text from an authenticated page."""
    try:
        data = page.evaluate(
            """
            () => {
              const clean = (value) => (value || "").replace(/\\s+/g, " ").trim();
              const firstText = (selectors) => {
                for (const selector of selectors) {
                  const node = document.querySelector(selector);
                  const value = clean(node?.innerText || node?.textContent || "");
                  if (value) return value;
                }
                return "";
              };
              const descriptionSelectors = [
                ".jobs-description__content",
                ".jobs-box__html-content",
                ".jobs-description-content__text",
                ".jobs-description",
                "[class*='jobs-description']"
              ];
              const title = firstText([
                ".job-details-jobs-unified-top-card__job-title",
                ".jobs-unified-top-card__job-title",
                "h1"
              ]);
              const company = firstText([
                ".job-details-jobs-unified-top-card__company-name",
                ".jobs-unified-top-card__company-name",
                "a[href*='/company/']"
              ]);
              const description = firstText(descriptionSelectors);
              return {
                title,
                company,
                description,
                url: window.location.href
              };
            }
            """
        )
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    return {
        "title": compact_text(str(data.get("title") or ""), max_chars=200),
        "company": compact_text(str(data.get("company") or ""), max_chars=160),
        "description": compact_text(str(data.get("description") or ""), max_chars=12_000),
        "url": str(data.get("url") or getattr(page, "url", "")),
    }


def build_job_description_for_cv_tailoring(
    jd_data: dict[str, str],
    fallback_url: str,
) -> str:
    """Build CV Maker JD text from authenticated LinkedIn page content."""
    title = jd_data.get("title", "").strip()
    company = jd_data.get("company", "").strip()
    description = jd_data.get("description", "").strip()
    if not title and not description:
        return ""

    parts = [
        f"Source URL: {jd_data.get('url') or fallback_url}",
        f"Role: {title}" if title else "",
        f"Company: {company}" if company else "",
        description,
    ]
    return "\n\n".join(part for part in parts if part and part.strip())


def select_application_material_paths(generated_files: list[str]) -> dict[str, Any]:
    """Classify CV Maker outputs into resume and cover-letter upload paths."""
    paths = [resolve_material_path(path) for path in generated_files if path]
    uploadable_paths = [
        path
        for path in paths
        if path.suffix.lower() in (*RESUME_UPLOAD_SUFFIX_PREFERENCE, ".docx")
    ]
    cover_path = next(
        (path for path in uploadable_paths if is_cover_letter_file(path)),
        None,
    )
    resume_candidates = [
        path for path in uploadable_paths if not is_cover_letter_file(path)
    ]
    resume_path = next(
        (
            path
            for suffix in RESUME_UPLOAD_SUFFIX_PREFERENCE
            for path in resume_candidates
            if path.suffix.lower() == suffix
        ),
        None,
    )
    return {
        "resume_path": str(resume_path) if resume_path else None,
        "cover_letter_path": str(cover_path) if cover_path else None,
        "generated_files": [str(path) for path in paths],
    }


def resolve_material_path(path: str) -> Path:
    """Resolve a generated-material path without requiring it to exist yet."""
    material_path = Path(path).expanduser()
    if material_path.is_absolute():
        return material_path.resolve()
    return material_path.resolve()


def is_cover_letter_file(path: Path) -> bool:
    """Return whether a generated file looks like a cover letter."""
    lowered = path.name.lower()
    return "cover" in lowered or "letter" in lowered


def detect_application_platform(url: str) -> str:
    """Classify an application platform from a URL host."""
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if not host:
        return "unknown"
    for platform, keywords in PLATFORM_DOMAIN_KEYWORDS.items():
        for keyword in keywords:
            normalized_keyword = keyword.lower().removeprefix("www.")
            if host == normalized_keyword or host.endswith(f".{normalized_keyword}"):
                return platform
    return "external"


def application_memory_module(platform: str) -> str:
    """Return a stable memory module name for an application platform."""
    safe_platform = re.sub(r"[^a-z0-9_]+", "_", (platform or "unknown").lower()).strip("_")
    return f"job_application_{safe_platform or 'unknown'}"


def with_application_memory(
    result: dict[str, Any],
    *,
    platform: str,
    phase: str,
    source_url: str,
    tool_name: str,
) -> dict[str, Any]:
    """Attach platform-aware memory routing fields to a Playwright result."""
    active_platform = platform or "unknown"
    result["application_platform"] = active_platform
    result["application_phase"] = phase
    result["memory_module"] = application_memory_module(active_platform)
    result["memory_tags"] = [
        tool_name,
        "jobs",
        "application",
        f"platform-{active_platform}",
        phase,
    ]
    result["memory_metadata"] = {
        "application_platform": active_platform,
        "application_phase": phase,
        "source_url": source_url,
    }
    result.setdefault("extracted_data", {})
    result["extracted_data"]["application_platform"] = active_platform
    result["extracted_data"]["application_phase"] = phase
    return result


def extract_fit_keywords(candidate_profile: str, required_keywords: list[str]) -> list[str]:
    """Build a deduplicated keyword list for fit scoring."""
    candidates = [*required_keywords]
    candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", candidate_profile))
    stopwords = {
        "and",
        "the",
        "for",
        "with",
        "from",
        "that",
        "this",
        "remote",
        "engineer",
        "software",
    }
    seen: set[str] = set()
    keywords: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip().lower()
        if len(normalized) < 3 or normalized in stopwords or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(candidate.strip())
    return keywords[:30]


def first_missing_application_material_path(
    *,
    resume_path: str | None,
    cover_letter_path: str | None,
) -> str | None:
    """Return the first configured application material path that is missing."""
    for material_path in (resume_path, cover_letter_path):
        if material_path and not Path(material_path).expanduser().exists():
            return material_path
    return None


def attempt_application_material_uploads(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    resume_path: str | None,
    cover_letter_path: str | None,
    upload_state: dict[str, Any],
) -> None:
    """Upload resume and cover letter when matching inputs are available."""
    if resume_path and not upload_state["resume_uploaded"]:
        upload_selector, upload_success = set_first_file_input(
            page,
            trace,
            APPLICATION_FILE_INPUT_SELECTORS,
            resume_path,
            label="Upload resume into Easy Apply draft",
            timeout=5_000,
        )
        upload_state["resume_uploaded"] = upload_success
        upload_state["resume_upload_selector"] = upload_selector

    if cover_letter_path and not upload_state["cover_letter_uploaded"]:
        cover_selector, cover_success = set_cover_letter_file_input(
            page,
            trace,
            cover_letter_path,
            timeout=2_000,
        )
        upload_state["cover_letter_uploaded"] = cover_success
        upload_state["cover_letter_upload_selector"] = cover_selector


def set_cover_letter_file_input(
    page: Any,
    trace: PlaywrightToolTrace,
    file_path: str | Path,
    *,
    timeout: int = 2_000,
) -> tuple[str | None, bool]:
    """Set the cover-letter file input without overwriting the resume input."""
    resolved_path = Path(file_path).expanduser().resolve()
    selector, locator = first_attached_locator(
        page,
        APPLICATION_COVER_LETTER_FILE_INPUT_SELECTORS,
        timeout=timeout,
    )
    if selector and locator is not None:
        locator.set_input_files(str(resolved_path))
        trace.action(
            "upload_file",
            "Upload cover letter into Easy Apply draft",
            url=getattr(page, "url", None),
            selector=selector,
            success=True,
            details={"path": str(resolved_path)},
        )
        return selector, True

    try:
        locator = page.locator('input[type="file"]').nth(1)
        locator.wait_for(state="attached", timeout=timeout)
        locator.set_input_files(str(resolved_path))
        selector = 'input[type="file"] >> nth=1'
        trace.action(
            "upload_file",
            "Upload cover letter into Easy Apply draft",
            url=getattr(page, "url", None),
            selector=selector,
            success=True,
            details={"path": str(resolved_path)},
        )
        return selector, True
    except Exception as exc:
        trace.action(
            "upload_file",
            "Upload cover letter into Easy Apply draft",
            url=getattr(page, "url", None),
            success=False,
            details={
                "reason": "no attached cover-letter file input matched",
                "path": str(resolved_path),
                "error": str(exc),
            },
        )
        return None, False


def advance_application_to_review(
    page: Any,
    trace: PlaywrightToolTrace,
    *,
    resume_path: str | None,
    cover_letter_path: str | None,
    upload_state: dict[str, Any],
    advance_application: bool,
    max_application_steps: int,
) -> tuple[str | None, bool, int]:
    """Click safe Next/Review steps until Submit is visible or manual input blocks."""
    review_selector, review_ready = find_submit_application_action(page)
    if review_ready or not advance_application:
        if not review_ready:
            review_selector, review_ready = find_first_application_action(page)
        return review_selector, review_ready, 0

    steps_taken = 0
    last_selector: str | None = review_selector
    while steps_taken < max_application_steps:
        attempt_application_material_uploads(
            page,
            trace,
            resume_path=resume_path,
            cover_letter_path=cover_letter_path,
            upload_state=upload_state,
        )
        submit_selector, submit_ready = find_submit_application_action(page)
        if submit_ready:
            return submit_selector, True, steps_taken

        advance_selector, advanced = click_first_visible(
            page,
            trace,
            APPLICATION_REVIEW_BUTTON_SELECTORS,
            label="Advance LinkedIn application draft",
            timeout=2_000,
        )
        last_selector = advance_selector or last_selector
        if not advanced:
            break

        steps_taken += 1
        wait_for_load_state(page, trace, timeout=5_000)

    submit_selector, submit_ready = find_submit_application_action(page)
    if submit_ready:
        return submit_selector, True, steps_taken
    return last_selector, False, steps_taken


def find_submit_application_action(page: Any) -> tuple[str | None, bool]:
    """Find a visible final submit button without clicking it."""
    for selector in APPLICATION_SUBMIT_BUTTON_SELECTORS:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=1_000)
            return selector, True
        except Exception:
            continue
    return None, False


def find_first_application_action(page: Any) -> tuple[str | None, bool]:
    """Find a visible review/next/submit button without clicking it."""
    for selector in (*APPLICATION_SUBMIT_BUTTON_SELECTORS, *APPLICATION_REVIEW_BUTTON_SELECTORS):
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=1_000)
            return selector, True
        except Exception:
            continue
    return None, False


@tool("linkedin-jobs-explorer", args_schema=LinkedInJobsExplorerInput)
def linkedin_jobs_explorer(
    query: str,
    location: str = "",
    candidate_profile: str = "",
    required_keywords: list[str] | None = None,
    easy_apply_only: bool = False,
    limit: int = 10,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Explore LinkedIn Jobs, extract candidates, and record a reusable trace."""
    if not Path(session_state_path).expanduser().exists():
        return build_missing_linkedin_jobs_auth_result(
            session_state_path,
            execution_mode=execution_mode,
        )
    return explore_linkedin_jobs(
        query=query,
        location=location,
        candidate_profile=candidate_profile,
        required_keywords=required_keywords or [],
        easy_apply_only=easy_apply_only,
        limit=limit,
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
    )


@tool("linkedin-job-apply-draft", args_schema=LinkedInJobApplyDraftInput)
def linkedin_job_apply_draft(
    job_url: str,
    resume_path: str | None = None,
    cover_letter_path: str | None = None,
    advance_application: bool = True,
    max_application_steps: int = 5,
    submit: bool = False,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Open LinkedIn Easy Apply and stop before Submit unless y/n confirms."""
    if not Path(session_state_path).expanduser().exists():
        return build_missing_linkedin_jobs_auth_result(
            session_state_path,
            execution_mode=execution_mode,
        )
    return open_linkedin_job_apply_draft(
        job_url=job_url,
        resume_path=resume_path,
        cover_letter_path=cover_letter_path,
        advance_application=advance_application,
        max_application_steps=max_application_steps,
        submit=submit,
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
    )


@tool("linkedin-job-tailored-apply-draft", args_schema=LinkedInJobTailoredApplyDraftInput)
def linkedin_job_tailored_apply_draft(
    job_url: str,
    resume_path: str | None = None,
    cover_letter_path: str | None = None,
    advance_application: bool = True,
    max_application_steps: int = 5,
    submit: bool = False,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    capture_screenshot: bool = True,
    capture_dom_snapshot: bool = True,
    execution_mode: str | None = None,
    library: str = "user_content/library",
    template: str = "",
    output: str = "Tailored_CV.docx",
    output_format: str = "docx",
    provider: str = "auto",
    model: str = "",
    github: str = "",
    suggestions: str = "",
    summarize_years: int = 10,
    no_compile: bool = False,
    timeout_seconds: int | None = None,
    upload_cover_letter: bool = True,
) -> dict[str, Any]:
    """Tailor CV/Cover Letter from a LinkedIn JD URL, then fill Easy Apply."""
    if not Path(session_state_path).expanduser().exists():
        return build_missing_linkedin_jobs_auth_result(
            session_state_path,
            execution_mode=execution_mode,
        )

    if resume_path:
        cover_path = cover_letter_path if upload_cover_letter else None
        return continue_linkedin_job_application_with_materials(
            job_url=job_url,
            resume_path=resume_path,
            cover_letter_path=cover_path,
            advance_application=advance_application,
            max_application_steps=max_application_steps,
            submit=submit,
            session_state_path=session_state_path,
            headless=headless,
            capture_screenshot=capture_screenshot,
            capture_dom_snapshot=capture_dom_snapshot,
        )

    return open_linkedin_job_tailored_apply_draft(
        job_url=job_url,
        submit=submit,
        library=library,
        template=template,
        output=output,
        output_format=output_format,
        provider=provider,
        model=model,
        github=github,
        suggestions=suggestions,
        summarize_years=summarize_years,
        no_compile=no_compile,
        timeout_seconds=timeout_seconds,
        upload_cover_letter=upload_cover_letter,
        advance_application=advance_application,
        max_application_steps=max_application_steps,
        session_state_path=session_state_path,
        headless=headless,
        capture_screenshot=capture_screenshot,
        capture_dom_snapshot=capture_dom_snapshot,
    )


__all__ = [
    "APPLICATION_COVER_LETTER_FILE_INPUT_SELECTORS",
    "APPLICATION_FILE_INPUT_SELECTORS",
    "APPLICATION_REVIEW_BUTTON_SELECTORS",
    "APPLICATION_SUBMIT_BUTTON_SELECTORS",
    "EASY_APPLY_BUTTON_SELECTORS",
    "EXTERNAL_APPLICATION_ADVANCE_SELECTORS",
    "EXTERNAL_APPLICATION_SUBMIT_BUTTON_SELECTORS",
    "EXTERNAL_APPLY_BUTTON_SELECTORS",
    "JOB_CARD_SELECTORS",
    "JOB_COPY_LINK_BUTTON_SELECTORS",
    "JOB_MORE_ACTIONS_BUTTON_SELECTORS",
    "JOB_SHARE_BUTTON_SELECTORS",
    "LINKEDIN_JOBS_MODULE",
    "LINKEDIN_JOBS_URL",
    "PLATFORM_DOMAIN_KEYWORDS",
    "LinkedInJobApplyDraftInput",
    "LinkedInJobTailoredApplyDraftInput",
    "LinkedInJobsExplorerInput",
    "advance_application_to_review",
    "advance_external_application_draft",
    "application_memory_module",
    "attempt_application_material_uploads",
    "build_job_description_for_cv_tailoring",
    "build_linkedin_jobs_search_url",
    "build_missing_linkedin_jobs_auth_result",
    "click_external_apply_button",
    "continue_application_from_job_page",
    "continue_linkedin_job_application_with_materials",
    "copy_linkedin_job_link_from_share",
    "copy_linkedin_job_share_link",
    "detect_application_platform",
    "extract_fit_keywords",
    "extract_first_url",
    "extract_linkedin_job_cards",
    "extract_linkedin_job_description",
    "fill_external_application_answers",
    "fill_linkedin_easy_apply_draft",
    "find_first_application_action",
    "find_submit_application_action",
    "first_missing_application_material_path",
    "grant_clipboard_permissions",
    "inspect_external_application_form_state",
    "is_cover_letter_file",
    "linkedin_job_apply_draft",
    "linkedin_job_tailored_apply_draft",
    "linkedin_jobs_explorer",
    "normalize_job_url",
    "normalize_linkedin_job",
    "open_linkedin_job_apply_draft",
    "open_external_application_from_linkedin",
    "open_linkedin_job_tailored_apply_draft",
    "read_browser_clipboard",
    "resolve_material_path",
    "score_linkedin_job_fit",
    "select_application_material_paths",
    "set_cover_letter_file_input",
    "tailor_linkedin_job_application_materials",
]
