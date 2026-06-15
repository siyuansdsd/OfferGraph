"""LinkedIn content editor LangChain tool."""

from pathlib import Path
from typing import Any, Callable, Literal

from langchain_core.tools import tool
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from pydantic import BaseModel, Field

from tools.approval import ApprovalRequest, request_user_approval
from tools.linkedin.auth import LINKEDIN_FEED_URL


DEFAULT_LINKEDIN_SESSION_STATE_PATH = ".auth/linkedin.json"
LINKEDIN_AUTH_SETUP_COMMAND = "./.venv/bin/python scripts/setup_linkedin_auth.py"
COMPOSER_BUTTON_SELECTORS = (
    'button:has-text("Start a post")',
    'div[role="button"]:has-text("Start a post")',
    '[aria-label*="Start a post"]',
    'button[aria-label*="Create a post"]',
    '[aria-label*="Create a post"]',
    '[data-control-name="share.sharebox_focus"]',
    ".share-box-feed-entry__trigger",
)
COMPOSER_EDITOR_SELECTORS = (
    ".share-creation-state__text-editor .ql-editor[contenteditable='true']",
    ".ql-editor[contenteditable='true']",
    "[role='textbox'][contenteditable='true']",
    "div[contenteditable='true']",
)
POST_BUTTON_SELECTORS = (
    "button.share-actions__primary-action",
    'button:has-text("Post")',
    'button[aria-label*="Post"]',
    '[data-control-name="share.post"]',
)
DEFAULT_PLAYWRIGHT_TIMEOUT_MS = 15_000


class LinkedInEditorInput(BaseModel):
    """Input schema for the linkedin-editor tool."""

    task: str = Field(
        ...,
        description="The goal or brief for the LinkedIn post.",
    )
    post_text: str = Field(
        ...,
        description=(
            "The exact final LinkedIn post text to insert into the composer. "
            "Do not pass a task brief, outline, facts list, or instructions here."
        ),
    )
    draft_only: bool = Field(
        default=True,
        description="When true, stop after preparing or inserting a draft.",
    )
    publish: bool = Field(
        default=False,
        description="When true, publish the post. Use only after explicit user confirmation.",
    )
    session_state_path: str = Field(
        default=DEFAULT_LINKEDIN_SESSION_STATE_PATH,
        description="Playwright storage_state path for the authenticated LinkedIn session.",
    )
    headless: bool = Field(
        default=False,
        description="Whether Playwright should run in headless mode.",
    )
    execution_mode: str | None = Field(
        default=None,
        description=(
            "Approval mode override. Use auto-mode to skip approval gates, or "
            "approve-mode to require explicit approval. Defaults to OFFERGRAPH_TOOL_MODE "
            "or approve-mode."
        ),
    )


class LinkedInEditorResult(BaseModel):
    """Structured result returned by the linkedin-editor tool."""

    status: Literal[
        "planned",
        "draft_ready",
        "needs_confirmation",
        "published",
        "error",
        "needs_approval",
        "manual_required",
    ]
    message: str
    draft: str | None = None
    url: str | None = None
    screenshot: str | None = None
    approval: dict[str, Any] | None = None


class LinkedInEditorBrowserError(RuntimeError):
    """Raised when LinkedIn browser automation cannot prepare a draft."""


class LinkedInDraftValidationError(ValueError):
    """Raised when linkedin-editor receives a brief instead of final post text."""


