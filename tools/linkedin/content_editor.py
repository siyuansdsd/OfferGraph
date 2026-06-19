"""LinkedIn content editor LangChain tool."""

import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any, Callable, Literal

from langchain_core.tools import tool
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from pydantic import BaseModel, Field

from agent.memory import record_browser_trace_safely
from config.env import PROJECT_ROOT
from tools.image_tools import (
    DEFAULT_IMAGE_CANDIDATE_LIMIT,
    build_image_search_query,
    download_image_url,
    extract_image_candidates,
    generate_openai_image,
    run_tavily_image_search,
)
from tools.approval import ApprovalRequest, request_user_approval
from tools.linkedin.auth import LINKEDIN_FEED_URL


DEFAULT_LINKEDIN_SESSION_STATE_PATH = ".auth/linkedin.json"
LINKEDIN_AUTH_SETUP_COMMAND = "./.venv/bin/python scripts/setup_linkedin_auth.py"
DEFAULT_AUTO_IMAGE_BRIEF = (
    "professional LinkedIn visual, modern AI product announcement, clean data "
    "visualization, no readable text, no fake logos"
)
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
MEDIA_BUTTON_SELECTORS = (
    'button[aria-label*="Add media"]',
    'button[aria-label*="Photo"]',
    'button[aria-label*="Media"]',
    '[aria-label*="Add media"]',
    '[aria-label*="Photo"]',
    '[aria-label*="Media"]',
    '[data-control-name="share.media_upload"]',
    'button:has-text("Photo")',
)
MEDIA_FILE_INPUT_SELECTORS = (
    'input[type="file"]',
    'input.accept-image[type="file"]',
)
MEDIA_PREVIEW_SELECTORS = (
    ".share-creation-state__preview-container",
    ".share-creation-state__preview-content",
    ".share-media-editor",
    ".share-image",
    ".share-box-v2__image",
    "[data-test-media-preview]",
    "[data-test-share-media-image]",
    "img[src^='blob:']",
    "img[alt]",
)
MEDIA_FINALIZE_BUTTON_SELECTORS = (
    'button:has-text("Next")',
    'button[aria-label*="Next"]',
    'button:has-text("Done")',
    'button[aria-label*="Done"]',
    'button:has-text("Add")',
    'button[aria-label*="Add"]',
    'button:has-text("Apply")',
    'button[aria-label*="Apply"]',
    'button:has-text("Save")',
    'button[aria-label*="Save"]',
)
ALT_TEXT_BUTTON_SELECTORS = (
    'button:has-text("Alt text")',
    'button:has-text("Add alt text")',
    'button[aria-label*="Alt text"]',
    '[aria-label*="Alt text"]',
)
ALT_TEXT_INPUT_SELECTORS = (
    'textarea[aria-label*="alt"]',
    'textarea[name*="alt"]',
    "textarea",
)
ALT_TEXT_SAVE_SELECTORS = (
    'button:has-text("Save")',
    'button:has-text("Done")',
    'button[aria-label*="Save"]',
)
DEFAULT_PLAYWRIGHT_TIMEOUT_MS = 15_000
IMAGE_ATTACH_TIMEOUT_MS = 5_000
CURSOR_MOVE_DURATION_MS = 650
_PREPARED_DRAFT_KEYS: set[str] = set()
IMAGE_RELEVANCE_STOPWORDS = {
    "about",
    "after",
    "analysis",
    "announcement",
    "clean",
    "create",
    "draft",
    "image",
    "linkedin",
    "model",
    "modern",
    "news",
    "post",
    "professional",
    "text",
    "visual",
    "with",
}


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
    image_path: str | None = Field(
        default=None,
        description="Local image file path to upload into the LinkedIn composer.",
    )
    image_url: str | None = Field(
        default=None,
        description="Remote image URL to download locally and upload into the LinkedIn composer.",
    )
    alt_text: str | None = Field(
        default=None,
        description="Optional alt text to set or store for the uploaded image.",
    )
    auto_image: bool = Field(
        default=True,
        description=(
            "When true and no image_path/image_url is provided, search for a "
            "matching image first and generate one as fallback."
        ),
    )
    require_image: bool = Field(
        default=True,
        description="When true, return an error instead of preparing a text-only draft.",
    )
    show_cursor: bool = Field(
        default=True,
        description="Show a visible in-page cursor and move it before key Playwright clicks.",
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
    image_path: str | None = None
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
    image_path: str | None = None,
    alt_text: str | None = None,
    show_cursor: bool = True,
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
            if show_cursor:
                _enable_visual_cursor(page)

            composer_selector, composer_button = _first_visible_locator(
                page,
                COMPOSER_BUTTON_SELECTORS,
                purpose="LinkedIn post composer button",
            )
            _click_locator(page, composer_button, show_cursor=show_cursor)

            editor_selector, editor = _first_visible_locator(
                page,
                COMPOSER_EDITOR_SELECTORS,
                purpose="LinkedIn post editor",
            )
            if draft:
                _fill_linkedin_editor(page, editor, draft, show_cursor=show_cursor)

            image_upload_result: dict[str, Any] | None = None
            if image_path:
                image_upload_result = _upload_linkedin_image(
                    page,
                    image_path,
                    alt_text=alt_text,
                    show_cursor=show_cursor,
                )

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
                    _click_locator(page, post_button, show_cursor=show_cursor)
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
                "image_path": image_upload_result.get("image_path") if image_upload_result else None,
                "image_uploaded": bool(image_upload_result),
                "image_upload": image_upload_result,
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


def resolve_linkedin_image_upload_path(
    *,
    image_path: str | None = None,
    image_url: str | None = None,
) -> str | None:
    """Resolve a local upload path from image_path or downloaded image_url."""
    if image_path:
        resolved_path = Path(image_path).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = PROJECT_ROOT / resolved_path
        resolved_path = resolved_path.resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"LinkedIn image file not found: {resolved_path}")
        if not resolved_path.is_file():
            raise ValueError(f"LinkedIn image path is not a file: {resolved_path}")
        return str(resolved_path)

    if image_url:
        return str(
            download_image_url(
                image_url,
                filename_hint="linkedin_editor_upload",
            )
        )

    return None


