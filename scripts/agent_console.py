"""Run an OfferGraph agent from a local console."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from rich.console import Console


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.agent.linkedin_master import (  # noqa: E402
    LinkedInMasterConfig,
    create_linkedin_master_agent,
)
from agent.agent.plan_master import PlanMasterConfig, create_plan_master_agent  # noqa: E402
from agent.execution_log import (  # noqa: E402
    ExecutionFrame,
    execution_events_from_chunk,
    print_execution_frame,
)
from agent.model_selection import (  # noqa: E402
    DEFAULT_CONSOLE_MODEL_CHOICE,
    DEFAULT_MODEL_CHOICE,
    get_console_model_choice,
    list_console_model_choices,
    resolve_model_reference,
)
from agent.mcp_clients import load_cv_tailoring_mcp_tools_sync  # noqa: E402


AGENT_CHOICES = ("linkedin-master", "plan-master")
TOP_LEVEL_AGENT = "plan-master"
DEFAULT_CV_TAILORING_TRANSPORT = "stdio"
CHAT_EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit", ":q"}


def parse_args() -> argparse.Namespace:
    """Parse console arguments."""
    parser = argparse.ArgumentParser(description="Run an OfferGraph agent locally.")
    parser.add_argument(
        "--agent",
        choices=AGENT_CHOICES,
        default=TOP_LEVEL_AGENT,
        help="Agent to run. Defaults to the top-level plan-master.",
    )
    parser.add_argument(
        "--model",
        choices=list_console_model_choices(),
        default=None,
        help=(
            "Model choice. Omit it to use the console default from env/config. "
            "Use 'default' to use the agent's configured default model."
        ),
    )
    parser.add_argument(
        "--choose-model",
        action="store_true",
        help="Prompt for model selection before starting.",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="User message. Omit it for an interactive prompt.",
    )
    parser.add_argument(
        "--industry",
        default="AI Engineer and Software Engineer",
        help="Industry context injected into the agent prompt.",
    )
    parser.add_argument(
        "--extra-need",
        default="Create a practical LinkedIn post for OfferGraph.",
        help="Additional content requirements injected into the agent prompt.",
    )
    parser.add_argument(
        "--with-cv-tailoring-mcp",
        action="store_true",
        help=(
            "Load CV Maker tools. This is automatic for plan-master; keep this "
            "flag for non-default agents or explicitness."
        ),
    )
    parser.add_argument(
        "--without-cv-tailoring-mcp",
        action="store_true",
        help="Do not load CV Maker tools.",
    )
    parser.add_argument(
        "--cv-tailoring-transport",
        choices=("stdio", "streamable_http", "streamable-http"),
        default=DEFAULT_CV_TAILORING_TRANSPORT,
        help="How to load CV Tailoring tools. Default stdio avoids a second terminal.",
    )
    return parser.parse_args()


def prompt_for_model_choice() -> str:
    """Ask the user to choose a supported model in the console."""
    choices = [choice for choice in list_console_model_choices() if choice != "default"]
    print("Select a model:")
    for index, choice in enumerate(choices, start=1):
        print(f"{index}. {choice}")
    print(f"{len(choices) + 1}. {DEFAULT_MODEL_CHOICE}")

    raw_choice = input(f"Model [1: {DEFAULT_CONSOLE_MODEL_CHOICE}]: ").strip()
    if not raw_choice:
        return DEFAULT_CONSOLE_MODEL_CHOICE

    if raw_choice.isdigit():
        index = int(raw_choice)
        indexed_choices = [*choices, DEFAULT_MODEL_CHOICE]
        if 1 <= index <= len(indexed_choices):
            return indexed_choices[index - 1]

    if raw_choice in list_console_model_choices():
        return raw_choice

    supported = ", ".join(list_console_model_choices())
    raise ValueError(f"Unsupported model choice: {raw_choice}. Use: {supported}")


def choose_model(args_model: str | None, *, prompt: bool = False) -> str:
    """Choose a console model from args, env, or interactive input."""
    if args_model:
        return args_model

    if prompt and sys.stdin.isatty():
        return prompt_for_model_choice()

    return get_console_model_choice()


def build_agent(
    agent_name: str,
    model: Any,
    industry: str,
    extra_need: str,
    *,
    extra_tools: list[Any] | None = None,
) -> Any:
    """Build the selected agent."""
    if agent_name == "plan-master":
        return create_plan_master_agent(
            model=model,
            config=PlanMasterConfig(industry=industry, extra_need=extra_need),
            extra_tools=extra_tools,
        )

    return create_linkedin_master_agent(
        model=model,
        config=LinkedInMasterConfig(industry=industry, extra_need=extra_need),
        extra_tools=extra_tools,
    )


def run_agent(
    agent: Any,
    agent_name: str,
    message: str,
    *,
    console: Console | None = None,
    messages: list[Any] | None = None,
) -> Any:
    """Run an agent and print formatted execution updates."""
    active_console = console or Console()
    payload = {"messages": messages or [{"role": "user", "content": message}]}
    print_execution_frame(
        active_console,
        ExecutionFrame(
            agent=agent_name,
            task=message,
            doing="starting",
            details="Agent run has started.",
            next_step="wait for the first agent step",
        ),
    )

    seen_keys: set[str] = set()
    final_result: Any = None
    if hasattr(agent, "stream"):
        try:
            stream = agent.stream(payload, stream_mode="updates")
        except TypeError:
            stream = agent.stream(payload)

        for chunk in stream:
            final_result = chunk
            for event in execution_events_from_chunk(
                chunk,
                default_agent=agent_name,
                task=message,
            ):
                if event.dedupe_key in seen_keys:
                    continue
                if event.dedupe_key:
                    seen_keys.add(event.dedupe_key)
                print_execution_frame(active_console, event.frame)
    else:
        final_result = agent.invoke(payload)
        for event in execution_events_from_chunk(
            final_result,
            default_agent=agent_name,
            task=message,
        ):
            print_execution_frame(active_console, event.frame)

    print_execution_frame(
        active_console,
        ExecutionFrame(
            agent=agent_name,
            task=message,
            doing="completed",
            details="Agent run finished.",
            next_step="review the output above",
        ),
    )
    return final_result


def chat_loop(
    agent: Any,
    agent_name: str,
    *,
    console: Console | None = None,
) -> None:
    """Run a lightweight multi-turn console loop."""
    active_console = console or Console()
    active_console.print(
        f"OfferGraph chat ready. Top agent: {agent_name}. Type /exit to quit."
    )
    history: list[Any] = []

    while True:
        try:
            message = input("OfferGraph> ").strip()
        except EOFError:
            active_console.print()
            return

        if not message:
            continue
        if message.lower() in CHAT_EXIT_COMMANDS:
            return

        history.append({"role": "user", "content": message})
        result = run_agent(
            agent,
            agent_name,
            message,
            console=active_console,
            messages=history,
        )
        assistant_text = extract_last_assistant_text(result)
        if assistant_text:
            history.append({"role": "assistant", "content": assistant_text})


def extract_last_assistant_text(value: Any) -> str:
    """Return the last assistant text from an agent result for REPL history."""
    assistant_messages = [
        message
        for message in iter_result_messages(value)
        if message_role(message) in {"ai", "assistant"}
        and message_content(message)
        and not message_tool_calls(message)
    ]
    if not assistant_messages:
        return ""
    return message_content(assistant_messages[-1])


def iter_result_messages(value: Any):
    """Yield message-like values from a nested agent result."""
    if is_message_like(value):
        yield value
        return

    if isinstance(value, dict):
        messages = value.get("messages")
        if is_message_like(messages):
            yield messages
        elif isinstance(messages, list):
            for message in messages:
                if is_message_like(message):
                    yield message

        for key, nested_value in value.items():
            if key == "messages":
                continue
            yield from iter_result_messages(nested_value)
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            yield from iter_result_messages(item)


def is_message_like(value: Any) -> bool:
    """Return whether a value looks like a LangChain or OpenAI-style message."""
    if isinstance(value, dict):
        return "content" in value and ("role" in value or "type" in value)
    return hasattr(value, "content") and (
        hasattr(value, "type") or value.__class__.__name__.endswith("Message")
    )


def message_role(message: Any) -> str:
    """Return a normalized message role/type."""
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or "").lower()
    return str(getattr(message, "type", "") or getattr(message, "role", "")).lower()


def message_content(message: Any) -> str:
    """Return message content as text."""
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content or "")


def message_tool_calls(message: Any) -> list[Any]:
    """Return tool calls on a message when present."""
    if isinstance(message, dict):
        return list(message.get("tool_calls") or [])
    return list(getattr(message, "tool_calls", None) or [])


def load_console_extra_tools(args: argparse.Namespace, console: Console) -> list[Any] | None:
    """Load optional tools for the selected console agent."""
    if getattr(args, "without_cv_tailoring_mcp", False):
        return None

    should_load_cv_tools = bool(getattr(args, "with_cv_tailoring_mcp", False)) or (
        getattr(args, "agent", TOP_LEVEL_AGENT) == TOP_LEVEL_AGENT
    )
    if not should_load_cv_tools:
        return None

    transport = getattr(args, "cv_tailoring_transport", DEFAULT_CV_TAILORING_TRANSPORT)
    try:
        return load_cv_tailoring_mcp_tools_sync(transport=transport)
    except Exception as exc:
        console.print(f"CV Tailoring MCP tools unavailable: {exc}")
        return None


def main() -> int:
    """Run the selected agent and print the response."""
    args = parse_args()
    console = Console()
    model_choice = choose_model(args.model, prompt=getattr(args, "choose_model", False))
    model = resolve_model_reference(model_choice)
    message = args.message
    extra_tools = load_console_extra_tools(args, console)
    agent = build_agent(
        args.agent,
        model,
        args.industry,
        args.extra_need,
        extra_tools=extra_tools,
    )
    if message:
        run_agent(agent, args.agent, message, console=console)
    else:
        chat_loop(agent, args.agent, console=console)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
