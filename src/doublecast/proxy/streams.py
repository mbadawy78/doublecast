"""Restoring Server-Sent Event streams from Anthropic and OpenAI.

A stand-in can be split across two events ("Nord" | "mart"). Each text
channel (a content block, a choice, a tool call's arguments) gets its own
StreamRestorer that holds back a short tail until it is safe to emit. When
a channel closes, whatever is held back is flushed as one extra delta event
just before the close event.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from ..engine import Engine
from .walk import Walker

Event = tuple[str | None, Any]  # (event name, data: dict | str)


class AnthropicStream:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.walker = Walker(engine.restore, restoring=True)
        self.channels: dict[int, tuple[Any, str]] = {}

    def process(self, name: str | None, data: Any) -> list[Event]:
        if not isinstance(data, dict):
            return [(name, data)]
        t = data.get("type")
        if t == "message_start" and isinstance(data.get("message"), dict):
            data["message"] = self.walker.walk(data["message"])
            return [(name, data)]
        if t == "content_block_start":
            idx = data.get("index", 0)
            block = data.get("content_block") or {}
            btype = block.get("type")
            if btype == "text":
                self.channels[idx] = (self.engine.stream_restorer(), "text_delta")
                if block.get("text"):
                    block["text"] = self.engine.restore(block["text"])
            elif btype in ("tool_use", "server_tool_use"):
                self.channels[idx] = (self.engine.stream_restorer(escape_json=True), "input_json_delta")
                if isinstance(block.get("input"), dict):
                    block["input"] = self.walker.walk(block["input"])
            return [(name, data)]
        if t == "content_block_delta":
            idx = data.get("index", 0)
            delta = data.get("delta") or {}
            channel = self.channels.get(idx)
            if channel is None:
                return [(name, data)]
            restorer, _ = channel
            if delta.get("type") == "text_delta":
                delta["text"] = restorer.feed(delta.get("text", ""))
                return [(name, data)] if delta["text"] else []
            if delta.get("type") == "input_json_delta":
                delta["partial_json"] = restorer.feed(delta.get("partial_json", ""))
                return [(name, data)] if delta["partial_json"] else []
            return [(name, data)]
        if t == "content_block_stop":
            idx = data.get("index", 0)
            out: list[Event] = []
            channel = self.channels.pop(idx, None)
            if channel:
                restorer, dtype = channel
                rest = restorer.flush()
                if rest:
                    field = "text" if dtype == "text_delta" else "partial_json"
                    out.append(
                        (
                            "content_block_delta",
                            {"type": "content_block_delta", "index": idx, "delta": {"type": dtype, field: rest}},
                        )
                    )
            out.append((name, data))
            return out
        return [(name, data)]


class OpenAIChatStream:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.channels: dict[tuple, Any] = {}
        self.last_chunk: dict | None = None

    def _channel(self, key: tuple, escape: bool):
        if key not in self.channels:
            self.channels[key] = self.engine.stream_restorer(escape_json=escape)
        return self.channels[key]

    def process(self, name: str | None, data: Any) -> list[Event]:
        if data == "[DONE]":
            out: list[Event] = []
            leftovers = self._flush_all()
            if leftovers and self.last_chunk:
                chunk = copy.deepcopy(self.last_chunk)
                chunk["choices"] = leftovers
                out.append((name, chunk))
            out.append((name, data))
            return out
        if not isinstance(data, dict):
            return [(name, data)]
        self.last_chunk = {k: v for k, v in data.items() if k != "choices"}
        for choice in data.get("choices", []) or []:
            i = choice.get("index", 0)
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str):
                delta["content"] = self._channel(("c", i), False).feed(delta["content"])
            for tc in delta.get("tool_calls", []) or []:
                fn = tc.get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = self._channel(("t", i, tc.get("index", 0)), True).feed(fn["arguments"])
            if choice.get("finish_reason"):
                self._flush_choice(i, delta)
                choice["delta"] = delta
        return [(name, data)]

    def _flush_choice(self, i: int, delta: dict) -> None:
        for key in [k for k in self.channels if k[1] == i]:
            rest = self.channels.pop(key).flush()
            if not rest:
                continue
            if key[0] == "c":
                delta["content"] = (delta.get("content") or "") + rest
            else:
                delta.setdefault("tool_calls", []).append({"index": key[2], "function": {"arguments": rest}})

    def _flush_all(self) -> list[dict]:
        choices: dict[int, dict] = {}
        for key in list(self.channels):
            rest = self.channels.pop(key).flush()
            if not rest:
                continue
            delta = choices.setdefault(key[1], {"index": key[1], "delta": {}, "finish_reason": None})["delta"]
            if key[0] == "c":
                delta["content"] = rest
            else:
                delta.setdefault("tool_calls", []).append({"index": key[2], "function": {"arguments": rest}})
        return list(choices.values())


class OpenAIResponsesStream:
    """The Responses API (used by OpenAI Codex). Support is beta."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.walker = Walker(engine.restore, restoring=True)
        self.channels: dict[tuple, Any] = {}

    def process(self, name: str | None, data: Any) -> list[Event]:
        if not isinstance(data, dict):
            return [(name, data)]
        t = data.get("type", name)
        if t == "response.output_text.delta":
            key = ("text", data.get("item_id"), data.get("content_index", 0))
            r = self.channels.setdefault(key, self.engine.stream_restorer())
            data["delta"] = r.feed(data.get("delta", ""))
            return [(name, data)] if data["delta"] else []
        if t == "response.output_text.done":
            key = ("text", data.get("item_id"), data.get("content_index", 0))
            out = self._flush(key, name, data, "response.output_text.delta")
            if isinstance(data.get("text"), str):
                data["text"] = self.engine.restore(data["text"])
            return out + [(name, data)]
        if t == "response.function_call_arguments.delta":
            key = ("args", data.get("item_id"))
            r = self.channels.setdefault(key, self.engine.stream_restorer(escape_json=True))
            data["delta"] = r.feed(data.get("delta", ""))
            return [(name, data)] if data["delta"] else []
        if t == "response.function_call_arguments.done":
            out = self._flush(("args", data.get("item_id")), name, data, "response.function_call_arguments.delta")
            if isinstance(data.get("arguments"), str):
                data["arguments"] = self.walker._json_string(data["arguments"])  # noqa: SLF001
            return out + [(name, data)]
        for field in ("item", "part", "response"):
            if isinstance(data.get(field), dict):
                data[field] = self.walker.walk(data[field])
        return [(name, data)]

    def _flush(self, key: tuple, name: str | None, done: dict, delta_type: str) -> list[Event]:
        r = self.channels.pop(key, None)
        rest = r.flush() if r else ""
        if not rest:
            return []
        delta = {k: v for k, v in done.items() if k in ("item_id", "output_index", "content_index", "sequence_number")}
        delta.update({"type": delta_type, "delta": rest})
        return [(delta_type if name else None, delta)]


def parse_sse_block(block: str) -> tuple[str | None, str | None, list[str]]:
    """Return (event name, data string, other lines) for one SSE event block."""
    name, data_lines, other = None, [], []
    for line in block.split("\n"):
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
        elif line:
            other.append(line)
    return name, ("\n".join(data_lines) if data_lines else None), other


def format_sse(name: str | None, data: Any, other: list[str] | None = None) -> str:
    lines = list(other or [])
    if name:
        lines.append(f"event: {name}")
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"
