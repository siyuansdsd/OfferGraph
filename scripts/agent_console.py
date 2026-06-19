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


def parse_args() -> argparse.Namespace:
    """Parse console arguments."""
    parser = argparse.ArgumentParser(description="Run an OfferGraph agent locally.")
    parser.add_argument(
        "--agent",
        choices=AGENT_CHOICES,
        default="linkedin-master",
        help="Agent to run.",
    )
    parser.add_argument(
        "--model",
        choices=list_console_model_choices(),
        default=None,
        help=(
            "Model choice. Omit it for an interactive prompt. Use 'default' to use "
            "the agent's configured default model."
        ),
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
        help="Load CV Maker tools from the separate CV Tailoring MCP service.",
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


def choose_model(args_model: str | None) -> str:
    """Choose a console model from args, env, or interactive input."""
    if args_model:
        return args_model

    if sys.stdin.isatty():
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
) -> Any:
    """Run an agent and print formatted execution updates."""
    active_console = console or Console()
    payload = {"messages": [{"role": "user", "content": message}]}
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


def main() -> int:
    """Run the selected agent and print the response."""
    args = parse_args()
    model_choice = choose_model(args.model)
    model = resolve_model_reference(model_choice)
    message = args.message or input("Message: ").strip()

    extra_tools = (
        load_cv_tailoring_mcp_tools_sync() if args.with_cv_tailoring_mcp else None
    )
    agent = build_agent(
        args.agent,
        model,
        args.industry,
        args.extra_need,
        extra_tools=extra_tools,
    )
    run_agent(agent, args.agent, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
