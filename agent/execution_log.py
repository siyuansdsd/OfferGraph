"""Formatted execution logging for local agent runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from rich.console import Console
from rich.text import Text


DEFAULT_DETAIL_LIMIT = 700
DEFAULT_TASK_LIMIT = 320
SEPARATOR_WIDTH = 72
AGENT_COLORS = {
    "plan-master": "cyan",
    "linkedin-master": "magenta",
    "research-agent": "green",
    "tool": "yellow",
    "unknown": "white",
}


@dataclass(frozen=True)
class ExecutionFrame:
    """One console status frame for an agent run."""

    agent: str
    task: str
    doing: str
    details: str
    next_step: str


@dataclass(frozen=True)
class ExecutionEvent:
    """A rendered status frame plus an optional dedupe key."""

    frame: ExecutionFrame
    dedupe_key: str | None = None


def summarize_value(value: Any, limit: int = DEFAULT_DETAIL_LIMIT) -> str:
    """Return a single-line summary suitable for console status output."""
    if value is None:
        return "-"
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)

    text = " ".join(text.split())
    if len(text) <= limit:
        return text or "-"
    return f"{text[: limit - 3]}..."


def agent_color(agent: str) -> str:
    """Return a stable rich color name for an agent or tool."""
    normalized = agent.lower()
    for name, color in AGENT_COLORS.items():
        if normalized.startswith(name):
            return color
    return AGENT_COLORS["unknown"]


def print_execution_frame(console: Console, frame: ExecutionFrame) -> None:
    """Print one execution frame with agent-specific coloring."""
    color = agent_color(frame.agent)
    console.print("=" * SEPARATOR_WIDTH, style=color)
    _print_field(console, "agent", frame.agent, color)
    _print_field(console, "task", summarize_value(frame.task, DEFAULT_TASK_LIMIT), color)
    _print_field(console, "doing", frame.doing, color)
    _print_field(console, "details", frame.details, color)
    _print_field(console, "next", frame.next_step, color)


def _print_field(console: Console, label: str, value: str, color: str) -> None:
    text = Text()
    text.append(f"{label}: ", style=f"bold {color}")
    text.append(value or "-")
    console.print(text)


def execution_events_from_chunk(
    chunk: Any,
    *,
    default_agent: str,
    task: str,
) -> list[ExecutionEvent]:
    """Build formatted execution events from a LangGraph stream chunk."""
    messages = list(_iter_messages(chunk))
    if messages:
        return [
            ExecutionEvent(
                frame=_frame_from_message(message, default_agent=default_agent, task=task),
                dedupe_key=_message_dedupe_key(message),
            )
            for message in messages
        ]

    return [
        ExecutionEvent(
            frame=ExecutionFrame(
                agent=default_agent,
                task=task,
                doing="state update",
                details=summarize_value(chunk),
                next_step="continue running the agent",
            ),
            dedupe_key=f"chunk:{summarize_value(chunk, 240)}",
        )
    ]


def _iter_messages(value: Any) -> Iterable[Any]:
    if _is_message_like(value):
        yield value
        return

    if isinstance(value, dict):
        messages = value.get("messages")
        if _is_message_like(messages):
            yield messages
        elif isinstance(messages, list):
            for message in messages:
                if _is_message_like(message):
                    yield message

        for key, nested_value in value.items():
            if key == "messages":
                continue
            yield from _iter_messages(nested_value)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_messages(item)


def _is_message_like(value: Any) -> bool:
    return hasattr(value, "content") and (
        hasattr(value, "type") or value.__class__.__name__.endswith("Message")
    )


def _frame_from_message(message: Any, *, default_agent: str, task: str) -> ExecutionFrame:
    message_type = str(getattr(message, "type", "")).lower()
    class_name = message.__class__.__name__.lower()
    content = getattr(message, "content", None)

    if message_type == "tool" or "toolmessage" in class_name:
        tool_name = getattr(message, "name", None) or "tool"
        return ExecutionFrame(
            agent=f"tool:{tool_name}",
            task=task,
            doing="received tool result",
            details=summarize_value(content),
            next_step="return the result to the active agent",
        )

    agent = getattr(message, "name", None) or default_agent
    invalid_tool_calls = list(getattr(message, "invalid_tool_calls", None) or [])
    if invalid_tool_calls:
        finish_reason = _finish_reason(message)
        details = summarize_value(_describe_tool_calls(invalid_tool_calls))
        if finish_reason:
            details = f"{details} finish_reason={finish_reason}"
        return ExecutionFrame(
            agent=agent,
            task=task,
            doing="tool call parsing issue",
            details=details,
            next_step="check output length, tool schema, or prompt drift before retrying",
        )

    tool_calls = list(getattr(message, "tool_calls", None) or [])
    if tool_calls:
        assigned_task = _task_from_tool_calls(tool_calls) or task
        tool_names = ", ".join(_tool_call_name(call) for call in tool_calls)
        return ExecutionFrame(
            agent=agent,
            task=assigned_task,
            doing=_doing_for_tool_calls(tool_calls),
            details=summarize_value(_describe_tool_calls(tool_calls)),
            next_step=f"run tool(s): {tool_names}",
        )

    return ExecutionFrame(
        agent=agent,
        task=task,
        doing="reasoning or responding",
        details=summarize_value(content),
        next_step=_next_step_from_finish_reason(_finish_reason(message)),
    )


def _message_dedupe_key(message: Any) -> str:
    message_id = getattr(message, "id", None)
    if message_id:
        return f"message:{message_id}"
    return (
        f"message:{getattr(message, 'type', message.__class__.__name__)}:"
        f"{summarize_value(getattr(message, 'content', None), 160)}:"
        f"{summarize_value(getattr(message, 'tool_calls', None), 160)}"
    )


def _tool_call_name(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("name") or call.get("function", {}).get("name") or "tool")
    return str(getattr(call, "name", None) or "tool")


def _tool_call_args(call: Any) -> Any:
    if isinstance(call, dict):
        if "args" in call:
            return call["args"]
        function = call.get("function")
        if isinstance(function, dict):
            return function.get("arguments")
        return None
    return getattr(call, "args", None)


def _describe_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "tool": _tool_call_name(call),
            "args": _tool_call_args(call),
        }
        for call in tool_calls
    ]


def _task_from_tool_calls(tool_calls: list[Any]) -> str | None:
    for call in tool_calls:
        if _tool_call_name(call) != "task":
            continue
        args = _tool_call_args(call)
        if isinstance(args, dict) and args.get("description"):
            return summarize_value(args["description"], DEFAULT_TASK_LIMIT)
    return None


def _doing_for_tool_calls(tool_calls: list[Any]) -> str:
    if any(_tool_call_name(call) == "task" for call in tool_calls):
        return "delegating task"
    return "calling tool"


def _finish_reason(message: Any) -> str | None:
    metadata = getattr(message, "response_metadata", None) or {}
    if isinstance(metadata, dict):
        reason = metadata.get("finish_reason")
        return str(reason) if reason else None
    return None


def _next_step_from_finish_reason(finish_reason: str | None) -> str:
    if finish_reason == "length":
        return "increase output tokens or shorten the task before retrying"
    if finish_reason in {"stop", "end_turn"}:
        return "review the final response"
    return "continue until the task is complete"


__all__ = [
    "AGENT_COLORS",
    "ExecutionEvent",
    "ExecutionFrame",
    "agent_color",
    "execution_events_from_chunk",
    "print_execution_frame",
    "summarize_value",
]
