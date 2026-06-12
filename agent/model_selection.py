"""Model selection helpers for OfferGraph consoles and agents."""

from __future__ import annotations

from typing import Any

from langchain_community.chat_models import MiniMaxChat

from config.env import get_env, load_project_env


MINIMAX_API_KEY_ENV = "MINIMAX_API_KEY"
CONSOLE_MODEL_ENV = "OFFERGRAPH_CONSOLE_MODEL"
DEFAULT_CONSOLE_MODEL_CHOICE = "MiniMax-M2.7"
DEFAULT_MODEL_CHOICE = "default"
MINIMAX_MODEL_CHOICES = {
    "MiniMax-M2.7": "MiniMax-M2.7",
    "MiniMax-M2.5": "MiniMax-M2.5",
}
CONSOLE_MODEL_CHOICES = (
    "MiniMax-M2.7",
    "MiniMax-M2.5",
    DEFAULT_MODEL_CHOICE,
)


def list_console_model_choices() -> tuple[str, ...]:
    """Return model choices exposed by the console."""
    return CONSOLE_MODEL_CHOICES


def get_console_model_choice(default: str = DEFAULT_CONSOLE_MODEL_CHOICE) -> str:
    """Return the preferred console model choice from `.env` or a default."""
    load_project_env()
    return get_env(CONSOLE_MODEL_ENV, default, load=False) or default


def get_minimax_key() -> str | None:
    """Return the MiniMax API key from the project environment."""
    load_project_env()
    return get_env(MINIMAX_API_KEY_ENV, load=False)


def create_minimax_model(choice: str) -> MiniMaxChat:
    """Create a MiniMax chat model for a supported console choice."""
    model_name = MINIMAX_MODEL_CHOICES.get(choice)
    if not model_name:
        supported = ", ".join(MINIMAX_MODEL_CHOICES)
        raise ValueError(f"Unsupported MiniMax model choice: {choice}. Use: {supported}")

    api_key = get_minimax_key()
    if not api_key:
        raise RuntimeError(
            "Missing MINIMAX_API_KEY. Add it to .env before using MiniMax."
        )

    return MiniMaxChat(api_key=api_key, model=model_name)


def resolve_model_reference(model: str | Any | None) -> str | Any | None:
    """Resolve supported display choices to model objects."""
    if not isinstance(model, str):
        return model

    if model == DEFAULT_MODEL_CHOICE:
        return None

    if model in MINIMAX_MODEL_CHOICES:
        return create_minimax_model(model)

    return model


__all__ = [
    "CONSOLE_MODEL_CHOICES",
    "CONSOLE_MODEL_ENV",
    "DEFAULT_CONSOLE_MODEL_CHOICE",
    "DEFAULT_MODEL_CHOICE",
    "MINIMAX_API_KEY_ENV",
    "MINIMAX_MODEL_CHOICES",
    "create_minimax_model",
    "get_console_model_choice",
    "get_minimax_key",
    "list_console_model_choices",
    "resolve_model_reference",
]
