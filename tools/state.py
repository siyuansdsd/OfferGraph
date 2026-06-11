"""State types shared by OfferGraph deep-agent tools."""

from typing import Annotated, Literal, NotRequired
from typing_extensions import TypedDict

from langchain.agents import AgentState


class Todo(TypedDict):
    """A structured task item."""

    content: str
    status: Literal["pending", "in_progress", "completed"]


def file_reducer(
    left: dict[str, str] | None,
    right: dict[str, str] | None,
) -> dict[str, str] | None:
    """Merge file dictionaries, with right-side values taking precedence."""
    if left is None:
        return right
    if right is None:
        return left

    return {**left, **right}


class PlanMasterState(AgentState):
    """Agent state with TODO tracking and a virtual file system."""

    todos: NotRequired[list[Todo]]
    files: Annotated[NotRequired[dict[str, str]], file_reducer]


__all__ = ["PlanMasterState", "Todo", "file_reducer"]