def prepare_linkedin_editor_image(
    *,
    task: str,
    post_text: str,
    alt_text: str | None = None,
    image_brief: str = DEFAULT_AUTO_IMAGE_BRIEF,
) -> tuple[str | None, dict[str, Any]]:
    """Prepare a local image path for LinkedIn editor using search, then generation."""
    query = build_image_search_query(
        task,
        image_brief=image_brief,
        post_text=post_text,
    )
    metadata: dict[str, Any] = {
        "query": query,
        "source": None,
        "errors": [],
    }

    try:
        search_response = run_tavily_image_search(
            query,
            max_results=DEFAULT_IMAGE_CANDIDATE_LIMIT,
        )
        candidates = extract_image_candidates(
            search_response,
            max_candidates=DEFAULT_IMAGE_CANDIDATE_LIMIT,
        )
        metadata["candidate_count"] = len(candidates)
        relevant_candidates = [
            candidate
            for candidate in candidates
            if is_relevant_image_candidate(
                candidate,
                topic_text=f"{task} {post_text}",
            )
        ]
        metadata["relevant_candidate_count"] = len(relevant_candidates)
        for candidate in relevant_candidates:
            try:
                image_path = download_image_url(
                    candidate.url,
                    filename_hint=candidate.title or task,
                )
                metadata.update(
                    {
                        "source": "tavily",
                        "image_url": candidate.url,
                        "source_url": candidate.source_url,
                        "image_path": str(image_path),
                    }
                )
                return str(image_path), metadata
            except Exception as exc:
                metadata["errors"].append(
                    f"download failed for {candidate.url}: {exc}"
                )
    except Exception as exc:
        metadata["errors"].append(f"image search failed: {exc}")

    image_prompt = build_auto_linkedin_image_prompt(
        task=task,
        post_text=post_text,
        alt_text=alt_text,
        image_brief=image_brief,
    )
    image_result = generate_openai_image(image_prompt)
    metadata["generation"] = image_result.model_dump(exclude_none=True)
    if image_result.image_path:
        metadata.update(
            {
                "source": "openai",
                "image_path": image_result.image_path,
                "image_url": image_result.image_url,
            }
        )
        return image_result.image_path, metadata

    metadata["errors"].append(image_result.message)
    return None, metadata


