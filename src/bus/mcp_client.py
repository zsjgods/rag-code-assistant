"""MCP Client — connects to external MCP servers via stdio JSON-RPC.

Each MCP server runs as a subprocess. The client communicates via stdin/stdout
using the JSON-RPC 2.0 protocol. Tool definitions are fetched from the server
and converted to agent-core Tool dataclass instances for registration.

Protocol flow:
  1. Launch server process
  2. initialize → capabilities negotiation
  3. tools/list → get tool definitions
  4. tools/call → execute a tool (forwarded as RPC)
  5. On shutdown: exit notification + terminate process

MCP Server config format (in settings.json):
  {
    "mcp_servers": {
      "brave-search": {
        "command": "node",
        "args": ["brave-search/dist/index.js"],
        "env": {"BRAVE_API_KEY": "xxx"}
      }
    }
  }
"""

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any

from src.tools.base import Tool, build_tool

WORKDIR = Path.cwd()


class MCPServerError(Exception):
    """Raised when an MCP server operation fails."""
    pass


class MCPServerConnection:
    """A single MCP server connection over stdio.

    Launches the server process, handles JSON-RPC lifecycle,
    and provides tool listing + execution.
    """

    def __init__(self, name: str, command: str, args: list[str] = None,
                 env: dict[str, str] = None, timeout: int = 30):
        self.name = name
        self.command = command
        self.args = args or []
        self.extra_env = env or {}
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._tools: list[dict] = []

    # ── Lifecycle ──────────────────────────────────────────

    def start(self):
        """Launch the server process and initialize the MCP connection."""
        env = os.environ.copy()
        env.update(self.extra_env)

        try:
            self._process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=WORKDIR,
                env=env,
            )
        except FileNotFoundError as e:
            raise MCPServerError(f"Failed to start MCP server '{self.name}': {e}. "
                                 f"Make sure '{self.command}' is installed.") from e

        # Initialize
        result = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent-core", "version": "2.0"},
        })
        if not result:
            raise MCPServerError(f"MCP server '{self.name}' initialize failed")

        # Send initialized notification
        self._notify("notifications/initialized", {})

        # Fetch tools
        self._tools = self._request("tools/list", {}) or []
        if isinstance(self._tools, dict):
            # MCP returns {"tools": [...]}
            self._tools = self._tools.get("tools", [])

    def stop(self):
        """Send exit notification and terminate the server process."""
        if self._process and self._process.poll() is None:
            try:
                self._notify("exit", {})
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    # ── JSON-RPC ──────────────────────────────────────────

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _send(self, payload: dict):
        """Send a JSON-RPC message to the server."""
        if not self._process or self._process.poll() is not None:
            raise MCPServerError(f"MCP server '{self.name}' is not running")
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            self._process.stdin.write(line)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise MCPServerError(f"MCP server '{self.name}' write failed: {e}") from e

    def _recv(self) -> dict | None:
        """Read a JSON-RPC response from the server."""
        if not self._process or self._process.poll() is not None:
            return None
        try:
            line = self._process.stdout.readline()
            if not line:
                return None
            return json.loads(line)
        except (json.JSONDecodeError, OSError):
            return None

    def _request(self, method: str, params: dict) -> Any:
        """Send a JSON-RPC request and return the result."""
        with self._lock:
            req_id = self._next_id()
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._send(payload)

            while True:
                resp = self._recv()
                if resp is None:
                    raise MCPServerError(
                        f"MCP server '{self.name}' disconnected during {method}")
                if resp.get("id") == req_id:
                    if "error" in resp:
                        err = resp["error"]
                        raise MCPServerError(
                            f"MCP server '{self.name}' error: {err.get('message', err)}")
                    return resp.get("result")

    def _notify(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send(payload)

    # ── Tool interface ────────────────────────────────────

    @property
    def tool_definitions(self) -> list[dict]:
        """Return raw MCP tool definitions."""
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool on the MCP server. Returns the result as a string."""
        result = self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        # MCP returns content as a list of content blocks
        if isinstance(result, dict):
            content = result.get("content", [result])
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(block.get("text", json.dumps(block, ensure_ascii=False)))
                    else:
                        parts.append(str(block))
                return "\n".join(parts)
            return str(content)
        return str(result)


class MCPClientManager:
    """Manages multiple MCP server connections and registers their tools.

    Usage:
        manager = MCPClientManager()
        manager.add_server("search", "node", ["brave-search/dist/index.js"],
                          env={"BRAVE_API_KEY": "xxx"})
        manager.start_all()
        manager.register_tools(registry)  # registers into ToolRegistry
    """

    def __init__(self):
        self._servers: dict[str, MCPServerConnection] = {}
        self._tool_registry: dict[str, MCPServerConnection] = {}  # tool_name → server

    def add_server(self, name: str, command: str, args: list[str] = None,
                   env: dict[str, str] = None):
        """Add a server configuration. Does not start it yet."""
        self._servers[name] = MCPServerConnection(name, command, args, env)

    def start_all(self) -> list[str]:
        """Start all configured servers. Returns list of errors (empty = all good)."""
        errors = []
        for name, server in self._servers.items():
            try:
                server.start()
                print(f"  [mcp] {name}: connected ({len(server.tool_definitions)} tools)")
            except MCPServerError as e:
                errors.append(str(e))
                print(f"  [mcp] {name}: ERROR — {e}")
        return errors

    def stop_all(self):
        """Stop all running servers."""
        for server in self._servers.values():
            server.stop()

    def get_all_tools(self) -> dict[str, list[dict]]:
        """Return {server_name: [tool_defs]} for all connected servers."""
        return {
            name: server.tool_definitions
            for name, server in self._servers.items()
            if server.is_running
        }

    def register_tools(self, registry) -> list[str]:
        """Register all MCP tools into a ToolRegistry.

        Each MCP tool gets a handler that forwards calls to the MCP server.
        Tool names are prefixed with the server name to avoid collisions:
          brave-search.search → brave_search

        Returns list of registered tool names.
        """
        registered = []
        for server_name, server in self._servers.items():
            if not server.is_running:
                continue
            for tool_def in server.tool_definitions:
                mcp_tool_name = tool_def.get("name", "unknown")
                # Prefix with server name to avoid collisions
                agent_tool_name = f"mcp_{server_name}_{mcp_tool_name}".replace("-", "_")

                # Build the handler that forwards to MCP server
                # Capture server and tool_name in closure (default args avoid late binding)
                def make_handler(srv, tname):
                    def handler(**kwargs):
                        try:
                            return srv.call_tool(tname, kwargs)
                        except MCPServerError as e:
                            return f"MCP tool error: {e}"
                    return handler

                input_schema = tool_def.get("inputSchema", {
                    "type": "object",
                    "properties": {},
                })
                # Ensure it's a valid JSON Schema
                if "type" not in input_schema:
                    input_schema = {"type": "object", "properties": input_schema}

                tool = build_tool(
                    name=agent_tool_name,
                    description=tool_def.get("description", f"MCP tool: {mcp_tool_name}"),
                    input_schema=input_schema,
                    handler=make_handler(server, mcp_tool_name),
                    # MCP tools: conservatively assume destructive unless proven otherwise
                    is_read_only=False,
                    is_destructive=False,
                )

                registry.register(tool)
                self._tool_registry[agent_tool_name] = server
                registered.append(agent_tool_name)

        return registered

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to an MCP server."""
        return tool_name in self._tool_registry

    @property
    def tool_count(self) -> int:
        return sum(
            len(s.tool_definitions)
            for s in self._servers.values()
            if s.is_running
        )


# ── Config loader ────────────────────────────────────────────


def load_mcp_from_config(config: dict) -> MCPClientManager:
    """Create and configure MCPClientManager from settings.json config.

    Expected format:
      {
        "mcp_servers": {
          "brave-search": {
            "command": "node",
            "args": ["path/to/server.js"],
            "env": {"BRAVE_API_KEY": "xxx"}
          }
        }
      }
    """
    manager = MCPClientManager()
    servers = config.get("mcp_servers", {})
    for name, cfg in servers.items():
        if cfg.get("disabled"):
            continue
        manager.add_server(
            name=name,
            command=cfg.get("command", ""),
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
        )
    return manager
