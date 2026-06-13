"""Tests for formatted agent execution logging."""

from io import StringIO
from types import SimpleNamespace
from unittest import TestCase

from rich.console import Console

from agent.execution_log import (
    ExecutionFrame,
    agent_color,
    execution_events_from_chunk,
    print_execution_frame,
    summarize_value,
)


class ExecutionLogTest(TestCase):
    def test_agent_color_uses_stable_agent_palette(self) -> None:
        self.assertEqual(agent_color("plan-master"), "cyan")
        self.assertEqual(agent_color("linkedin-master"), "magenta")
        self.assertEqual(agent_color("research-agent"), "green")
        self.assertEqual(agent_color("tool:ls"), "yellow")

    def test_print_execution_frame_uses_requested_shape(self) -> None:
        output = StringIO()
        console = Console(file=output, force_terminal=False, color_system=None, width=120)

        print_execution_frame(
            console,
            ExecutionFrame(
                agent="plan-master",
                task="Create a LinkedIn post",
                doing="calling tool",
                details="Used tavily_search",
                next_step="read tool result",
            ),
        )

        text = output.getvalue()
        self.assertIn("====", text)
        self.assertIn("agent: plan-master", text)
        self.assertIn("task: Create a LinkedIn post", text)
        self.assertIn("doing: calling tool", text)
        self.assertIn("details: Used tavily_search", text)
        self.assertIn("next: read tool result", text)

    def test_execution_events_from_tool_call_chunk(self) -> None:
        message = SimpleNamespace(
            type="ai",
            name="plan-master",
            content="",
            tool_calls=[
                {
                    "name": "task",
                    "args": {"description": "Draft a LinkedIn post for OfferGraph"},
                    "id": "call-1",
                }
            ],
            invalid_tool_calls=[],
            response_metadata={},
            id="message-1",
        )

        events = execution_events_from_chunk(
            {"plan-master": {"messages": [message]}},
            default_agent="plan-master",
            task="Top-level request",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].dedupe_key, "message:message-1")
        self.assertEqual(events[0].frame.agent, "plan-master")
        self.assertEqual(events[0].frame.doing, "delegating task")
        self.assertIn("Draft a LinkedIn post", events[0].frame.task)
        self.assertIn("run tool(s): task", events[0].frame.next_step)

    def test_execution_events_from_invalid_tool_call_chunk(self) -> None:
        message = SimpleNamespace(
            type="ai",
            name="plan-master",
            content="",
            tool_calls=[],
            invalid_tool_calls=[{"name": "task", "args": '{"description": "cut'}],
            response_metadata={"finish_reason": "length"},
            id="message-2",
        )

        events = execution_events_from_chunk(
            {"messages": [message]},
            default_agent="plan-master",
            task="Top-level request",
        )

        self.assertEqual(events[0].frame.doing, "tool call parsing issue")
        self.assertIn("finish_reason=length", events[0].frame.details)
        self.assertIn("tool schema", events[0].frame.next_step)

    def test_execution_events_from_tool_result_chunk(self) -> None:
        message = SimpleNamespace(
            type="tool",
            name="tavily_search",
            content="Found one search result.",
            id="tool-message-1",
        )

        events = execution_events_from_chunk(
            {"tools": {"messages": [message]}},
            default_agent="plan-master",
            task="Research news",
        )

        self.assertEqual(events[0].frame.agent, "tool:tavily_search")
        self.assertEqual(events[0].frame.doing, "received tool result")
        self.assertIn("Found one search result", events[0].frame.details)

    def test_summarize_value_truncates_long_details(self) -> None:
        summary = summarize_value("x" * 20, limit=10)

        self.assertEqual(summary, "xxxxxxx...")