def is_relevant_image_candidate(candidate: Any, *, topic_text: str) -> bool:
    """Return whether a searched image candidate appears related to the post topic."""
    terms = _important_image_terms(topic_text)
    if not terms:
        return True
    haystack = " ".join(
        str(value or "")
        for value in (
            getattr(candidate, "url", ""),
            getattr(candidate, "source_url", ""),
            getattr(candidate, "title", ""),
            getattr(candidate, "description", ""),
        )
    ).lower()
    return any(term in haystack for term in terms)


def _important_image_terms(text: str) -> list[str]:
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", text)
        if len(token) >= 2
    ]
    priority = [
        token
        for token in tokens
        if token not in IMAGE_RELEVANCE_STOPWORDS
        and (any(char.isdigit() for char in token) or len(token) >= 4)
    ]
    seen: set[str] = set()
    terms: list[str] = []
    for token in priority:
        if token not in seen:
            seen.add(token)
            terms.append(token)
        if len(terms) >= 8:
            break
    return terms


def build_auto_linkedin_image_prompt(
    *,
    task: str,
    post_text: str,
    alt_text: str | None = None,
    image_brief: str = DEFAULT_AUTO_IMAGE_BRIEF,
) -> str:
    """Build a generation prompt for an automatic LinkedIn post image."""
    return (
        f"{image_brief}. Topic: {' '.join(task.split())[:220]}. "
        f"Post context: {' '.join(post_text.split())[:500]}. "
        f"Accessibility intent: {' '.join((alt_text or '').split())[:220]}. "
        "Use a polished editorial technology style suitable for LinkedIn. "
        "Avoid adding readable text, brand logos, watermarks, UI screenshots, or stock-photo people."
    )


def record_linkedin_editor_memory(
    *,
    task: str,
    draft: str,
    browser_result: dict[str, Any] | None,
    status: str,
    message: str,
    publish: bool,
    success: bool,
    error: str | None = None,
    image_path: str | None = None,
    alt_text: str | None = None,
    image_preparation: dict[str, Any] | None = None,
) -> None:
    """Record a sanitized LinkedIn browser trace for future retrieval."""
    result = browser_result or {}
    url = str(result.get("url") or LINKEDIN_FEED_URL)
    actions: list[dict[str, Any]] = [
        {
            "type": "navigate",
            "label": "Open LinkedIn feed",
            "url": LINKEDIN_FEED_URL,
            "success": success or bool(browser_result),
        }
    ]
    if result.get("composer_selector"):
        actions.append(
            {
                "type": "click",
                "label": "Open LinkedIn post composer",
                "selector": str(result["composer_selector"]),
                "success": True,
            }
        )
    if result.get("editor_selector"):
        actions.append(
            {
                "type": "fill",
                "label": "Insert final LinkedIn post text",
                "selector": str(result["editor_selector"]),
                "success": bool(result.get("draft_inserted", True)),
                "details": {
                    "draft_character_count": len(draft),
                    "draft_preview": _preview_text(draft),
                },
            }
        )
    if result.get("image_uploaded") or image_path:
        upload = result.get("image_upload") or {}
        actions.append(
            {
                "type": "upload",
                "label": "Upload LinkedIn post image",
                "selector": upload.get("file_input_selector"),
                "success": bool(result.get("image_uploaded")),
                "details": {
                    "image_path": result.get("image_path") or image_path,
                    "preview_ready": bool(upload.get("preview_ready")),
                    "finalized": bool(upload.get("finalized")),
                    "post_review_ready": bool(upload.get("post_review_ready")),
                    "alt_text_set": bool(upload.get("alt_text_set")),
                },
            }
        )
    if publish:
        actions.append(
            {
                "type": "confirm",
                "label": "Request terminal publish confirmation",
                "success": bool(result.get("publish_confirmed")),
            }
        )
    if result.get("post_selector"):
        actions.append(
            {
                "type": "click",
                "label": "Click LinkedIn Post button",
                "selector": str(result["post_selector"]),
                "success": bool(result.get("published")),
            }
        )

    record_browser_trace_safely(
        task=task,
        final_result=f"{status}: {message}",
        success=success,
        url=url,
        actions=actions,
        extracted_data={
            "status": status,
            "draft_character_count": len(draft),
            "draft_preview": _preview_text(draft),
            "draft_inserted": bool(result.get("draft_inserted")),
            "publish_requested": bool(result.get("publish_requested", publish)),
            "publish_confirmed": bool(result.get("publish_confirmed")),
            "published": bool(result.get("published")),
            "image_path": result.get("image_path") or image_path,
            "image_uploaded": bool(result.get("image_uploaded")),
            "alt_text_preview": _preview_text(alt_text or "", max_chars=200) if alt_text else None,
            "image_preparation": image_preparation,
            "composer_selector": result.get("composer_selector"),
            "editor_selector": result.get("editor_selector"),
            "post_selector": result.get("post_selector"),
        },
        error=error,
        module="linkedin",
        tags=["linkedin", "linkedin-editor", "playwright", status],
        metadata={"tool": "linkedin-editor"},
    )