def open_linkedin_composer(
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    *,
    headless: bool = False,
    draft: str | None = None,
    publish: bool = False,
    wait_for_user: Callable[[str], str] | None = None,
    confirm_publish: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Open LinkedIn's post composer, insert a draft, and optionally post it."""
    resolved_state_path = Path(session_state_path).expanduser().resolve()
    if not resolved_state_path.exists():
        raise FileNotFoundError(f"LinkedIn auth state not found: {resolved_state_path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(resolved_state_path))
        page = context.new_page()
        try:
            page.goto(
                LINKEDIN_FEED_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=DEFAULT_PLAYWRIGHT_TIMEOUT_MS,
                )
            except PlaywrightError:
                pass
            if "linkedin.com/login" in page.url or "authwall" in page.url:
                raise LinkedInEditorBrowserError(
                    "LinkedIn session is missing or expired. Re-run auth setup."
                )

            composer_selector, composer_button = _first_visible_locator(
                page,
                COMPOSER_BUTTON_SELECTORS,
                purpose="LinkedIn post composer button",
            )
            composer_button.click()

            editor_selector, editor = _first_visible_locator(
                page,
                COMPOSER_EDITOR_SELECTORS,
                purpose="LinkedIn post editor",
            )
            if draft:
                _fill_linkedin_editor(page, editor, draft)

            published = False
            post_selector = None
            publish_confirmed = False
            if publish:
                confirmer = confirm_publish or input
                publish_confirmed = confirm_linkedin_publish(confirmer)
                if publish_confirmed:
                    post_selector, post_button = _first_visible_locator(
                        page,
                        POST_BUTTON_SELECTORS,
                        purpose="LinkedIn post button",
                    )
                    post_button.click()
                    published = True
                    try:
                        page.wait_for_load_state(
                            "networkidle",
                            timeout=DEFAULT_PLAYWRIGHT_TIMEOUT_MS,
                        )
                    except PlaywrightError:
                        pass

            current_url = page.url
            if not headless and not published:
                reviewer = wait_for_user or input
                reviewer(
                    "LinkedIn draft is open in the browser. "
                    "Review it there, then press Enter here to close Playwright..."
                )

            return {
                "url": current_url,
                "composer_selector": composer_selector,
                "editor_selector": editor_selector,
                "draft_inserted": bool(draft),
                "publish_requested": publish,
                "publish_confirmed": publish_confirmed,
                "published": published,
                "post_selector": post_selector,
            }
        finally:
            browser.close()


def compose_post(post_text: str, *, task: str | None = None) -> str:
    """Return the exact draft text that should be inserted into LinkedIn."""
    draft = post_text.strip()
    if not draft:
        raise LinkedInDraftValidationError(
            "linkedin-editor needs the final LinkedIn post text in post_text. "
            "Do not call it with only a task brief; draft the post first, then pass "
            "the exact post body through post_text."
        )

    if (task and draft == task.strip()) or _looks_like_task_brief(draft):
        raise LinkedInDraftValidationError(
            "linkedin-editor received a task brief instead of final post text. "
            "Pass only the exact LinkedIn post body in post_text."
        )

    return draft


def _looks_like_task_brief(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    brief_prefixes = (
        "create a linkedin post",
        "create and post",
        "draft a linkedin post",
        "prepare a linkedin post",
        "write a linkedin post",
        "help me create",
        "help me open linkedin",
    )
    return any(normalized.startswith(prefix) for prefix in brief_prefixes)


def publish_or_save_draft(
    draft: str,
    *,
    publish: bool = False,
    browser_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the publish status for a prepared draft."""
    if publish:
        if browser_result and browser_result.get("published"):
            return {
                "status": "published",
                "message": (
                    "Draft was prepared in LinkedIn and posted after y/n confirmation."
                ),
            }
        return {
            "status": "needs_confirmation",
            "message": (
                "Draft was prepared in LinkedIn, but terminal confirmation was not "
                "granted. It was left unpublished."
            ),
        }

    return {
        "status": "draft_ready",
        "message": "Draft was prepared in LinkedIn and left unpublished.",
    }


def confirm_linkedin_publish(input_func: Callable[[str], str] = input) -> bool:
    """Ask for explicit terminal confirmation before clicking LinkedIn Post."""
    answer = input_func(
        "Post this LinkedIn draft now? Type y/yes to post, or n/no to leave it unpublished: "
    )
    return answer.strip().lower() in {"y", "yes"}


def _first_visible_locator(
    page: Any,
    selectors: tuple[str, ...],
    *,
    purpose: str,
) -> tuple[str, Any]:
    errors: list[str] = []
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=DEFAULT_PLAYWRIGHT_TIMEOUT_MS)
            return selector, locator
        except PlaywrightError as exc:
            errors.append(f"{selector}: {exc}")

    raise LinkedInEditorBrowserError(
        f"Could not find {purpose}. Tried selectors: {', '.join(selectors)}. "
        f"Details: {' | '.join(errors)}"
    )


def _fill_linkedin_editor(page: Any, editor: Any, draft: str) -> None:
    editor.click()
    try:
        editor.fill(draft, timeout=DEFAULT_PLAYWRIGHT_TIMEOUT_MS)
    except PlaywrightError:
        page.keyboard.insert_text(draft)


def build_linkedin_auth_approval_request(session_state_path: str) -> ApprovalRequest:
    """Build the reusable approval request for LinkedIn login state setup."""
    return ApprovalRequest(
        action="linkedin-auth-setup",
        reason=(
            "linkedin-editor needs a saved LinkedIn Playwright session before it can "
            "open the composer as your account."
        ),
        automated_flow=(
            "Run the LinkedIn auth setup flow: open a visible Playwright browser, let "
            f"you log in manually, and save session state to {session_state_path}."
        ),
        manual_steps=[
            "./.venv/bin/python -m playwright install chromium",
            LINKEDIN_AUTH_SETUP_COMMAND,
            "Log in to LinkedIn in the opened Playwright browser.",
            "After the feed is visible, return to the terminal and press Enter.",
        ],
    )


def check_linkedin_auth_approval(
    session_state_path: str,
    *,
    execution_mode: str | None = None,
) -> dict[str, Any] | None:
    """Return an approval response when LinkedIn auth setup is required."""
    if Path(session_state_path).expanduser().exists():
        return None

    try:
        decision = request_user_approval(
            build_linkedin_auth_approval_request(session_state_path),
            mode=execution_mode,
            interactive=False,
        )
    except ValueError as exc:
        return LinkedInEditorResult(
            status="error",
            message=str(exc),
            url="https://www.linkedin.com/feed/",
        ).model_dump(exclude_none=True)
    if decision.approved:
        message = (
            "LinkedIn auth state is missing. Auto-mode cannot create it because "
            "LinkedIn login requires your manual browser session. Run the setup steps."
        )
        return LinkedInEditorResult(
            status="manual_required",
            message=message,
            url=LINKEDIN_FEED_URL,
            approval={
                **decision.model_dump(),
                "status": "manual_required",
                "approved": False,
                "message": message,
            },
        ).model_dump(exclude_none=True)

    return LinkedInEditorResult(
        status=decision.status,
        message=decision.message,
        url=LINKEDIN_FEED_URL,
        approval=decision.model_dump(),
    ).model_dump(exclude_none=True)


@tool("linkedin-editor", args_schema=LinkedInEditorInput)
def linkedin_editor(
    task: str,
    post_text: str,
    draft_only: bool = True,
    publish: bool = False,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Open LinkedIn, insert a draft, and leave it unpublished by default."""
    if publish and draft_only:
        return LinkedInEditorResult(
            status="error",
            message=(
                "Invalid input: publish=True conflicts with draft_only=True. "
                "Set draft_only=False only after explicit user confirmation."
            ),
        ).model_dump(exclude_none=True)

    auth_approval_response = check_linkedin_auth_approval(
        session_state_path,
        execution_mode=execution_mode,
    )
    if auth_approval_response is not None:
        return auth_approval_response

    try:
        draft = compose_post(post_text, task=task)
    except LinkedInDraftValidationError as exc:
        return LinkedInEditorResult(
            status="error",
            message=str(exc),
            url=LINKEDIN_FEED_URL,
        ).model_dump(exclude_none=True)

    try:
        browser_result = open_linkedin_composer(
            session_state_path,
            headless=headless,
            draft=draft,
            publish=publish,
        )
    except (FileNotFoundError, LinkedInEditorBrowserError, PlaywrightError) as exc:
        return LinkedInEditorResult(
            status="error",
            message=str(exc),
            draft=draft,
            url=LINKEDIN_FEED_URL,
        ).model_dump(exclude_none=True)

    publish_decision = publish_or_save_draft(
        draft,
        publish=publish,
        browser_result=browser_result,
    )

    return LinkedInEditorResult(
        status=publish_decision["status"],
        message=publish_decision["message"],
        draft=draft,
        url=str(browser_result.get("url") or LINKEDIN_FEED_URL),
    ).model_dump(exclude_none=True)
