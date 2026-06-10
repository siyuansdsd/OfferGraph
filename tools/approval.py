"""Reusable approval gate for tool flows that need user consent."""

from __future__ import annotations

import os
from typing import Callable, Literal

from pydantic import BaseModel, Field


AUTO_MODE = "auto-mode"
APPROVE_MODE = "approve-mode"
TOOL_EXECUTION_MODE_ENV = "OFFERGRAPH_TOOL_MODE"
ToolExecutionMode = Literal["auto-mode", "approve-mode"]


class ApprovalRequest(BaseModel):
    """A tool action that may require user approval."""

    action: str = Field(..., description="Short stable action name.")
    reason: str = Field(..., description="Why the action is needed.")
    automated_flow: str = Field(
        ...,
        description="What the tool will do if the user approves automation.",
    )
    manual_steps: list[str] = Field(
        default_factory=list,
        description="How the user can complete the action manually.",
    )


class ApprovalDecision(BaseModel):
    """Decision returned by the approval gate."""

    status: Literal["approved", "needs_approval", "manual_required"]
    approved: bool
    mode: ToolExecutionMode
    action: str
    message: str
    reason: str
    automated_flow: str
    manual_steps: list[str]


def get_tool_execution_mode(mode: str | None = None) -> ToolExecutionMode:
    """Return the active tool execution mode."""
    raw_mode = (mode or os.getenv(TOOL_EXECUTION_MODE_ENV) or APPROVE_MODE).strip()
    if raw_mode not in (AUTO_MODE, APPROVE_MODE):
        raise ValueError(
            f"Invalid tool execution mode {raw_mode!r}. "
            f"Use {AUTO_MODE!r} or {APPROVE_MODE!r}."
        )

    return raw_mode  # type: ignore[return-value]


def request_user_approval(
    request: ApprovalRequest,
    *,
    mode: str | None = None,
    interactive: bool = False,
    input_func: Callable[[str], str] = input,
) -> ApprovalDecision:
    """Evaluate whether a sensitive tool flow may proceed."""
    active_mode = get_tool_execution_mode(mode)

    if active_mode == AUTO_MODE:
        return ApprovalDecision(
            status="approved",
            approved=True,
            mode=active_mode,
            action=request.action,
            message=f"Auto-mode approved action: {request.action}.",
            reason=request.reason,
            automated_flow=request.automated_flow,
            manual_steps=request.manual_steps,
        )

    if not interactive:
        return ApprovalDecision(
            status="needs_approval",
            approved=False,
            mode=active_mode,
            action=request.action,
            message=(
                f"Approval is required before running action {request.action!r}. "
                "Approve the automated flow or complete the manual steps."
            ),
            reason=request.reason,
            automated_flow=request.automated_flow,
            manual_steps=request.manual_steps,
        )

    prompt = (
        f"Allow action {request.action!r}?\n"
        f"Reason: {request.reason}\n"
        f"Automated flow: {request.automated_flow}\n"
        "Type 'yes' to allow, anything else to use the manual flow: "
    )
    answer = input_func(prompt).strip().lower()
    if answer in {"y", "yes"}:
        return ApprovalDecision(
            status="approved",
            approved=True,
            mode=active_mode,
            action=request.action,
            message=f"User approved action: {request.action}.",
            reason=request.reason,
            automated_flow=request.automated_flow,
            manual_steps=request.manual_steps,
        )

    return ApprovalDecision(
        status="manual_required",
        approved=False,
        mode=active_mode,
        action=request.action,
        message=f"User did not approve action: {request.action}.",
        reason=request.reason,
        automated_flow=request.automated_flow,
        manual_steps=request.manual_steps,
    )


__all__ = [
    "APPROVE_MODE",
    "AUTO_MODE",
    "ApprovalDecision",
    "ApprovalRequest",
    "TOOL_EXECUTION_MODE_ENV",
    "ToolExecutionMode",
    "get_tool_execution_mode",
    "request_user_approval",
]
