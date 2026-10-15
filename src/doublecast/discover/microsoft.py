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
            flow = self.app.initiate_device_flow(scopes=scopes)
            if "user_code" not in flow:
                raise SourceError(f"Microsoft sign-in could not start: {flow.get('error_description', flow)}")
            self.prompt(flow["message"])
            result = self.app.acquire_token_by_device_flow(flow)
        self._save()
        if "access_token" not in result:
            raise SourceError(f"Microsoft sign-in failed: {result.get('error_description', result.get('error'))}")
        return result["access_token"]


class Api:
    """Small JSON client with bearer tokens and OData paging."""

    def __init__(self, token: Callable[[], str], client: httpx.Client | None = None, headers: dict | None = None):
        self._token = token
        self.client = client or httpx.Client(timeout=60.0)
        self.headers = headers or {}

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Accept": "application/json", **self.headers}

    def get(self, url: str, params: dict | None = None) -> dict:
        r = self.client.get(url, params=params, headers=self._h())
        if r.status_code in (401, 403):
            raise SourceError(f"No permission to read {url.split('?')[0]} (HTTP {r.status_code})")
        if r.status_code == 404:
            raise SourceError(f"Not found: {url.split('?')[0]}")
        r.raise_for_status()
        return r.json()

    def post(self, url: str, body: dict) -> dict:
        r = self.client.post(url, json=body, headers=self._h())
        if r.status_code in (401, 403):
            raise SourceError(f"No permission for {url} (HTTP {r.status_code})")
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:300]
            raise SourceError(f"{url} failed (HTTP {r.status_code}): {detail}")
        return r.json()

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
