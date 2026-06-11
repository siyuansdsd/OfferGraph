"""Virtual file-system tools for agent context offloading."""

from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from tools.state import PlanMasterState


LS_DESCRIPTION = """List all files in the virtual filesystem stored in agent state."""

READ_FILE_DESCRIPTION = """Read content from a virtual file with optional pagination."""

WRITE_FILE_DESCRIPTION = """Create or overwrite a file in the virtual filesystem."""


@tool(description=LS_DESCRIPTION)
def ls(state: Annotated[PlanMasterState, InjectedState]) -> list[str]:
    """List files in the virtual filesystem."""
    return sorted(state.get("files", {}).keys())


@tool(description=READ_FILE_DESCRIPTION)
def read_file(
    file_path: str,
    state: Annotated[PlanMasterState, InjectedState],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Read file content from the virtual filesystem."""
    files = state.get("files", {})
    if file_path not in files:
        return f"Error: File '{file_path}' not found"

    content = files[file_path]
    if not content:
        return "System reminder: File exists but has empty contents"

    lines = content.splitlines()
    if offset >= len(lines):
        return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"

    end_idx = min(offset + limit, len(lines))
    result_lines = []
    for index in range(offset, end_idx):
        line_content = lines[index][:2000]
        result_lines.append(f"{index + 1:6d}\t{line_content}")

    return "\n".join(result_lines)


@tool(description=WRITE_FILE_DESCRIPTION)
def write_file(
    file_path: str,
    content: str,
    state: Annotated[PlanMasterState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Write content to a file in the virtual filesystem."""
    files = dict(state.get("files", {}))
    files[file_path] = content
    return Command(
        update={
            "files": files,
            "messages": [
                ToolMessage(f"Updated file {file_path}", tool_call_id=tool_call_id)
            ],
        }
    )


__all__ = [
    "LS_DESCRIPTION",
    "READ_FILE_DESCRIPTION",
    "WRITE_FILE_DESCRIPTION",
    "ls",
    "read_file",
    "write_file",
]
