"""Tests for OfferGraph MCP client helpers."""

import asyncio
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

from agent import mcp_clients
from config.env import PROJECT_ROOT


class MCPClientsTest(TestCase):
    def test_build_cv_tailoring_connection_defaults_to_http_service(self) -> None:
        connection = mcp_clients.build_cv_tailoring_mcp_connection(
            url="http://127.0.0.1:8765/mcp",
        )

        self.assertEqual(connection["transport"], "streamable_http")
        self.assertEqual(connection["url"], "http://127.0.0.1:8765/mcp")

    def test_build_cv_tailoring_connection_can_use_stdio_server_process(self) -> None:
        connection = mcp_clients.build_cv_tailoring_mcp_connection(
            transport="stdio",
            python_executable="/tmp/python",
            cwd="/tmp/project",
        )

        self.assertEqual(connection["transport"], "stdio")
        self.assertEqual(connection["command"], "/tmp/python")
        self.assertEqual(
            connection["args"],
            ["-m", "mcp_servers.cv_tailoring.server"],
        )
        self.assertEqual(connection["cwd"], "/tmp/project")

    def test_build_cv_tailoring_stdio_connection_defaults_to_offergraph_root(self) -> None:
        connection = mcp_clients.build_cv_tailoring_mcp_connection(transport="stdio")

        self.assertEqual(connection["cwd"], str(PROJECT_ROOT))
        self.assertIn("python", Path(connection["command"]).name)

    def test_load_cv_tailoring_tools_uses_named_mcp_server(self) -> None:
        fake_tools = [object()]
        fake_client = AsyncMock()
        fake_client.get_tools.return_value = fake_tools

        with patch(
            "agent.mcp_clients.build_cv_tailoring_mcp_client",
            return_value=fake_client,
        ) as client_factory:
            tools = asyncio.run(mcp_clients.load_cv_tailoring_mcp_tools())

        self.assertEqual(tools, fake_tools)
        client_factory.assert_called_once_with(
            transport=None,
            url=None,
            python_executable=None,
            tool_name_prefix=False,
        )
        fake_client.get_tools.assert_awaited_once_with(server_name="cv-tailoring")
