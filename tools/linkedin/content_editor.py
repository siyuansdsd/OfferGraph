"""LinkedIn content editor LangChain tool.

The tool contract is defined here, while browser automation and publishing are
intentionally left behind explicit implementation points.
"""

from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


DEFAULT_LINKEDIN_SESSION_STATE_PATH = ".auth/linkedin.json"


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


class LinkedInEditorResult(BaseModel):
    """Structured result returned by the linkedin-editor tool."""

    status: Literal[
        "planned",
        "draft_ready",
        "needs_confirmation",
        "published",
        "error",
    ]
    message: str
    draft: str | None = None
    url: str | None = None
    screenshot: str | None = None


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


@tool("linkedin-editor", args_schema=LinkedInEditorInput)
def linkedin_editor(
    task: str,
    additional_info: str | None = None,
    draft_only: bool = True,
    publish: bool = False,
    session_state_path: str = DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    headless: bool = False,
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

    if publish:
        status: Literal["needs_confirmation"] = "needs_confirmation"
        message = (
            "Publish mode was requested, but browser automation is not implemented yet. "
            "The next implementation step is to open LinkedIn with Playwright, draft the "
            "post, and click Post only after confirmation."
        )
    else:
        status = "planned"
        message = (
            "linkedin-editor is defined. Implementation points are ready for opening "
            "LinkedIn, composing the post, and inserting it as a draft."
        )

    return LinkedInEditorResult(
        status=status,
        message=message,
        url="https://www.linkedin.com/feed/",
    ).model_dump(exclude_none=True)
