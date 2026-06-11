"""TODO management tools for Plan Master agents."""

from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from tools.state import PlanMasterState, Todo


WRITE_TODOS_DESCRIPTION = """Create or update the agent TODO list."""


@tool(description=WRITE_TODOS_DESCRIPTION)
def write_todos(
    todos: list[Todo],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Create or update the agent TODO list."""
    return Command(
        update={
            "todos": todos,
            "messages": [
                ToolMessage(f"Updated todo list to {todos}", tool_call_id=tool_call_id)
            ],
        }
    )


@tool
def read_todos(
    state: Annotated[PlanMasterState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> str:
    """Read the current TODO list from agent state."""
    todos = state.get("todos", [])
    if not todos:
        return "No todos currently in the list."

    result = ["Current TODO List:"]
    for index, todo in enumerate(todos, start=1):
        result.append(f"{index}. [{todo['status']}] {todo['content']}")

    return "\n".join(result)


__all__ = ["WRITE_TODOS_DESCRIPTION", "read_todos", "write_todos"]
