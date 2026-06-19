"""MCP client helpers for loading tools into OfferGraph agents."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from config.env import PROJECT_ROOT, get_env


CV_TAILORING_MCP_SERVER_NAME = "cv-tailoring"
CV_TAILORING_MCP_MODULE = "mcp_servers.cv_tailoring.server"
CV_TAILORING_MCP_URL_ENV = "CV_TAILORING_MCP_URL"
CV_TAILORING_MCP_CLIENT_TRANSPORT_ENV = "CV_TAILORING_MCP_CLIENT_TRANSPORT"
DEFAULT_CV_TAILORING_MCP_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_CV_TAILORING_MCP_CLIENT_TRANSPORT = "streamable_http"


def build_cv_tailoring_mcp_connection(
    *,
    transport: str | None = None,
    url: str | None = None,
    python_executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> dict[str, Any]:
    """Build the MCP connection for the separately running CV Maker service."""
    active_transport = (
        transport
        or get_env(
            CV_TAILORING_MCP_CLIENT_TRANSPORT_ENV,
            DEFAULT_CV_TAILORING_MCP_CLIENT_TRANSPORT,
        )
        or DEFAULT_CV_TAILORING_MCP_CLIENT_TRANSPORT
    )
    if active_transport in {"streamable-http", "streamable_http"}:
        return {
            "transport": "streamable_http",
            "url": url
            or get_env(CV_TAILORING_MCP_URL_ENV, DEFAULT_CV_TAILORING_MCP_URL)
            or DEFAULT_CV_TAILORING_MCP_URL,
        }
    if active_transport != "stdio":
        raise ValueError(
            "CV Tailoring MCP client transport must be streamable_http or stdio."
        )

    return {
        "transport": "stdio",
        "command": str(python_executable or sys.executable),
        "args": ["-m", CV_TAILORING_MCP_MODULE],
        "cwd": str(cwd or PROJECT_ROOT),
    }


def build_cv_tailoring_mcp_client(
    *,
    transport: str | None = None,
    url: str | None = None,
    python_executable: str | Path | None = None,
    tool_name_prefix: bool = False,
) -> MultiServerMCPClient:
    """Create an MCP client for the CV Maker service."""
    return MultiServerMCPClient(
        {
            CV_TAILORING_MCP_SERVER_NAME: build_cv_tailoring_mcp_connection(
                transport=transport,
                url=url,
                python_executable=python_executable,
            )
        },
        tool_name_prefix=tool_name_prefix,
    )


async def load_cv_tailoring_mcp_tools(
    *,
    transport: str | None = None,
    url: str | None = None,
    python_executable: str | Path | None = None,
    tool_name_prefix: bool = False,
) -> list[BaseTool]:
    """Load CV Maker MCP tools as LangChain tools."""
    client = build_cv_tailoring_mcp_client(
        transport=transport,
        url=url,
        python_executable=python_executable,
        tool_name_prefix=tool_name_prefix,
    )
    return await client.get_tools(server_name=CV_TAILORING_MCP_SERVER_NAME)


def load_cv_tailoring_mcp_tools_sync(
    *,
    transport: str | None = None,
    url: str | None = None,
    python_executable: str | Path | None = None,
    tool_name_prefix: bool = False,
) -> list[BaseTool]:
    """Synchronously load CV Maker MCP tools for console entrypoints."""
    return asyncio.run(
        load_cv_tailoring_mcp_tools(
            transport=transport,
            url=url,
            python_executable=python_executable,
            tool_name_prefix=tool_name_prefix,
        )
    )


__all__ = [
    "CV_TAILORING_MCP_MODULE",
    "CV_TAILORING_MCP_CLIENT_TRANSPORT_ENV",
    "CV_TAILORING_MCP_SERVER_NAME",
    "CV_TAILORING_MCP_URL_ENV",
    "DEFAULT_CV_TAILORING_MCP_URL",
    "build_cv_tailoring_mcp_client",
    "build_cv_tailoring_mcp_connection",
    "load_cv_tailoring_mcp_tools",
    "load_cv_tailoring_mcp_tools_sync",
]
