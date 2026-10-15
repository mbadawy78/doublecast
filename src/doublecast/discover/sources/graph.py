"""Microsoft 365 through Microsoft Graph: Outlook contacts, the people you
email with, and SharePoint lists and spreadsheets.

Only metadata is read from mail (sender and recipient names and addresses,
via the Mail.ReadBasic permission): never message bodies or attachments.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

from ..microsoft import Api
from .base import Source, SourceError, Table
from .files import FolderSource

GRAPH = "https://graph.microsoft.com/v1.0"


class GraphSource(Source):
    kind = "m365"

    def __init__(
        self,
        name: str,
        api: Api,
        contacts: bool = True,
        mail_messages: int = 500,
        sharepoint_sites: list[str] | None = None,
        sharepoint_files: int = 50,
    ):
        super().__init__(name)
        self.api = api
        self.contacts = contacts
        self.mail_messages = mail_messages
        self.sites = sharepoint_sites or []
        self.sharepoint_files = sharepoint_files
        self.skipped: list[str] = []
        self._rows: dict[str, list[dict]] = {}
        self._tmp = None

    # ------------------------------------------------------------ tables
    def tables(self) -> Iterator[Table]:
        if self.contacts:
            yield from self._try("Outlook contacts", self._contacts)
        if self.mail_messages:
            yield from self._try("Mail correspondents", self._correspondents)
        for query in self.sites:
            yield from self._try(f"SharePoint '{query}'", lambda q=query: self._sharepoint(q))

    def _try(self, label: str, fn) -> Iterator[Table]:
        try:
            yield from fn()
        except SourceError as exc:
            self.skipped.append(f"{label}: {exc}")

    def _contacts(self) -> Iterator[Table]:
        rows = []
        for c in self.api.pages(
            f"{GRAPH}/me/contacts", {"$select": "displayName,companyName,emailAddresses", "$top": "500"}
        ):
            emails = [e.get("address") for e in c.get("emailAddresses") or [] if e.get("address")]
            rows.append(
                {
                    "Contact name": c.get("displayName"),
                    "Company": c.get("companyName"),
                    "Email": emails[0] if emails else None,
                }
            )
        self._rows["Outlook contacts"] = rows
        yield Table("Outlook contacts", ["Contact name", "Company", "Email"])

    def _correspondents(self) -> Iterator[Table]:
        rows = []
        seen = set()
        params = {"$select": "from,toRecipients,ccRecipients", "$top": "100"}
        for m in self.api.pages(f"{GRAPH}/me/messages", params, limit=self.mail_messages):
            people = [m.get("from")] + (m.get("toRecipients") or []) + (m.get("ccRecipients") or [])
            for p in people:
                ea = (p or {}).get("emailAddress") or {}
                key = (ea.get("name"), ea.get("address"))
                if key in seen or not any(key):
                    continue
                seen.add(key)
                name = ea.get("name")
                if name and "@" in name:  # display name is just the address
                    name = None
                rows.append({"Contact name": name, "Email": ea.get("address")})
        self._rows["Mail correspondents"] = rows
        yield Table("Mail correspondents", ["Contact name", "Email"])

    def _sharepoint(self, query: str) -> Iterator[Table]:
        sites = self.api.get(f"{GRAPH}/sites", {"search": query}).get("value", [])
        if not sites:
            raise SourceError("no site found")
        for site in sites[:3]:
            sid, sname = site["id"], site.get("displayName") or site.get("name") or query
            for lst in self.api.pages(f"{GRAPH}/sites/{sid}/lists", limit=200):
                if (lst.get("list") or {}).get("hidden") or (lst.get("list") or {}).get(
                    "template"
                ) == "documentLibrary":
                    continue
                items = list(
                    self.api.pages(f"{GRAPH}/sites/{sid}/lists/{lst['id']}/items", {"expand": "fields"}, limit=5000)
                )
                rows = [
                    {
                        k: v
                        for k, v in (it.get("fields") or {}).items()
                        if not k.startswith(("@", "_"))
                        and k
                        not in (
                            "id",
                            "ContentType",
                            "Edit",
                            "LinkTitle",
                            "LinkTitleNoMenu",
                            "Attachments",
                            "ItemChildCount",
                            "FolderChildCount",
                            "AppAuthorLookupId",
                            "AppEditorLookupId",
                        )
                    }
                    for it in items
                ]
                key = f"{sname} / {lst.get('displayName') or lst.get('name')}"
                self._rows[key] = rows
                yield Table(key, sorted({k for r in rows for k in r}))
            if self.sharepoint_files:
                yield from self._sharepoint_files(sid, sname)

    def _sharepoint_files(self, site_id: str, site_name: str) -> Iterator[Table]:
        found = self.api.get(f"{GRAPH}/sites/{site_id}/drive/root/search(q='.xlsx')").get("value", [])
        found += self.api.get(f"{GRAPH}/sites/{site_id}/drive/root/search(q='.csv')").get("value", [])
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="doublecast-")
        for item in found[: self.sharepoint_files]:
            name = item.get("name", "")
            if not name.lower().endswith((".xlsx", ".xlsm", ".csv")):
                continue
            r = self.api.client.get(
                f"{GRAPH}/sites/{site_id}/drive/items/{item['id']}/content",
                headers=self.api._h(),
                follow_redirects=True,
            )  # noqa: SLF001
            if r.status_code != 200:
                self.skipped.append(f"{site_name}/{name}: HTTP {r.status_code}")
                continue
            local = Path(self._tmp.name) / f"{item['id']}_{name}"
            local.write_bytes(r.content)
            folder = FolderSource(name, local)
            for t in folder.tables():
                key = f"{site_name} / {name}" + (f" / {t.name.split('::', 1)[1]}" if "::" in t.name else "")
                self._rows[key] = folder.sample(t, 100000)
                yield Table(key, t.columns)

    # ------------------------------------------------------------ data
    def sample(self, table: Table, n: int) -> list[dict]:
        return self._rows.get(table.name, [])[:n]

    def values(self, table: Table, column: str, limit: int):
        for row in self._rows.get(table.name, [])[:limit]:
            yield row.get(column)

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()  # downloaded copies never outlive the scan
