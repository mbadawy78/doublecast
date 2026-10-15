"""Configuration: what counts as sensitive, and how to treat it.

Config lives in ``~/.doublecast/config.yaml`` by default (override the folder
with the ``DOUBLECAST_HOME`` environment variable, or pass a file path).
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = (
    "PERSON",
    "ORG",
    "SITE",
    "PRODUCT",
    "PROJECT",
    "EMAIL",
    "PHONE",
    "IBAN",
    "TAX_ID",
    "NATIONAL_ID",
    "ID",
    "URL",
    "IP",
    "MONEY",
    "QUANTITY",
    "DATE",
    "SECRET",
    "CUSTOM",
)

ALL_LANGUAGES = ("el", "en", "de", "fr", "it", "es")
ALL_PACKS = ("fmcg", "finance", "hr", "legal_health")


def default_home() -> Path:
    env = os.environ.get("DOUBLECAST_HOME")
    return Path(env).expanduser() if env else Path.home() / ".doublecast"


@dataclass
class Term:
    category: str
    value: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Config:
    workspace: str = "default"
    home: Path = field(default_factory=default_home)
    mode: str = "warn"  # "warn" = log and still send; "block" = refuse to send on failure
    languages: list[str] = field(default_factory=lambda: list(ALL_LANGUAGES))
    default_language: str = "en"
    packs: list[str] = field(default_factory=lambda: list(ALL_PACKS))
    terms: list[Term] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    scale_money: bool = True
    scale_quantities: bool = False
    number_locale: str = "auto"  # auto | eu | us
    shift_dates: bool = False
    ner_enabled: str = "auto"  # auto | on | off
    ner_model: str = "urchade/gliner_multi_pii-v1"
    ner_threshold: float = 0.55
    ner_labels: list[str] = field(default_factory=lambda: ["person", "organization", "company", "location", "product"])
    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8787
    upstream_anthropic: str = "https://api.anthropic.com"
    upstream_openai: str = "https://api.openai.com"
    upstream_chatgpt: str = "https://chatgpt.com/backend-api/codex"
    pin_claude_code_system: bool = True
    source_path: Path | None = None

    @property
    def vault_path(self) -> Path:
        return self.home / f"{self.workspace}.vault"

    @property
    def key_path(self) -> Path:
        return self.home / "key"


def _parse_terms(raw: Any) -> list[Term]:
    terms: list[Term] = []
    if not raw:
        return terms
    if not isinstance(raw, dict):
        raise ValueError("'terms' must map a category (ORG, PERSON, ...) to a list of values")
    for category, items in raw.items():
        cat = str(category).upper()
        if cat not in CATEGORIES:
            raise ValueError(f"Unknown category '{category}'. Use one of: {', '.join(CATEGORIES)}")
        for item in items or []:
            if isinstance(item, str):
                terms.append(Term(cat, item.strip()))
            elif isinstance(item, dict) and "value" in item:
                aliases = [str(a).strip() for a in item.get("aliases", []) if str(a).strip()]
                terms.append(Term(cat, str(item["value"]).strip(), aliases))
            else:
                raise ValueError(f"Bad term entry under {cat}: {item!r}")
    return [t for t in terms if t.value]


def _load_term_file(path: Path) -> list[Term]:
    """CSV with columns: category,value[,aliases separated by |]."""
    terms: list[Term] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cat = (row.get("category") or "").strip().upper()
            value = (row.get("value") or "").strip()
            if not cat or not value:
                continue
            if cat not in CATEGORIES:
                raise ValueError(f"{path}: unknown category '{cat}'")
            aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
            terms.append(Term(cat, value, aliases))
    return terms


def load_config(path: str | Path | None = None, **overrides: Any) -> Config:
    home = default_home()
    cfg_path = Path(path).expanduser() if path else home / "config.yaml"
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    numbers = data.get("numbers", {}) or {}
    dates = data.get("dates", {}) or {}
    ner = data.get("ner", {}) or {}
    proxy = data.get("proxy", {}) or {}
    upstreams = proxy.get("upstreams", {}) or {}

    cfg = Config(
        workspace=str(data.get("workspace", "default")),
        home=Path(data["home"]).expanduser() if data.get("home") else home,
        mode=str(data.get("mode", "warn")),
        languages=list(data.get("languages", ALL_LANGUAGES)),
        default_language=str(data.get("default_language", "en")),
        packs=list(data.get("packs", ALL_PACKS)),
        terms=_parse_terms(data.get("terms")),
        allow=[str(a) for a in data.get("allow", []) or []],
        scale_money=bool(numbers.get("scale_money", True)),
        scale_quantities=bool(numbers.get("scale_quantities", False)),
        number_locale=str(numbers.get("locale", "auto")),
        shift_dates=bool(dates.get("shift", False)),
        ner_enabled=str(ner.get("enabled", "auto")),
        ner_model=str(ner.get("model", Config.ner_model)),
        ner_threshold=float(ner.get("threshold", 0.55)),
        proxy_host=str(proxy.get("host", "127.0.0.1")),
        proxy_port=int(proxy.get("port", 8787)),
        upstream_anthropic=str(upstreams.get("anthropic", "https://api.anthropic.com")),
        upstream_openai=str(upstreams.get("openai", "https://api.openai.com")),
        upstream_chatgpt=str(upstreams.get("chatgpt", "https://chatgpt.com/backend-api/codex")),
        pin_claude_code_system=bool(proxy.get("pin_claude_code_system", True)),
        source_path=cfg_path if cfg_path.exists() else None,
    )
    if ner.get("labels"):
        cfg.ner_labels = list(ner["labels"])

    for tf in data.get("term_files", []) or []:
        p = Path(tf).expanduser()
        if not p.is_absolute() and cfg_path.exists():
            p = cfg_path.parent / p
        cfg.terms.extend(_load_term_file(p))

    for key, value in overrides.items():
        if value is not None:
            setattr(cfg, key, value)

    if cfg.mode not in ("warn", "block"):
        raise ValueError("mode must be 'warn' or 'block'")
    unknown = [p for p in cfg.packs if p not in ALL_PACKS]
    if unknown:
        raise ValueError(f"Unknown packs: {unknown}. Available: {', '.join(ALL_PACKS)}")
    return cfg


CONFIG_TEMPLATE = """\
# Doublecast configuration
# Everything here stays on this machine. Docs: https://github.com/mimisbadawy78/doublecast

