"""Credentials and payment cards.

These are removed and never restored: an AI never needs your real key,
and a key in a provider's logs is a key you have to rotate.
"""

from __future__ import annotations

import re

from ..validators import luhn_valid
from .base import Span

SECRET_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"), 0),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), 0),
    ("openai_key", re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}"), 0),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"), 0),
    ("gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"), 0),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"), 0),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), 0),
    ("stripe_key", re.compile(r"\b[rs]k_(?:live|test)_[0-9A-Za-z]{20,}\b"), 0),
    ("nvidia_key", re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}\b"), 0),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), 0),
    ("azure_storage_key", re.compile(r"AccountKey=[A-Za-z0-9+/=]{40,}"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), 0),
    (
        "connection_string",
        re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)://[^\s:@/]+:([^\s@/]+)@"),
        1,
    ),
    ("sendgrid_key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"), 0),
    ("twilio_key", re.compile(r"\bSK[0-9a-fA-F]{32}\b"), 0),
    ("http_auth", re.compile(r"(?i)\b(?:Bearer|Basic)\s+([A-Za-z0-9+/=._~\-]{16,})"), 1),
    (
        "assigned_secret",
        re.compile(
            r"""(?ix)
            \b(?:[a-z0-9]+[_-])*                       # prefixes: DB_, AWS_, AZURE_CLIENT_ ...
            (?:password|passwd|pwd|passphrase|secret|api[_-]?key|apikey|access[_-]?key|private[_-]?key|
               token|credentials?|κωδικός|συνθηματικό|passwort|mot[_\s-]de[_\s-]passe|contraseña)
            (?:[_-](?:key|token|secret|pass|password|pwd|value|string|b64|base64))*   # _ACCESS_KEY, _TOKEN ...
            \s*["']?\s*(?:=|:)\s*["']?
            (?!\$|\{|<|%|https?://|os\.|process\.|env\b|getenv|ENV\[|config\.|settings\.|self\.|None\b|null\b|true\b|false\b|\*{3})
            ([^\s"'`,;(){}\[\]]{8,})
            """
        ),
        1,
    ),
]

_CARD_WORDS = (
    "card",
    "visa",
    "mastercard",
    "amex",
    "american express",
    "maestro",
    "cc ",
    "cc:",
    "credit",
    "debit",
    "pan",
    "κάρτα",
    "κάρτας",
    "karte",
    "kreditkarte",
    "carte",
    "carta",
    "tarjeta",
)
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")


def detect_secrets(text: str) -> list[Span]:
    spans: list[Span] = []
    for kind, pattern, group in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            s, e = m.span(group)
            if kind == "assigned_secret" and text[s:e].isdigit():
                continue  # counts and limits ("max_tokens: 40960") are not secrets
            if e > s:
                spans.append(Span(s, e, "SECRET", text[s:e], "secret", action="redact", kind=kind))
    for m in _CARD.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"[ -]", "", raw)
        grouped = bool(re.fullmatch(r"\d{4}([ -])\d{4}\1\d{4}\1\d{1,7}|\d{4}([ -])\d{6}\2\d{5}", raw))
        nearby = text[max(0, m.start() - 40) : m.start()].lower()
        context = any(w in nearby for w in _CARD_WORDS)
        if not (grouped or context):
            continue  # a bare 16-digit number is more often an order or account reference
        if 13 <= len(digits) <= 19 and digits[0] in "3456" and luhn_valid(digits):
            spans.append(Span(m.start(), m.end(), "SECRET", m.group(0), "secret", action="redact", kind="payment_card"))
    return spans