def _preview_text(text: str, *, max_chars: int = 500) -> str:
    """Return a compact text preview for memory."""
    normalized = " ".join(text.split())
    return normalized[:max_chars]


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
    timeout: int = DEFAULT_PLAYWRIGHT_TIMEOUT_MS,
) -> tuple[str, Any]:
    errors: list[str] = []
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout)
            return selector, locator
        except PlaywrightError as exc:
            errors.append(f"{selector}: {exc}")

    raise LinkedInEditorBrowserError(
        f"Could not find {purpose}. Tried selectors: {', '.join(selectors)}. "
        f"Details: {' | '.join(errors)}"
    )


def _first_attached_locator(
    page: Any,
    selectors: tuple[str, ...],
    *,
    purpose: str,
    timeout: int = DEFAULT_PLAYWRIGHT_TIMEOUT_MS,
) -> tuple[str, Any]:
    errors: list[str] = []
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="attached", timeout=timeout)
            return selector, locator
        except PlaywrightError as exc:
            errors.append(f"{selector}: {exc}")

    raise LinkedInEditorBrowserError(
        f"Could not find {purpose}. Tried selectors: {', '.join(selectors)}. "
        f"Details: {' | '.join(errors)}"
    )


def _wait_for_optional_visible(
    page: Any,
    selectors: tuple[str, ...],
    *,
    timeout: int = IMAGE_ATTACH_TIMEOUT_MS,
) -> tuple[str | None, bool]:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout)
            return selector, True
        except PlaywrightError:
            continue
    return None, False


