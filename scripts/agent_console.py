"""Run an OfferGraph agent from a local console."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.agent.linkedin_master import (  # noqa: E402
    LinkedInMasterConfig,
    create_linkedin_master_agent,
)
from agent.agent.plan_master import PlanMasterConfig, create_plan_master_agent  # noqa: E402
from agent.model_selection import (  # noqa: E402
    DEFAULT_CONSOLE_MODEL_CHOICE,
    DEFAULT_MODEL_CHOICE,
    get_console_model_choice,
    list_console_model_choices,
    resolve_model_reference,
)


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


def build_agent(agent_name: str, model: Any, industry: str, extra_need: str) -> Any:
    """Build the selected agent."""
    if agent_name == "plan-master":
        return create_plan_master_agent(
            model=model,
            config=PlanMasterConfig(industry=industry, extra_need=extra_need),
        )

    return create_linkedin_master_agent(
        model=model,
        config=LinkedInMasterConfig(industry=industry, extra_need=extra_need),
    )


def main() -> int:
    """Run the selected agent and print the response."""
    args = parse_args()
    model_choice = choose_model(args.model)
    model = resolve_model_reference(model_choice)
    message = args.message or input("Message: ").strip()

    agent = build_agent(args.agent, model, args.industry, args.extra_need)
    result = agent.invoke({"messages": [{"role": "user", "content": message}]})
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
