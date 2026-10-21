"""Sign-in to Microsoft services (Graph, Power BI, Dynamics 365) for discovery.

Uses the device-code flow: Doublecast prints a short code, you open
https://microsoft.com/devicelogin on any device and sign in as yourself.
Doublecast only ever gets *read* access you grant, and only to your data.

Microsoft requires every script to have its own app registration (a
"client ID"); there is no shared one we may use. Your IT admin creates it
once in Microsoft Entra ID (see docs/discover.md), then:

    microsoft:
      tenant_id: <your tenant id or domain>
      client_id: <the app's client id>

Tokens are cached encrypted with the vault key, so you sign in once.

    pip install "doublecast[m365]"
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator

import httpx

from .sources.base import SourceError

GRAPH_SCOPES = ["User.Read", "Contacts.Read", "Mail.ReadBasic", "Sites.Read.All"]
POWERBI_SCOPES = [
    "https://analysis.windows.net/powerbi/api/Dataset.Read.All",
    "https://analysis.windows.net/powerbi/api/Workspace.Read.All",
]


class MicrosoftAuth:
    def __init__(self, tenant: str, client_id: str, vault, cache_path, prompt: Callable[[str], None] | None = None):
        if not client_id:
            raise SourceError(
                "Microsoft sources need an app registration. Add microsoft.client_id (and tenant_id) to your config; "
                "see docs/discover.md, 'Microsoft sign-in'."
            )
        try:
            import msal
        except ImportError as exc:  # pragma: no cover
            raise SourceError("Microsoft sources need MSAL: pip install 'doublecast[m365]'") from exc
        self.msal = msal
        self.vault = vault
        self.cache_path = cache_path
        self.cache = msal.SerializableTokenCache()
        if cache_path.exists():
            try:
                self.cache.deserialize(vault.decrypt(cache_path.read_bytes()).decode("utf-8"))
            except Exception:  # corrupt or from another key: start fresh
                pass
        self.app = msal.PublicClientApplication(
            client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=self.cache
        )
        self.prompt = prompt or (lambda msg: print(msg, file=sys.stderr, flush=True))
        self.interactive = lambda: prompt is not None or sys.stdin.isatty()

    def _save(self) -> None:
        if self.cache.has_state_changed:
            import os

            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.cache_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(self.vault.encrypt(self.cache.serialize().encode("utf-8")))

    def token(self, scopes: list[str]) -> str:
        result = None
        for account in self.app.get_accounts():
            result = self.app.acquire_token_silent(scopes, account=account)
            if result:
                break
        if not result:
            if not self.interactive():
                # a scheduled run must never sit waiting for a sign-in nobody will see
                raise SourceError("Microsoft sign-in needed: run `doublecast discover` once in a terminal")
            flow = self.app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise SourceError(f"Microsoft sign-in could not start: {flow.get('error_description', flow)}")
            self.prompt(flow["message"])
            result = self.app.acquire_token_by_device_flow(flow)
        self._save()
        if "access_token" not in result:
            raise SourceError(f"Microsoft sign-in failed: {result.get('error_description', result.get('error'))}")
        return result["access_token"]


def _retry_after(value: str | None, attempt: int) -> float:
    """Retry-After is seconds or an HTTP date; without it, back off exponentially."""
    if value:
        try:
            return float(value)
        except ValueError:
            import email.utils
            from datetime import datetime, timezone

            try:
                when = email.utils.parsedate_to_datetime(value)
                return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                pass
    return float(min(2**attempt, 30))


class Api:
    """Small JSON client with bearer tokens, OData paging, and polite retries.

    Throttling (429), server hiccups (5xx) and network timeouts are retried with back-off
    (honouring Retry-After); an expired token (401) is refreshed once. Anything else becomes
    a SourceError, so one bad table never stops a scan.
    """

    RETRIES = 5

    def __init__(
        self,
        token: Callable[..., str],
        client: httpx.Client | None = None,
        headers: dict | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._token = token
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=60.0)
        self.headers = headers or {}
        self._sleep = sleep

    def _h(self, fresh: bool = False) -> dict:
        try:
            tok = self._token(fresh=True) if fresh else self._token()
        except TypeError:  # a plain callable without the `fresh` switch
            tok = self._token()
        return {"Authorization": f"Bearer {tok}", "Accept": "application/json", **self.headers}

    def _send(self, method: str, url: str, **kw) -> httpx.Response:
        fresh = False
        short = url.split("?")[0]
        for attempt in range(self.RETRIES + 1):
            try:
                r = self.client.request(method, url, headers=self._h(fresh), **kw)
            except httpx.TransportError as exc:  # timeouts, resets, DNS
                if attempt == self.RETRIES:
                    raise SourceError(f"{short}: network error ({exc.__class__.__name__})") from exc
                self._sleep(min(2**attempt, 30))
                continue
            if r.status_code == 401 and not fresh:
                fresh = True  # token expired during a long scan: get a new one and retry once
                continue
            if (r.status_code == 429 or r.status_code >= 500) and attempt < self.RETRIES:
                wait = _retry_after(r.headers.get("Retry-After"), attempt)
                self._sleep(min(max(wait, 0.5), 60))
                continue
            return r
        return r  # pragma: no cover

    def _check(self, r: httpx.Response, url: str) -> dict:
        short = url.split("?")[0]
        if r.status_code in (401, 403):
            raise SourceError(f"No permission to read {short} (HTTP {r.status_code})")
        if r.status_code == 404:
            raise SourceError(f"Not found: {short}")
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:300]
            raise SourceError(f"{short} failed (HTTP {r.status_code}): {detail}")
        try:
            return r.json()
        except ValueError as exc:
            raise SourceError(f"{short}: the answer was not JSON") from exc

    def get(self, url: str, params: dict | None = None) -> dict:
        return self._check(self._send("GET", url, params=params), url)

    def post(self, url: str, body: dict) -> dict:
        return self._check(self._send("POST", url, json=body), url)

    def download(self, url: str) -> httpx.Response:
        return self._send("GET", url, follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def pages(self, url: str, params: dict | None = None, limit: int = 100000) -> Iterator[dict]:
        """Yield items across @odata.nextLink pages."""
        count = 0
        data = self.get(url, params)
        while True:
            for item in data.get("value", []):
                yield item
                count += 1
                if count >= limit:
                    return
            nxt = data.get("@odata.nextLink")
            if not nxt:
                return
            data = self.get(nxt)