def _enable_visual_cursor(page: Any) -> bool:
    """Inject a visible cursor overlay into the current page."""
    try:
        return bool(
            page.evaluate(
                """
                () => {
                  const id = "offergraph-playwright-cursor";
                  let cursor = document.getElementById(id);
                  if (!cursor) {
                    cursor = document.createElement("div");
                    cursor.id = id;
                    cursor.style.cssText = [
                      "position: fixed",
                      "left: 0",
                      "top: 0",
                      "width: 18px",
                      "height: 18px",
                      "border: 3px solid #ff2d55",
                      "background: rgba(255, 45, 85, 0.18)",
                      "border-radius: 999px",
                      "box-shadow: 0 0 0 5px rgba(255, 45, 85, 0.18)",
                      "transform: translate3d(50vw, 50vh, 0) translate(-50%, -50%) scale(1)",
                      "z-index: 2147483647",
                      "pointer-events: none",
                      "transition: background 120ms ease, box-shadow 120ms ease",
                      "will-change: transform"
                    ].join(";");
                    document.documentElement.appendChild(cursor);
                  }

                  window.__offergraphCursorState = window.__offergraphCursorState || {
                    x: Math.round(window.innerWidth * 0.5),
                    y: Math.round(window.innerHeight * 0.5),
                    active: false,
                    animation: null
                  };

                  const state = window.__offergraphCursorState;
                  const renderCursor = () => {
                    const activeCursor = document.getElementById(id);
                    if (!activeCursor) return false;
                    const scale = state.active ? 0.72 : 1;
                    activeCursor.style.transform = [
                      `translate3d(${state.x}px, ${state.y}px, 0)`,
                      "translate(-50%, -50%)",
                      `scale(${scale})`
                    ].join(" ");
                    activeCursor.style.background = state.active
                      ? "rgba(255, 45, 85, 0.42)"
                      : "rgba(255, 45, 85, 0.18)";
                    activeCursor.style.boxShadow = state.active
                      ? "0 0 0 9px rgba(255, 45, 85, 0.16)"
                      : "0 0 0 5px rgba(255, 45, 85, 0.18)";
                    return true;
                  };

                  const easeOutCubic = (value) => 1 - Math.pow(1 - value, 3);

                  window.__offergraphAnimateCursorTo = ({ x, y, duration = 550, active = false }) => {
                    if (state.animation) {
                      window.cancelAnimationFrame(state.animation);
                      state.animation = null;
                    }
                    const startX = state.x;
                    const startY = state.y;
                    const startedAt = window.performance.now();
                    state.active = Boolean(active);
                    renderCursor();

                    return new Promise((resolve) => {
                      const step = (now) => {
                        const progress = duration <= 0
                          ? 1
                          : Math.min((now - startedAt) / duration, 1);
                        const eased = easeOutCubic(progress);
                        state.x = startX + (x - startX) * eased;
                        state.y = startY + (y - startY) * eased;
                        renderCursor();
                        if (progress < 1) {
                          state.animation = window.requestAnimationFrame(step);
                          return;
                        }
                        state.x = x;
                        state.y = y;
                        state.animation = null;
                        renderCursor();
                        resolve(true);
                      };
                      state.animation = window.requestAnimationFrame(step);
                    });
                  };

                  window.__offergraphMoveCursor = (x, y, active = false) => {
                    state.x = x;
                    state.y = y;
                    state.active = Boolean(active);
                    return renderCursor();
                  };

                  window.__offergraphSetCursorActive = (active = false) => {
                    state.active = Boolean(active);
                    return renderCursor();
                  };

                  renderCursor();
                  return true;
                }
                """
            )
        )
    except Exception:
        return False


def _move_cursor_to_locator(page: Any, locator: Any) -> bool:
    """Move the visible cursor and Playwright mouse to a locator center."""
    try:
        bounding_box = locator.bounding_box(timeout=2_000)
    except Exception:
        return False
    if not bounding_box:
        return False

    x = bounding_box["x"] + bounding_box["width"] / 2
    y = bounding_box["y"] + bounding_box["height"] / 2
    _animate_visual_cursor_to(page, x, y, duration_ms=CURSOR_MOVE_DURATION_MS)
    try:
        page.mouse.move(x, y, steps=16)
    except Exception:
        try:
            page.mouse.move(x, y)
        except Exception:
            pass
    return True


