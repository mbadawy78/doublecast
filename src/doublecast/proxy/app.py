"""Local proxy: point Claude Code, Codex or any API client here.

    Claude Code       : ANTHROPIC_BASE_URL=http://127.0.0.1:8787
    Codex (API key)   : openai_base_url = "http://127.0.0.1:8787/openai/v1"     (~/.codex/config.toml)
    Codex (ChatGPT)   : provider base_url = "http://127.0.0.1:8787/backend-api/codex"
    Other OpenAI tools: base URL http://127.0.0.1:8787/openai/v1

Requests are scrambled before they leave the machine; responses (plain or
streamed) are restored before your tool sees them. Your API key or login
token is passed through untouched; Doublecast never stores it.

Failure policy follows `mode` in config:
  warn  -> log the problem and send the request as-is
  block -> refuse with HTTP 422 and send nothing
Secrets are always stripped, whatever the mode.
"""

from __future__ import annotations

import gzip
import json
import logging
import time

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ..detectors.base import resolve_overlaps
from ..detectors.secrets import detect_secrets
from ..engine import Engine
from .streams import AnthropicStream, OpenAIChatStream, OpenAIResponsesStream, format_sse, parse_sse_block
from .walk import Walker

log = logging.getLogger("doublecast.proxy")

HOP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
    "accept-encoding",
    "content-encoding",
}


class ProxyStats:
    def __init__(self):
        self.requests = 0
        self.scrambled_strings = 0
        self.failures = 0
        self.started = time.time()


def _filter_headers(headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}


