"""Walk API request/response bodies and transform only the human text.

Structural fields (ids, roles, model names, tool names, JSON schemas,
signatures) are never touched, so the API contract stays intact.

Reasoning ("thinking") blocks are passed through untouched in both
directions. Providers sign them, so they must come back byte-for-byte; and
because we never restore them, they only ever contain stand-ins.
"""

from __future__ import annotations

import json
from typing import Any, Callable

SKIP_KEYS = {
    "model",
    "role",
    "type",
    "id",
    "tool_use_id",
    "tool_call_id",
    "call_id",
    "item_id",
    "stop_reason",
    "stop_sequence",
    "media_type",
    "cache_control",
    "signature",
    "encrypted_content",
    "name",
    "input_schema",
    "parameters",
    "schema",
    "json_schema",
    "metadata",
    "object",
    "created",
    "index",
    "finish_reason",
    "usage",
    "system_fingerprint",
    "service_tier",
    "status",
    "response_format",
    "tool_choice",
    "reasoning_effort",
    "previous_response_id",
    "prompt_cache_key",
    "safety_identifier",
    "user",
    "file_id",
    "container",
    "anthropic_version",
    "url",
    "image_url",
    "detail",
    "format",
    "logprobs",
    "sequence_number",
    "output_index",
    "content_index",
    "response_id",
    "effort",
    "stream",
    "store",
    "truncation",
    "include",
    "modalities",
    "voice",
    "audio",
}
OPAQUE_TYPES = {"thinking", "redacted_thinking", "reasoning", "image", "input_image", "input_audio", "compaction"}


class Walker:
    def __init__(self, transform: Callable[[str], str], *, restoring: bool = False):
        self.transform = transform
        self.restoring = restoring
        self.binary_documents = 0

    def walk(self, node: Any) -> Any:
        if isinstance(node, dict):
            return self._walk_dict(node)
        if isinstance(node, list):
            return [self.walk(x) for x in node]
        if isinstance(node, str):
            return self.transform(node)
        return node

    def _walk_dict(self, node: dict) -> dict:
        t = node.get("type")
        if t in OPAQUE_TYPES:
            return node
        if t == "base64" or (
            isinstance(node.get("data"), str) and str(node.get("media_type", "")).startswith(("application/", "image/"))
        ):
            self.binary_documents += 1
            return node
        out = {}
        for key, value in node.items():
            if key in SKIP_KEYS:
                out[key] = value
            elif key == "data" and str(node.get("media_type", "")).startswith("text/"):
                out[key] = self.transform(value) if isinstance(value, str) else value
            elif key == "data":
                out[key] = value
            elif key == "arguments" and isinstance(value, str):
                out[key] = self._json_string(value)
            elif key == "partial_json" and isinstance(value, str):
                out[key] = value  # handled by the stream transformer
            else:
                out[key] = self.walk(value)
        return out

    def _json_string(self, value: str) -> str:
        """Function-call arguments arrive as a JSON document inside a string."""
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return self.transform(value)
        return json.dumps(self.walk(parsed), ensure_ascii=False)
