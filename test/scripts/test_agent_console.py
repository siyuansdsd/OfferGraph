"""Tests for the agent console script."""

from io import StringIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from rich.console import Console

from scripts.agent_console import (
    DEFAULT_CONSOLE_MODEL_CHOICE,
    TOP_LEVEL_AGENT,
    build_agent,
    chat_loop,
    choose_model,
    main,
    parse_args,
    prompt_for_model_choice,
    run_agent,
)


class AgentConsoleTest(TestCase):
    def test_choose_model_uses_argument(self) -> None:
        self.assertEqual(choose_model("MiniMax-M2.5"), "MiniMax-M2.5")

    def test_choose_model_uses_env_default_when_non_interactive(self) -> None:
        with patch("scripts.agent_console.sys.stdin.isatty", return_value=True), patch(
            "scripts.agent_console.get_console_model_choice",
            return_value="MiniMax-M2.5",
        ):
            self.assertEqual(choose_model(None), "MiniMax-M2.5")

    def test_choose_model_can_prompt_when_requested(self) -> None:
        with patch("scripts.agent_console.sys.stdin.isatty", return_value=True), patch(
            "scripts.agent_console.prompt_for_model_choice",
            return_value="MiniMax-M2.7",
        ):
            self.assertEqual(choose_model(None, prompt=True), "MiniMax-M2.7")

    def test_parse_args_defaults_to_top_level_agent(self) -> None:
        with patch("scripts.agent_console.sys.argv", ["agent_console.py"]):
            args = parse_args()

        self.assertEqual(args.agent, TOP_LEVEL_AGENT)
        self.assertIsNone(args.message)
        self.assertEqual(args.cv_tailoring_transport, "stdio")

    def test_prompt_for_model_choice_defaults_to_m27(self) -> None:
        with patch("builtins.input", return_value=""), patch("builtins.print"):
            self.assertEqual(prompt_for_model_choice(), DEFAULT_CONSOLE_MODEL_CHOICE)

    def test_prompt_for_model_choice_accepts_index(self) -> None:
        with patch("builtins.input", return_value="2"), patch("builtins.print"):
            self.assertEqual(prompt_for_model_choice(), "MiniMax-M2.5")

    def test_build_agent_passes_extra_tools_to_plan_master(self) -> None:
        extra_tool = object()

        with patch("scripts.agent_console.create_plan_master_agent") as create_mock:
            build_agent(
                "plan-master",
                "test:model",
                "AI",
                "Need",
                extra_tools=[extra_tool],
            )

        _, kwargs = create_mock.call_args
        self.assertEqual(kwargs["extra_tools"], [extra_tool])

    def test_main_loads_cv_tailoring_mcp_tools_when_enabled(self) -> None:
        fake_agent = object()
        fake_tool = object()

        with patch(
            "scripts.agent_console.parse_args",
            return_value=SimpleNamespace(
                agent="linkedin-master",
                model="default",
                message="Tailor my CV",
                industry="AI",
                extra_need="Need",
                choose_model=False,
                with_cv_tailoring_mcp=True,
                without_cv_tailoring_mcp=False,
                cv_tailoring_transport="stdio",
            ),
        ), patch(
            "scripts.agent_console.resolve_model_reference",
            return_value="test:model",
        ), patch(
            "scripts.agent_console.load_cv_tailoring_mcp_tools_sync",
            return_value=[fake_tool],
        ) as load_tools, patch(
            "scripts.agent_console.build_agent",
            return_value=fake_agent,
        ) as build_mock, patch(
            "scripts.agent_console.run_agent",
            return_value={},
        ):
            self.assertEqual(main(), 0)

        load_tools.assert_called_once_with(transport="stdio")
        build_mock.assert_called_once_with(
            "linkedin-master",
            "test:model",
            "AI",
            "Need",
            extra_tools=[fake_tool],
        )

    def test_main_enters_chat_loop_for_default_top_agent(self) -> None:
        fake_agent = object()

        with patch(
            "scripts.agent_console.parse_args",
            return_value=SimpleNamespace(
                agent="plan-master",
                model="default",
                message=None,
                industry="AI",
                extra_need="Need",
                choose_model=False,
                with_cv_tailoring_mcp=False,
                without_cv_tailoring_mcp=False,
                cv_tailoring_transport="stdio",
            ),
        ), patch(
            "scripts.agent_console.resolve_model_reference",
            return_value="test:model",
        ), patch(
            "scripts.agent_console.load_cv_tailoring_mcp_tools_sync",
            return_value=[],
        ) as load_tools, patch(
            "scripts.agent_console.build_agent",
            return_value=fake_agent,
        ), patch(
            "scripts.agent_console.chat_loop",
        ) as chat_mock:
            self.assertEqual(main(), 0)

        load_tools.assert_not_called()
        chat_mock.assert_called_once()

    def test_run_agent_streams_formatted_updates(self) -> None:
        class FakeAgent:
            def __init__(self) -> None:
                self.stream_args = None

            def stream(self, payload, stream_mode=None):
                self.stream_args = (payload, stream_mode)
                message = SimpleNamespace(
                    type="ai",
                    name="plan-master",
                    content="Working on it.",
                    tool_calls=[],
                    invalid_tool_calls=[],
                    response_metadata={"finish_reason": "stop"},
                    id="message-1",
                )
                return iter([{"messages": [message]}])

        output = StringIO()
        console = Console(file=output, force_terminal=False, color_system=None, width=120)
        agent = FakeAgent()

        result = run_agent(
            agent,
            "plan-master",
            "Create a LinkedIn post",
            console=console,
        )

        self.assertEqual(
            agent.stream_args,
            (
                {"messages": [{"role": "user", "content": "Create a LinkedIn post"}]},
                "updates",
            ),
        )
        self.assertEqual(result["messages"][0].content, "Working on it.")
        text = output.getvalue()
        self.assertIn("agent: plan-master", text)
        self.assertIn("doing: starting", text)
        self.assertIn("details: Working on it.", text)
        self.assertIn("doing: completed", text)

    def test_run_agent_prefers_async_stream_when_available(self) -> None:
        class FakeAgent:
            def __init__(self) -> None:
                self.astream_args = None
                self.stream_called = False

            async def astream(self, payload, stream_mode=None):
                self.astream_args = (payload, stream_mode)
                message = SimpleNamespace(
                    type="ai",
                    name="plan-master",
                    content="Async done.",
                    tool_calls=[],
                    invalid_tool_calls=[],
                    response_metadata={"finish_reason": "stop"},
                    id="message-async",
                )
                yield {"messages": [message]}

            def stream(self, payload, stream_mode=None):
                self.stream_called = True
                return iter([])

        output = StringIO()
        console = Console(file=output, force_terminal=False, color_system=None, width=120)
        agent = FakeAgent()

        result = run_agent(
            agent,
            "plan-master",
            "Tailor my CV",
            console=console,
        )

        self.assertEqual(
            agent.astream_args,
            (
                {"messages": [{"role": "user", "content": "Tailor my CV"}]},
                "updates",
            ),
        )
        self.assertFalse(agent.stream_called)
        self.assertEqual(result["messages"][0].content, "Async done.")
        self.assertIn("details: Async done.", output.getvalue())

    def test_chat_loop_runs_until_exit(self) -> None:
        class FakeAgent:
            def stream(self, payload, stream_mode=None):
                message = SimpleNamespace(
                    type="ai",
                    name="plan-master",
                    content="Done.",
                    tool_calls=[],
                    invalid_tool_calls=[],
                    response_metadata={"finish_reason": "stop"},
                    id="message-2",
                )
                return iter([{"messages": [message]}])

        output = StringIO()
        console = Console(file=output, force_terminal=False, color_system=None, width=120)

        with patch("builtins.input", side_effect=["hello", "/exit"]):
            chat_loop(FakeAgent(), "plan-master", console=console)

        text = output.getvalue()
        self.assertIn("OfferGraph chat ready", text)
        self.assertIn("details: Done.", text)
