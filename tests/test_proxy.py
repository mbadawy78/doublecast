"""The proxy against simulated Anthropic and OpenAI servers.

Each fake upstream records what it received (it must never see a real value)
and answers in terms of the stand-ins it was given (the client must only see
real values).
"""

import json

import httpx
from starlette.testclient import TestClient

from doublecast.engine import Engine
from doublecast.proxy.app import create_app

from .conftest import make_config

REAL = ["Nordia Hellas", "Eleni Papadopoulou", "Larissa Plant"]


def _client(engine, handler):
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TestClient(create_app(engine, client=upstream))


def _stand_in(engine, value):
    return engine.vault.get(value)


def _assert_clean(body: str):
    for value in REAL:
        assert value not in body, f"upstream saw {value!r}"


def _sse(events):
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


async def _chunked(text, size):
    for i in range(0, len(text), size):
        yield text[i : i + size].encode()


def test_anthropic_non_streaming(engine):
    seen = {}

    def handler(request: httpx.Request):
        body = request.content.decode()
        seen["body"] = body
        assert request.headers["x-api-key"] == "test-key"
        _assert_clean(body)
        sur = _stand_in(engine, "Nordia Hellas")
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-x",
                "content": [
                    {"type": "thinking", "thinking": f"about {sur}", "signature": "sig=="},
                    {"type": "text", "text": f"{sur} is your top customer."},
                    {"type": "tool_use", "id": "tu_1", "name": "write_file", "input": {"content": f"Customer: {sur}"}},
                ],
            },
        )

    client = _client(engine, handler)
    r = client.post(
        "/anthropic/v1/messages",
        headers={"x-api-key": "test-key", "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": "claude-x",
            "max_tokens": 100,
            "system": "You help Eleni Papadopoulou.",
            "messages": [{"role": "user", "content": "How is Nordia Hellas doing at Larissa Plant?"}],
        },
    )
    data = r.json()
    assert data["content"][1]["text"] == "Nordia Hellas is your top customer."
    assert data["content"][2]["input"]["content"] == "Customer: Nordia Hellas"
    assert data["content"][0]["thinking"] != "about Nordia Hellas"  # signed reasoning stays untouched
    assert data["content"][0]["signature"] == "sig=="


def test_anthropic_streaming_split_stand_in(engine):
    engine.scramble("Nordia Hellas")
    sur = _stand_in(engine, "Nordia Hellas")
    text = f"Yes, {sur} grew 12%. Ask {sur}."
    args = json.dumps({"to": sur})
    events = [
        ("message_start", {"type": "message_start", "message": {"id": "m", "content": [], "role": "assistant"}}),
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        ),
    ]
    for i in range(0, len(text), 3):  # 3-character deltas split every stand-in
        events.append(
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[i : i + 3]}},
            )
        )
    events.append(("content_block_stop", {"type": "content_block_stop", "index": 0}))
    events.append(
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "t", "name": "mail", "input": {}},
            },
        )
    )
    for i in range(0, len(args), 4):
        events.append(
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": args[i : i + 4]},
                },
            )
        )
    events.append(("content_block_stop", {"type": "content_block_stop", "index": 1}))
    events.append(("message_stop", {"type": "message_stop"}))
    stream = _sse(events)

    def handler(request):
        _assert_clean(request.content.decode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_chunked(stream, 17))

    client = _client(engine, handler)
    with client.stream(
        "POST",
        "/anthropic/v1/messages",
        headers={"content-type": "application/json"},
        json={"model": "x", "stream": True, "messages": [{"role": "user", "content": "Nordia Hellas?"}]},
    ) as r:
        raw = "".join(r.iter_text())
    texts, partial = [], []
    for block in raw.strip().split("\n\n"):
        data = json.loads(block.split("data: ", 1)[1])
        if data.get("type") == "content_block_delta":
            d = data["delta"]
            (texts if d["type"] == "text_delta" else partial).append(d.get("text") or d.get("partial_json"))
    assert "".join(texts) == "Yes, Nordia Hellas grew 12%. Ask Nordia Hellas."
    assert json.loads("".join(partial)) == {"to": "Nordia Hellas"}


