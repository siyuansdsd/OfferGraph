"""Prompt loading helpers for OfferGraph agents."""

from pathlib import Path
from string import Formatter
from typing import Any


PROMPT_DIR = Path(__file__).resolve().parent


def load_prompt(prompt_name: str) -> str:
    """Load a prompt file from the prompt directory."""
    prompt_path = PROMPT_DIR / prompt_name
    if prompt_path.suffix != ".md":
        prompt_path = prompt_path.with_suffix(".md")

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    return prompt_path.read_text(encoding="utf-8")


def required_prompt_variables(template: str) -> set[str]:
    """Return the format variables required by a prompt template."""
    variables: set[str] = set()
    formatter = Formatter()
    for _, field_name, _, _ in formatter.parse(template):
        if field_name:
            variables.add(field_name)

    return variables


def render_prompt(prompt_name: str, **values: Any) -> str:
    """Load and format a prompt template."""
    template = load_prompt(prompt_name)
    missing = required_prompt_variables(template) - values.keys()
    if missing:
        missing_values = ", ".join(sorted(missing))
        raise KeyError(f"Missing prompt variables: {missing_values}")

    return template.format(**values)


__all__ = [
    "PROMPT_DIR",
    "load_prompt",
    "render_prompt",
    "required_prompt_variables",
]
