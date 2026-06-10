"""LinkedIn content editor LangChain tool.

The tool contract is defined here, while browser automation and publishing are
intentionally left behind explicit implementation points.
"""

from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools.approval import (
    AUTO_MODE,
    ApprovalRequest,
    request_user_approval,
)


DEFAULT_LINKEDIN_SESSION_STATE_PATH = ".auth/linkedin.json"
LINKEDIN_AUTH_SETUP_COMMAND = "./.venv/bin/python scripts/setup_linkedin_auth.py"


class LinkedInEditorInput(BaseModel):
    """Input schema for the linkedin-editor tool."""

    task: str = Field(
        ...,
        description="The goal or brief for the LinkedIn post.",
    )
    additional_info: str | None = Field(
        default=None,
        description="Extra context, facts, links, audience, tone, or constraints.",
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


def open_linkedin_composer(
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    *,
    headless: bool = False,
) -> dict[str, Any]:
    """Open LinkedIn's post composer with Playwright."""
    raise NotImplementedError(
        "TODO: use Playwright to load the saved LinkedIn session and open the post composer."
    )


def compose_post(task: str, additional_info: str | None = None) -> str:
    """Write a LinkedIn post draft from the task and supporting information."""
    raise NotImplementedError(
        "TODO: connect this to the agent or model that drafts LinkedIn post content."
    )


def publish_or_save_draft(
    draft: str,
    *,
    publish: bool = False,
) -> dict[str, Any]:
    """Insert the draft into LinkedIn and optionally publish it."""
    raise NotImplementedError(
        "TODO: insert text into the composer and click Post only when publish=True."
    )


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
        return None

    return LinkedInEditorResult(
        status=decision.status,
        message=decision.message,
        url="https://www.linkedin.com/feed/",
        approval=decision.model_dump(),
    ).model_dump(exclude_none=True)


@tool("linkedin-editor", args_schema=LinkedInEditorInput)
def linkedin_editor(
    task: str,
    additional_info: str | None = None,
    draft_only: bool = True,
    publish: bool = False,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    """Prepare a LinkedIn post workflow and optionally publish after confirmation."""
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

    if publish:
        status: Literal["needs_confirmation"] = "needs_confirmation"
        message = (
            "Publish mode was requested, but browser automation is not implemented yet. "
            "The next implementation step is to open LinkedIn with Playwright, draft the "
            "post, and click Post only after confirmation."
        )
    else:
        status = "planned"
        mode_note = (
            f" {AUTO_MODE} bypassed the LinkedIn auth approval gate."
            if execution_mode == AUTO_MODE
            else ""
        )
        message = (
            "linkedin-editor is defined. Implementation points are ready for opening "
            f"LinkedIn, composing the post, and inserting it as a draft.{mode_note}"
        )

    return LinkedInEditorResult(
        status=status,
        message=message,
        url="https://www.linkedin.com/feed/",
    ).model_dump(exclude_none=True)