def test_openai_chat_streaming(engine):
    engine.scramble("Eleni Papadopoulou")
    sur = _stand_in(engine, "Eleni Papadopoulou")
    text = f"Dear {sur}, thanks."
    chunks = [
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "model": "gpt",
            "choices": [{"index": 0, "delta": {"content": text[i : i + 2]}, "finish_reason": None}],
        }
        for i in range(0, len(text), 2)
    ]
    chunks.append(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "model": "gpt",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    )
    stream = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handler(request):
        _assert_clean(request.content.decode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_chunked(stream, 11))

    client = _client(engine, handler)
    with client.stream(
        "POST",
        "/openai/v1/chat/completions",
        headers={"content-type": "application/json"},
        json={"model": "gpt", "stream": True, "messages": [{"role": "user", "content": "Reply to Eleni Papadopoulou"}]},
    ) as r:
        raw = "".join(r.iter_text())
    out = ""
    for block in raw.strip().split("\n\n"):
        payload = block.split("data: ", 1)[1]
        if payload == "[DONE]":
            continue
        for ch in json.loads(payload)["choices"]:
            out += ch["delta"].get("content") or ""
    assert out == "Dear Eleni Papadopoulou, thanks."


def test_openai_responses_streaming(engine):
    engine.scramble("Larissa Plant")
    sur = _stand_in(engine, "Larissa Plant")
    text = f"Ship from {sur} tomorrow."
    events = [
        {"type": "response.output_text.delta", "item_id": "i1", "content_index": 0, "delta": text[i : i + 5]}
        for i in range(0, len(text), 5)
    ]
    events.append({"type": "response.output_text.done", "item_id": "i1", "content_index": 0, "text": text})
    events.append(
        {
            "type": "response.completed",
            "response": {
                "id": "r",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            },
        }
    )
    stream = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)

    def handler(request):
        _assert_clean(request.content.decode())
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_chunked(stream, 23))

    client = _client(engine, handler)
    with client.stream(
        "POST",
        "/openai/v1/responses",
        headers={"content-type": "application/json"},
        json={
            "model": "gpt",
            "stream": True,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "From Larissa Plant?"}]}],
        },
    ) as r:
        raw = "".join(r.iter_text())
    deltas, final = "", None
    for block in raw.strip().split("\n\n"):
        data = json.loads(block.split("data: ", 1)[1])
        if data["type"] == "response.output_text.delta":
            deltas += data["delta"]
        if data["type"] == "response.completed":
            final = data["response"]["output"][0]["content"][0]["text"]
    assert deltas == "Ship from Larissa Plant tomorrow."
    assert final == "Ship from Larissa Plant tomorrow."


def test_block_mode_refuses_on_failure(tmp_path, monkeypatch):
    engine = Engine(make_config(tmp_path, mode="block"))
    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200, json={})

    def boom(_text):
        raise RuntimeError("detector crashed")

    monkeypatch.setattr(engine, "scramble_cached", boom)
    client = _client(engine, handler)
    r = client.post(
        "/anthropic/v1/messages",
        headers={"content-type": "application/json"},
        json={"messages": [{"role": "user", "content": "Nordia Hellas"}]},
    )
    assert r.status_code == 422
    assert called["n"] == 0
    engine.vault.close()


def test_warn_mode_still_strips_secrets(tmp_path, monkeypatch):
    engine = Engine(make_config(tmp_path, mode="warn"))
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    def boom(_text):
        raise RuntimeError("detector crashed")

    monkeypatch.setattr(engine, "scramble_cached", boom)
    client = _client(engine, handler)
    key = "sk-ant-api03-" + "b" * 40
    client.post(
        "/anthropic/v1/messages",
        headers={"content-type": "application/json"},
        json={"messages": [{"role": "user", "content": f"key {key}"}]},
    )
    assert key not in seen["body"]
    engine.vault.close()