def _animate_visual_cursor_to(
    page: Any,
    x: float,
    y: float,
    *,
    duration_ms: int = CURSOR_MOVE_DURATION_MS,
    active: bool = False,
) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                async ({ x, y, duration, active }) => {
                  if (window.__offergraphAnimateCursorTo) {
                    return await window.__offergraphAnimateCursorTo({
                      x,
                      y,
                      duration,
                      active
                    });
                  }
                  if (window.__offergraphMoveCursor) {
                    return window.__offergraphMoveCursor(x, y, active);
                  }
                  return false;
                }
                """,
                {
                    "x": x,
                    "y": y,
                    "duration": duration_ms,
                    "active": active,
                },
            )
        )
    except Exception:
        return False


def _set_visual_cursor_active(page: Any, active: bool) -> None:
    try:
        page.evaluate(
            """
            (active) => {
              if (window.__offergraphSetCursorActive) {
                return window.__offergraphSetCursorActive(active);
              }
              return false;
            }
            """,
            active,
        )
    except Exception:
        return


def _pulse_visual_cursor(page: Any, locator: Any) -> None:
    _set_visual_cursor_active(page, True)
    try:
        page.wait_for_timeout(120)
    except Exception:
        pass
    _set_visual_cursor_active(page, False)


def _click_locator(page: Any, locator: Any, *, show_cursor: bool = True) -> None:
    if show_cursor:
        _move_cursor_to_locator(page, locator)
    locator.click()
    if show_cursor:
        _pulse_visual_cursor(page, locator)


def _fill_linkedin_editor(
    page: Any,
    editor: Any,
    draft: str,
    *,
    show_cursor: bool = True,
) -> None:
    _click_locator(page, editor, show_cursor=show_cursor)
    try:
        editor.fill(draft, timeout=DEFAULT_PLAYWRIGHT_TIMEOUT_MS)
    except PlaywrightError:
        page.keyboard.insert_text(draft)


def _upload_linkedin_image(
    page: Any,
    image_path: str,
    *,
    alt_text: str | None = None,
    show_cursor: bool = True,
) -> dict[str, Any]:
    resolved_path = Path(image_path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"LinkedIn image file not found: {resolved_path}")

    upload_result = _upload_linkedin_image_file(
        page,
        resolved_path,
        show_cursor=show_cursor,
    )
    preview_selector, preview_ready = _wait_for_optional_visible(
        page,
        MEDIA_PREVIEW_SELECTORS,
    )
    if not preview_ready:
        paste_result = _paste_linkedin_image(
            page,
            resolved_path,
            show_cursor=show_cursor,
        )
        if paste_result.get("pasted"):
            upload_result = paste_result
            preview_selector, preview_ready = _wait_for_optional_visible(
                page,
                MEDIA_PREVIEW_SELECTORS,
            )

    if not preview_ready:
        raise LinkedInEditorBrowserError(
            "LinkedIn image upload did not show a preview. "
            f"Tried method: {upload_result.get('method') or 'unknown'}."
        )

    alt_text_set = (
        _try_set_linkedin_alt_text(page, alt_text, show_cursor=show_cursor)
        if alt_text
        else False
    )
    finalize_result = _finalize_linkedin_media_review(page, show_cursor=show_cursor)
    return {
        "image_path": str(resolved_path),
        "method": upload_result.get("method"),
        "media_selector": upload_result.get("media_selector"),
        "file_input_selector": upload_result.get("file_input_selector"),
        "preview_selector": preview_selector,
        "preview_ready": preview_ready,
        "finalized": finalize_result.get("finalized", False),
        "finalize_selector": finalize_result.get("selector"),
        "post_review_ready": finalize_result.get("post_review_ready", False),
        "alt_text_set": alt_text_set,
        "alt_text_provided": bool(alt_text),
    }


def _upload_linkedin_image_file(
    page: Any,
    image_path: Path,
    *,
    show_cursor: bool = True,
) -> dict[str, Any]:
    try:
        file_input_selector, file_input = _first_attached_locator(
            page,
            MEDIA_FILE_INPUT_SELECTORS,
            purpose="LinkedIn image file input",
            timeout=2_000,
        )
        file_input.set_input_files(str(image_path))
        return {
            "method": "file_input",
            "file_input_selector": file_input_selector,
            "media_selector": None,
        }
    except (LinkedInEditorBrowserError, PlaywrightError):
        pass

    media_selector, media_button = _first_visible_locator(
        page,
        MEDIA_BUTTON_SELECTORS,
        purpose="LinkedIn image/media button",
        timeout=IMAGE_ATTACH_TIMEOUT_MS,
    )
    if hasattr(page, "expect_file_chooser"):
        try:
            with page.expect_file_chooser(timeout=IMAGE_ATTACH_TIMEOUT_MS) as chooser_info:
                _click_locator(page, media_button, show_cursor=show_cursor)
            chooser_info.value.set_files(str(image_path))
            return {
                "method": "file_chooser",
                "media_selector": media_selector,
                "file_input_selector": None,
            }
        except PlaywrightError:
            pass

    file_input_selector, file_input = _first_attached_locator(
        page,
        MEDIA_FILE_INPUT_SELECTORS,
        purpose="LinkedIn image file input",
        timeout=IMAGE_ATTACH_TIMEOUT_MS,
    )
    file_input.set_input_files(str(image_path))
    return {
        "method": "file_input_after_media",
        "media_selector": media_selector,
        "file_input_selector": file_input_selector,
    }


def _paste_linkedin_image(
    page: Any,
    image_path: Path,
    *,
    show_cursor: bool = True,
) -> dict[str, Any]:
    try:
        _, editor = _first_visible_locator(
            page,
            COMPOSER_EDITOR_SELECTORS,
            purpose="LinkedIn post editor for image paste",
            timeout=IMAGE_ATTACH_TIMEOUT_MS,
        )
        _click_locator(page, editor, show_cursor=show_cursor)
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        pasted = bool(
            page.evaluate(
                """
                async ({ name, mimeType, imageB64 }) => {
                  const active = document.activeElement;
                  if (!active) return false;
                  const binary = atob(imageB64);
                  const bytes = new Uint8Array(binary.length);
                  for (let i = 0; i < binary.length; i += 1) {
                    bytes[i] = binary.charCodeAt(i);
                  }
                  const file = new File([bytes], name, { type: mimeType });
                  const dataTransfer = new DataTransfer();
                  dataTransfer.items.add(file);
                  const event = new ClipboardEvent("paste", {
                    bubbles: true,
                    cancelable: true,
                    clipboardData: dataTransfer,
                  });
                  return active.dispatchEvent(event);
                }
                """,
                {
                    "name": image_path.name,
                    "mimeType": mime_type,
                    "imageB64": image_b64,
                },
            )
        )
        return {
            "method": "paste",
            "pasted": pasted,
            "media_selector": None,
            "file_input_selector": None,
        }
    except Exception as exc:
        return {
            "method": "paste",
            "pasted": False,
            "error": str(exc),
        }


def _finalize_linkedin_media_review(
    page: Any,
    *,
    show_cursor: bool = True,
) -> dict[str, Any]:
    """Move LinkedIn from image preview/editing back to full post review."""
    try:
        selector, button = _first_visible_locator(
            page,
            MEDIA_FINALIZE_BUTTON_SELECTORS,
            purpose="LinkedIn media review confirmation button",
            timeout=IMAGE_ATTACH_TIMEOUT_MS,
        )
        _click_locator(page, button, show_cursor=show_cursor)
        try:
            page.wait_for_load_state("networkidle", timeout=IMAGE_ATTACH_TIMEOUT_MS)
        except PlaywrightError:
            pass
        _, post_review_ready = _wait_for_optional_visible(
            page,
            POST_BUTTON_SELECTORS,
            timeout=IMAGE_ATTACH_TIMEOUT_MS,
        )
        return {
            "finalized": True,
            "selector": selector,
            "post_review_ready": post_review_ready,
        }
    except LinkedInEditorBrowserError:
        _, post_review_ready = _wait_for_optional_visible(
            page,
            POST_BUTTON_SELECTORS,
            timeout=2_000,
        )
        if post_review_ready:
            return {
                "finalized": False,
                "selector": None,
                "post_review_ready": True,
            }
        raise LinkedInEditorBrowserError(
            "LinkedIn image preview is open, but no Next/Done/Add button was found "
            "and the full post review composer is not ready."
        )


def _try_set_linkedin_alt_text(
    page: Any,
    alt_text: str | None,
    *,
    show_cursor: bool = True,
) -> bool:
    if not alt_text:
        return False
    try:
        _, alt_button = _first_visible_locator(
            page,
            ALT_TEXT_BUTTON_SELECTORS,
            purpose="LinkedIn image alt text button",
            timeout=2_500,
        )
        _click_locator(page, alt_button, show_cursor=show_cursor)
        _, alt_input = _first_visible_locator(
            page,
            ALT_TEXT_INPUT_SELECTORS,
            purpose="LinkedIn image alt text input",
            timeout=2_500,
        )
        alt_input.fill(alt_text, timeout=DEFAULT_PLAYWRIGHT_TIMEOUT_MS)
        _, save_button = _first_visible_locator(
            page,
            ALT_TEXT_SAVE_SELECTORS,
            purpose="LinkedIn image alt text save button",
            timeout=2_500,
        )
        _click_locator(page, save_button, show_cursor=show_cursor)
        return True
    except (LinkedInEditorBrowserError, PlaywrightError):
        return False


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
    image_path: str | None = None,
    image_url: str | None = None,
    alt_text: str | None = None,
    auto_image: bool = True,
    require_image: bool = True,
    show_cursor: bool = True,
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

    draft_only_key = _prepared_draft_key(
        draft=draft,
        image_path=None,
        publish=publish,
    )
    if not publish and not image_path and not image_url and draft_only_key in _PREPARED_DRAFT_KEYS:
        return LinkedInEditorResult(
            status="draft_ready",
            message=(
                "This LinkedIn draft was already prepared in this process. "
                "Skipped reopening the browser for the duplicate request."
            ),
            draft=draft,
            url=LINKEDIN_FEED_URL,
        ).model_dump(exclude_none=True)

    image_preparation = None
    try:
        upload_image_path = resolve_linkedin_image_upload_path(
            image_path=image_path,
            image_url=image_url,
        )
    except Exception as exc:
        return LinkedInEditorResult(
            status="error",
            message=str(exc),
            draft=draft,
            url=LINKEDIN_FEED_URL,
        ).model_dump(exclude_none=True)

    if not upload_image_path and auto_image:
        upload_image_path, image_preparation = prepare_linkedin_editor_image(
            task=task,
            post_text=draft,
            alt_text=alt_text,
        )

    if require_image and not upload_image_path:
        message = "linkedin-editor could not prepare a local image_path for this post."
        if image_preparation and image_preparation.get("errors"):
            message += f" Errors: {' | '.join(image_preparation['errors'])}"
        return LinkedInEditorResult(
            status="error",
            message=message,
            draft=draft,
            url=LINKEDIN_FEED_URL,
        ).model_dump(exclude_none=True)

    draft_key = _prepared_draft_key(
        draft=draft,
        image_path=upload_image_path,
        publish=publish,
    )
    if draft_key in _PREPARED_DRAFT_KEYS:
        return LinkedInEditorResult(
            status="draft_ready",
            message=(
                "This LinkedIn draft was already prepared in this process. "
                "Skipped reopening the browser for the duplicate request."
            ),
            draft=draft,
            url=LINKEDIN_FEED_URL,
            image_path=upload_image_path,
        ).model_dump(exclude_none=True)

    try:
        browser_result = open_linkedin_composer(
            session_state_path,
            headless=headless,
            draft=draft,
            publish=publish,
            image_path=upload_image_path,
            alt_text=alt_text,
            show_cursor=show_cursor,
        )
    except (FileNotFoundError, LinkedInEditorBrowserError, PlaywrightError) as exc:
        record_linkedin_editor_memory(
            task=task,
            draft=draft,
            browser_result=None,
            status="error",
            message=str(exc),
            publish=publish,
            success=False,
            error=str(exc),
            image_path=upload_image_path,
            alt_text=alt_text,
            image_preparation=image_preparation,
        )
        return LinkedInEditorResult(
            status="error",
            message=str(exc),
            draft=draft,
            url=LINKEDIN_FEED_URL,
            image_path=upload_image_path,
        ).model_dump(exclude_none=True)

    publish_decision = publish_or_save_draft(
        draft,
        publish=publish,
        browser_result=browser_result,
    )
    record_linkedin_editor_memory(
        task=task,
        draft=draft,
        browser_result=browser_result,
        status=publish_decision["status"],
        message=publish_decision["message"],
        publish=publish,
        success=publish_decision["status"] in {"draft_ready", "needs_confirmation", "published"},
        image_path=upload_image_path,
        alt_text=alt_text,
        image_preparation=image_preparation,
    )
    if not publish and publish_decision["status"] == "draft_ready":
        _PREPARED_DRAFT_KEYS.add(draft_key)
        if not image_path and not image_url:
            _PREPARED_DRAFT_KEYS.add(draft_only_key)

    return LinkedInEditorResult(
        status=publish_decision["status"],
        message=publish_decision["message"],
        draft=draft,
        url=str(browser_result.get("url") or LINKEDIN_FEED_URL),
        image_path=upload_image_path,
    ).model_dump(exclude_none=True)


def _prepared_draft_key(
    *,
    draft: str,
    image_path: str | None,
    publish: bool,
) -> str:
    payload = f"{publish}\n{image_path or ''}\n{draft}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