def create_app(engine: Engine, client: httpx.AsyncClient | None = None) -> Starlette:
    cfg = engine.config
    stats = ProxyStats()
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=20.0))

    async def health(_: Request) -> Response:
        return JSONResponse(
            {
                "ok": True,
                "workspace": cfg.workspace,
                "mode": cfg.mode,
                "requests": stats.requests,
                "values_in_vault": sum(engine.vault.stats().values()),
                "failures": stats.failures,
            }
        )

    async def forward(request: Request, provider: str, path: str, base: str | None = None) -> Response:
        stats.requests += 1
        if request.method == "HEAD":  # connection-warming probes: answer locally
            return Response(status_code=200)
        base = base or (cfg.upstream_anthropic if provider == "anthropic" else cfg.upstream_openai)
        url = f"{base.rstrip('/')}/{path.lstrip('/')}"
        if request.url.query:
            url += "?" + request.url.query
        headers = _filter_headers(request.headers)
        headers["accept-encoding"] = "identity"
        body = await request.body()
        if body and request.headers.get("content-encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        original_body = body

        payload = None
        stream = False
        before = dict(engine.totals)
        if body:
            try:
                payload = json.loads(body)  # whatever the content-type header says
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = None
            if payload is None:
                # Not JSON (plain text, multipart file upload, ...): cannot be rewritten safely.
                stats.failures += 1
                if cfg.mode == "block":
                    return _blocked(f"{request.method} {request.url.path} has a non-JSON body that cannot be scrambled")
                log.warning(
                    "Non-JSON body on %s passed through with secrets stripped only (mode=warn)", request.url.path
                )
                body = _strip_secrets_only(original_body)
            else:
                try:
                    stream = bool(isinstance(payload, dict) and payload.get("stream"))
                    pinned = _claude_code_attribution(request, payload, provider, cfg)
                    walker = Walker(engine.scramble_cached)
                    payload = walker.walk(payload)
                    if pinned is not None:
                        payload["system"][0] = pinned
                    if walker.binary_documents:
                        log.warning(
                            "%d image/PDF attachment(s) passed through unscrambled (binary content cannot be rewritten)",
                            walker.binary_documents,
                        )
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                except Exception as exc:  # noqa: BLE001
                    stats.failures += 1
                    if cfg.mode == "block":
                        log.error("Scrambling failed, request blocked: %s", exc)
                        return _blocked(f"could not scramble this request ({exc})")
                    log.warning(
                        "Scrambling failed, request sent without stand-ins (mode=warn), secrets still stripped: %s", exc
                    )
                    body = _strip_secrets_only(original_body)
                    payload = None
        swapped = {k: v - before.get(k, 0) for k, v in engine.totals.items() if v - before.get(k, 0)}
        detail = ", ".join(f"{k} {v}" for k, v in sorted(swapped.items())) or "nothing new"
        log.info(
            "%s %s -> %s%s | protected: %s",
            request.method,
            request.url.path,
            provider,
            " (stream)" if stream else "",
            detail,
        )

        upstream_req = http.build_request(request.method, url, headers=headers, content=body)
        if stream:
            resp = await http.send(upstream_req, stream=True)
            ctype = resp.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                data = await resp.aread()
                await resp.aclose()
                return _restore_plain(engine, data, resp, provider, path)
            transformer = _stream_transformer(engine, provider, path)

            async def gen():
                buffer = ""
                try:
                    async for text in resp.aiter_text():
                        buffer += text.replace("\r\n", "\n")
                        while "\n\n" in buffer:
                            block, buffer = buffer.split("\n\n", 1)
                            for chunk in _transform_block(transformer, block):
                                yield chunk.encode("utf-8")
                    if buffer.strip():
                        for chunk in _transform_block(transformer, buffer):
                            yield chunk.encode("utf-8")
                finally:
                    await resp.aclose()

            return StreamingResponse(
                gen(),
                status_code=resp.status_code,
                headers=_filter_headers(resp.headers),
                media_type="text/event-stream",
            )

        resp = await http.send(upstream_req)
        return _restore_plain(engine, resp.content, resp, provider, path)

    async def anthropic(request: Request) -> Response:
        return await forward(request, "anthropic", request.path_params["path"])

    async def openai(request: Request) -> Response:
        return await forward(request, "openai", request.path_params["path"])

    async def chatgpt(request: Request) -> Response:
        return await forward(request, "openai", request.path_params["path"], base=cfg.upstream_chatgpt)

    async def guess(request: Request) -> Response:
        path = request.path_params["path"]
        provider = (
            "anthropic" if ("anthropic-version" in request.headers or path.startswith("v1/messages")) else "openai"
        )
        return await forward(request, provider, path)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    app = Starlette(
        routes=[
            Route("/_doublecast/health", health, methods=["GET"]),
            Route("/anthropic/{path:path}", anthropic, methods=methods),
            Route("/openai/{path:path}", openai, methods=methods),
            Route("/backend-api/codex/{path:path}", chatgpt, methods=methods),
            Route("/{path:path}", guess, methods=methods),
        ]
    )
    app.state.stats = stats
    app.state.http = http
    return app


def _blocked(reason: str) -> JSONResponse:
    return JSONResponse(
        {
            "type": "error",
            "error": {
                "type": "doublecast_blocked",
                "message": f"Doublecast blocked this request: {reason}. Nothing was sent.",
            },
        },
        status_code=422,
    )


def _claude_code_attribution(request: Request, payload, provider: str, cfg):
    """Return Claude Code's first system block if it must be forwarded unchanged.

    Claude Code puts an attribution block first in `system`, which Anthropic
    checks for subscription logins. Only that block is pinned, and only when
    the client identifies itself as Claude Code (user-agent "claude-cli/...").
    Any other client's system prompt is scrambled like everything else.
    """
    if provider != "anthropic" or not cfg.pin_claude_code_system:
        return None
    ua = request.headers.get("user-agent", "").lower()
    if "claude-cli" not in ua and "claude-code" not in ua:
        return None
    system = payload.get("system") if isinstance(payload, dict) else None
    if not isinstance(system, list) or not system or not isinstance(system[0], dict):
        return None
    block = system[0]
    text = block.get("text", "")
    if not isinstance(text, str) or len(text) > 2000:
        return None
    return block


def _strip_secrets_only(body: bytes) -> bytes:
    """Last line of defence when full scrambling fails: still remove credentials."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    spans = sorted(resolve_overlaps(detect_secrets(text)), key=lambda s: s.start, reverse=True)
    for span in spans:
        text = text[: span.start] + f"[REDACTED:{span.kind}]" + text[span.end :]
    return text.encode("utf-8")


def _stream_transformer(engine: Engine, provider: str, path: str):
    if provider == "anthropic":
        return AnthropicStream(engine)
    if "responses" in path:
        return OpenAIResponsesStream(engine)
    return OpenAIChatStream(engine)


def _transform_block(transformer, block: str) -> list[str]:
    name, data, other = parse_sse_block(block)
    if data is None:
        return [block + "\n\n"] if block.strip() else []
    try:
        parsed = json.loads(data) if data != "[DONE]" else "[DONE]"
    except json.JSONDecodeError:
        return [block + "\n\n"]
    return [format_sse(n, d, other) for n, d in transformer.process(name, parsed)]


def _restore_plain(engine: Engine, content: bytes, resp: httpx.Response, provider: str, path: str) -> Response:
    headers = _filter_headers(resp.headers)
    ctype = resp.headers.get("content-type", "")
    if "json" in ctype and content and resp.status_code < 400:  # errors pass through unmodified
        try:
            data = json.loads(content)
            data = Walker(engine.restore, restoring=True).walk(data)
            content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not restore response body: %s", exc)
    return Response(content=content, status_code=resp.status_code, headers=headers, media_type=ctype or None)