def test_health(engine):
    client = _client(engine, lambda r: httpx.Response(200))
    assert client.get("/_doublecast/health").json()["ok"] is True


def test_claude_code_first_system_block_is_untouched(engine):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": []})

    client = _client(engine, handler)
    attribution = {"type": "text", "text": "You are Claude Code. User: Eleni Papadopoulou"}
    client.post(
        "/v1/messages",
        headers={
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "user-agent": "claude-cli/2.1.0 (external, cli)",
        },
        json={"system": [attribution, {"type": "text", "text": "Customer: Nordia Hellas"}], "messages": []},
    )
    assert seen["body"]["system"][0] == attribution
    assert "Nordia Hellas" not in seen["body"]["system"][1]["text"]


def test_chatgpt_codex_route_and_head_probe(engine):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"output": []})

    client = _client(engine, handler)
    assert client.head("/api/hello").status_code == 200
    client.post("/backend-api/codex/responses", headers={"content-type": "application/json"}, json={"input": "hi"})
    assert seen["url"] == "https://chatgpt.com/backend-api/codex/responses"


def test_errors_pass_through_unmodified(engine):
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    client = _client(engine, lambda r: httpx.Response(400, json=error))
    r = client.post(
        "/v1/messages",
        headers={"anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"messages": []},
    )
    assert r.status_code == 400 and r.json() == error


def test_other_clients_first_system_block_is_scrambled(engine):
    seen = {}

    def handler(request):
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"content": []})

    client = _client(engine, handler)
    client.post(
        "/v1/messages",
        headers={
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "user-agent": "anthropic-python/1.0",
        },
        json={"system": [{"type": "text", "text": "You work for Nordia Hellas."}], "messages": []},
    )
    _assert_clean(seen["body"])


def test_non_json_bodies(tmp_path):
    for mode in ("block", "warn"):
        engine = Engine(make_config(tmp_path, mode=mode, workspace=mode))
        seen = {}

        def handler(request, seen=seen):
            seen["body"] = request.content.decode()
            return httpx.Response(200, json={})

        client = _client(engine, handler)
        # valid JSON without a content-type header is still scrambled
        client.post(
            "/v1/messages",
            headers={"anthropic-version": "2023-06-01"},
            content=json.dumps({"messages": [{"role": "user", "content": "Nordia Hellas"}]}),
        )
        _assert_clean(seen["body"])
        seen.clear()
        key = "sk-ant-api03-" + "c" * 40
        r = client.post("/v1/messages", headers={"content-type": "text/plain"}, content=f"Nordia Hellas {key}")
        if mode == "block":
            assert r.status_code == 422 and not seen
        else:
            assert key not in seen["body"]
        engine.vault.close()


def test_streamed_prefix_currency_amounts_are_restored(engine):
    engine.scramble("owes €1.234.567,89 plus $500")
    scrambled = engine.scramble("The account owes a total of €1.234.567,89 plus $500 this year, as agreed.").text
    events = [
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        )
    ]
    for i in range(0, len(scrambled), 4):
        events.append(
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": scrambled[i : i + 4]},
                },
            )
        )
    events.append(("content_block_stop", {"type": "content_block_stop", "index": 0}))
    stream = _sse(events)
    client = _client(
        engine,
        lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_chunked(stream, 9)),
    )
    with client.stream(
        "POST",
        "/v1/messages",
        headers={"anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"stream": True, "messages": []},
    ) as r:
        raw = "".join(r.iter_text())
    text = "".join(
        json.loads(b.split("data: ", 1)[1])["delta"]["text"]
        for b in raw.strip().split("\n\n")
        if "content_block_delta" in b
    )
    assert text == "The account owes a total of €1.234.567,89 plus $500 this year, as agreed."
