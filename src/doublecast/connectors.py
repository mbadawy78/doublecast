"""Put a connector (a local MCP server, such as Power BI) behind Doublecast.

    doublecast connect powerbi        # once: wraps the connector in the Claude app's config
    doublecast connect powerbi --undo # puts it back as it was

After `connect`, the Claude app starts `doublecast wrap -- <the original command>` instead of the
connector itself. Everything the connector returns is scrambled on its way to the AI; what the AI
sends (a DAX query naming a customer double) gets the real values back first. The original
command is kept in ~/.doublecast/connectors.json, so discovery can ask the same connector, with
the sign-in it already has, which customers, suppliers and people exist.

Only connectors that run on this computer can be wrapped. Connectors added in claude.ai run on
the provider's servers and never pass through this machine.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


def claude_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _registry(home: Path) -> Path:
    return home / "connectors.json"


def registered(home: Path) -> dict:
    try:
        return json.loads(_registry(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _doublecast_command() -> list[str]:
    exe = shutil.which("doublecast")
    return [exe] if exe else [sys.executable, "-m", "doublecast"]


def connect(home: Path, name: str, config_path: Path | None = None) -> str:
    path = Path(config_path or claude_config_path())
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    if name not in servers:
        known = ", ".join(sorted(servers)) or "none"
        raise ValueError(f"No connector called '{name}' in {path}. Connectors there: {known}")
    entry = servers[name]
    args = list(entry.get("args") or [])
    if "wrap" in args and "--" in args:
        return f"'{name}' already goes through Doublecast."
    original = {"command": entry["command"], "args": args, "env": entry.get("env") or {}}
    backup = path.with_name(f"{path.name}.before-doublecast-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    cmd = _doublecast_command()
    servers[name] = {
        **entry,
        "command": cmd[0],
        "args": [*cmd[1:], "wrap", "--name", name, "--", original["command"], *original["args"]],
    }
    data["mcpServers"] = servers
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    reg = registered(home)
    reg[name] = {**original, "config": str(path), "backup": str(backup)}
    home.mkdir(parents=True, exist_ok=True)
    _registry(home).write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding="utf-8")
    return f"'{name}' now goes through Doublecast. Quit the Claude app (Cmd+Q) and open it again. Backup: {backup}"


def disconnect(home: Path, name: str) -> str:
    reg = registered(home)
    if name not in reg:
        return f"'{name}' was not connected through Doublecast."
    info = reg.pop(name)
    path = Path(info["config"])
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data.get("mcpServers", {}).get(name, {})
    entry["command"], entry["args"] = info["command"], info["args"]
    if info.get("env"):
        entry["env"] = info["env"]
    data.setdefault("mcpServers", {})[name] = entry
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _registry(home).write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding="utf-8")
    return f"'{name}' is back as it was. Restart the Claude app."


# ---------------------------------------------------------------- a tiny MCP client (stdio)
class StdioClient:
    """Starts an MCP server and calls its tools: enough for discovery, no SDK needed."""

    def __init__(self, command: str, args: list[str], env: dict | None = None, timeout: float = 120):
        self.proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **(env or {})},
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.timeout = timeout
        self._id = 0
        self._lock = threading.Lock()
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "doublecast-discover", "version": "1"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    @classmethod
    def for_connector(cls, home: Path, name: str) -> StdioClient:
        info = registered(home).get(name)
        if not info:
            raise ValueError(f"'{name}' is not connected. Run: doublecast connect {name}")
        return cls(info["command"], info["args"], info.get("env"))

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._id += 1
            want = self._id
            self._send({"jsonrpc": "2.0", "id": want, "method": method, "params": params})
            deadline = time.monotonic() + self.timeout
            assert self.proc.stdout is not None
            while time.monotonic() < deadline:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError(f"The connector stopped while answering {method}")
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("id") == want:
                    if "error" in msg:
                        raise RuntimeError(str(msg["error"].get("message", msg["error"])))
                    return msg.get("result") or {}
            raise TimeoutError(f"No answer to {method} in {self.timeout:.0f}s")

    def call(self, tool: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        text = "\n".join(texts)
        if result.get("isError"):
            raise RuntimeError(text[:300])
        try:  # FastMCP servers often wrap a JSON string in {"result": "..."}
            outer = json.loads(text)
            if isinstance(outer, dict) and set(outer) == {"result"} and isinstance(outer["result"], str):
                return outer["result"]
        except ValueError:
            pass
        return text

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()