workspace: {workspace}      # separate vault per workspace (client, company, project)
mode: warn                  # warn = log problems and still send | block = refuse to send

languages: [el, en, de, fr, it, es]
default_language: en        # language used for stand-in names when it can't be guessed
packs: [{packs}]

# Your own sensitive terms. These are the most reliable protection you have:
# anything listed here is always replaced, in any case or accent form.
terms:
  ORG:
    - Example Customer S.A.
    - value: Example Supplier
      aliases: [Παράδειγμα Προμηθευτής]
  PERSON:
    - Nikos Paradeigmatos
  SITE:
    - Example Plant North
  PRODUCT:
    - Secret Recipe X
  PROJECT:
    - Project Falcon

# Or keep long lists in CSV files (columns: category,value,aliases with | between aliases)
# term_files: [customers.csv, suppliers.csv, people.csv]

# Words that must never be replaced (countries, your own public brand, etc.)
allow: [Greece, Athens, Europe]

numbers:
  scale_money: true         # multiply money amounts by a secret factor (ratios stay correct)
  scale_quantities: false   # same for kg, units, cases, pallets
  locale: auto              # auto | eu (1.234,56) | us (1,234.56)

dates:
  shift: false              # move dates by a secret number of whole weeks

ner:
  enabled: auto             # auto = use the local AI detector if installed (pip install doublecast[ner])
  threshold: 0.55

proxy:
  host: 127.0.0.1
  port: 8787
"""
