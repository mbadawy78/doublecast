"""doublecast: command line.

doublecast init                  set up config, key and vault
doublecast scan  FILE            show what would be swapped (changes nothing)
doublecast scramble FILE         write FILE.doublecast.<ext>
doublecast restore  FILE         write FILE.restored.<ext>
doublecast clip scramble|restore swap the clipboard (for web chats)
doublecast proxy                 run the local proxy for Claude Code / Codex
doublecast run -- claude         run a tool through a temporary proxy
doublecast env claude|codex      print the settings to use the proxy
doublecast mcp                   run the MCP server (stdio)
doublecast vault stats|list|forget|wipe
doublecast bench                 run the leak benchmark
doublecast doctor                check the installation
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import ALL_PACKS, CONFIG_TEMPLATE, default_home, load_config

BOLD, DIM, GREEN, YELLOW, RED, RESET = (
    ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("",) * 6
)


def _engine(args):
    from .engine import Engine

    overrides = {}
    if getattr(args, "workspace", None):
        overrides["workspace"] = args.workspace
    if getattr(args, "mode", None):
        overrides["mode"] = args.mode
    return Engine(load_config(getattr(args, "config", None), **overrides))


def _print_counts(counts: dict[str, int]) -> None:
    if not counts:
        print(f"{DIM}Nothing sensitive found.{RESET}")
        return
    total = sum(counts.values())
    parts = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    print(f"{GREEN}Swapped {total} value(s){RESET}: {parts}")


def _print_warnings(warnings: list[str]) -> None:
    for w in warnings:
        print(f"{YELLOW}! {w}{RESET}", file=sys.stderr)


# ---------------------------------------------------------------- commands
def cmd_init(args) -> int:
    home = default_home()
    home.mkdir(parents=True, exist_ok=True)
    cfg_path = Path(args.config).expanduser() if args.config else home / "config.yaml"
    if cfg_path.exists() and not args.force:
        print(f"Config already exists: {cfg_path}  (use --force to overwrite)")
    else:
        packs = args.packs.split(",") if args.packs else list(ALL_PACKS)
        cfg_path.write_text(
            CONFIG_TEMPLATE.format(workspace=args.workspace or "default", packs=", ".join(packs)), encoding="utf-8"
        )
        try:
            os.chmod(cfg_path, 0o600)  # it will hold your customer and people lists
        except OSError:
            pass
        print(f"{GREEN}Created{RESET} {cfg_path}")
    engine = _engine(args)
    print(f"{GREEN}Vault ready{RESET} {engine.config.vault_path}")
    print(
        f"{GREEN}Key{RESET}         {engine.config.key_path}  {DIM}(keep it safe; without it nothing can be restored){RESET}"
    )
    print(
        f"\nNext:\n  1. Add your customers, suppliers, people and sites under 'terms' in {cfg_path}\n"
        f"  2. Try it:  doublecast scan some-file.xlsx\n"
        f"  3. Use it with Claude Code:  doublecast run -- claude"
    )
    return 0


def cmd_scan(args) -> int:
    from .detectors.base import Span  # noqa: F401

    engine = _engine(args)
    text = _read_input(args.file, engine)
    spans = engine.detect(text)
    if not spans:
        print(f"{DIM}Nothing sensitive found.{RESET}")
    for s in spans:
        shown = s.text if len(s.text) <= 60 else s.text[:57] + "..."
        action = {"redact": "remove", "money": "scale", "quantity": "scale", "date": "shift"}.get(s.action, "swap")
        print(f"  {s.category:<12} {action:<6} {shown!r}  {DIM}({s.detector}{':' + s.kind if s.kind else ''}){RESET}")
    counts: dict[str, int] = {}
    for s in spans:
        counts[s.category] = counts.get(s.category, 0) + 1
    print()
    if counts:
        print(
            f"{BOLD}{sum(counts.values())} value(s){RESET}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        )
    _print_warnings(engine._warnings(text, spans))  # noqa: SLF001
    return 0


def _read_input(file: str, engine) -> str:
    if file == "-":
        return sys.stdin.read()
    path = Path(file).expanduser()
    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm", ".docx"):
        from .mcp_server import _text_of

        return _text_of(path)
    if ext == ".pdf":
        from pypdf import PdfReader

        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8")


def cmd_scramble(args) -> int:
    engine = _engine(args)
    if args.file == "-":
        result = engine.scramble(sys.stdin.read())
        sys.stdout.write(result.text)
        _print_warnings(result.warnings)
        return 0
    from .files import scramble_file

    dst, counts, warnings = scramble_file(
        engine, Path(args.file).expanduser(), Path(args.output) if args.output else None
    )
    _print_counts(counts)
    _print_warnings(warnings)
    print(f"{BOLD}->{RESET} {dst}")
    return 0


def cmd_restore(args) -> int:
    engine = _engine(args)
    if args.file == "-":
        sys.stdout.write(engine.restore(sys.stdin.read()))
        return 0
    from .files import restore_file

    dst, _, _ = restore_file(engine, Path(args.file).expanduser(), Path(args.output) if args.output else None)
    print(f"{BOLD}->{RESET} {dst}")
    return 0


def _clipboard_get() -> str:
    system = platform.system()
    if system == "Darwin":
        return subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout
    if system == "Windows":
        # UTF-8 both ways, or Greek turns into question marks in Windows PowerShell 5.1
        script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"
        return subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
    for cmd in (
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        if shutil.which(cmd[0]):
            return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    raise RuntimeError("No clipboard tool found (install wl-clipboard, xclip or xsel)")


def _clipboard_set(text: str) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["pbcopy"], input=text, text=True, check=True)
        return
    if system == "Windows":
        script = "[Console]::InputEncoding=[Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], input=text, text=True, encoding="utf-8", check=True
        )
        return
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text, text=True, check=True)
            return
    raise RuntimeError("No clipboard tool found (install wl-clipboard, xclip or xsel)")


def cmd_clip(args) -> int:
    engine = _engine(args)
    text = _clipboard_get()
    if args.direction == "scramble":
        result = engine.scramble(text)
        _clipboard_set(result.text)
        _print_counts(result.summary())
        _print_warnings(result.warnings)
        print("Clipboard now holds the safe version. Paste it into the chat.")
    else:
        _clipboard_set(engine.restore(text))
        print("Clipboard now holds the answer with real values.")
    return 0


def _free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _serve(engine, host: str, port: int, background: bool = False):
    import uvicorn

    from .proxy.app import create_app

    app = create_app(engine)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    if not background:
        server.run()
        return None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server


def _env_lines(host: str, port: int) -> dict[str, str]:
    base = f"http://{host}:{port}"
    # Claude Code appends /v1/messages to the base URL; the proxy recognises Anthropic
    # traffic by its headers, so the bare address is the safest choice.
    return {"ANTHROPIC_BASE_URL": base, "OPENAI_BASE_URL": f"{base}/openai/v1"}


CODEX_SNIPPET = """# ~/.codex/config.toml  (user-level file; project files ignore these keys)

# If you use Codex with an OpenAI API key:
openai_base_url = "{base}/openai/v1"

# If you sign in to Codex with ChatGPT, use a custom provider instead
# (remove openai_base_url above):
# model_provider = "doublecast"
# [model_providers.doublecast]
# name = "OpenAI via Doublecast"
# base_url = "{base}/backend-api/codex"
# requires_openai_auth = true
"""

CLAUDE_SNIPPET = """# One session:
export ANTHROPIC_BASE_URL={base}

# Every session: add to ~/.claude/settings.json
{{
  "env": {{
    "ANTHROPIC_BASE_URL": "{base}"
  }}
}}

# Optional: stop Claude Code's non-essential traffic that does not go through the proxy
# (telemetry, error reports, update checks):
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Check inside Claude Code with /status (look for "Anthropic base URL").
"""


def cmd_proxy(args) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    engine = _engine(args)
    host = args.host or engine.config.proxy_host
    port = args.port or engine.config.proxy_port
    env = _env_lines(host, port)
    print(
        f"{BOLD}Doublecast proxy{RESET} on http://{host}:{port}  workspace={engine.config.workspace}  mode={engine.config.mode}"
    )
    print(f"  Claude Code:  export ANTHROPIC_BASE_URL={env['ANTHROPIC_BASE_URL']}")
    print("  Codex:        doublecast env codex   (prints the config.toml lines)")
    print(f"  Other tools:  base URL {env['OPENAI_BASE_URL']}")
    print(f"{DIM}Ctrl+C to stop.{RESET}")
    _serve(engine, host, port)
    return 0


def cmd_run(args) -> int:
    if not args.command:
        print("Usage: doublecast run -- <command> [args]", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING)
    engine = _engine(args)
    host = "127.0.0.1"
    port = _free_port(args.port or engine.config.proxy_port)
    server = _serve(engine, host, port, background=True)
    env = os.environ.copy()
    env.update(_env_lines(host, port))
    print(
        f"{DIM}doublecast: protecting this session via http://{host}:{port} (workspace {engine.config.workspace}){RESET}",
        file=sys.stderr,
    )
    try:
        return subprocess.call(args.command, env=env)
    finally:
        if server:
            server.should_exit = True


def cmd_env(args) -> int:
    cfg = load_config(args.config)
    base = f"http://{cfg.proxy_host}:{cfg.proxy_port}"
    if args.tool in ("claude", "all"):
        print(CLAUDE_SNIPPET.format(base=base))
    if args.tool in ("codex", "all"):
        print(CODEX_SNIPPET.format(base=base))
    if args.tool in ("openai", "all"):
        print(f"# Other OpenAI-compatible tools: set the base URL to\n{base}/openai/v1")
    return 0


def cmd_mcp(args) -> int:
    from .mcp_server import main

    main()
    return 0


def cmd_vault(args) -> int:
    engine = _engine(args)
    v = engine.vault
    if args.action == "stats":
        stats = v.stats()
        print(f"Workspace {engine.config.workspace}: {sum(stats.values())} protected value(s)")
        for k, n in sorted(stats.items()):
            print(f"  {k:<12} {n}")
    elif args.action == "list":
        for m in sorted(v.mappings(), key=lambda m: (m.category, m.original)):
            print(f"  {m.category:<12} {m.original}  ->  {m.surrogate}")
    elif args.action == "forget":
        if not args.value:
            print("Usage: doublecast vault forget VALUE", file=sys.stderr)
            return 2
        print("Forgotten." if v.forget(args.value) else "Not in the vault.")
    elif args.action == "wipe":
        if not args.yes:
            print(
                "This deletes every mapping and secret factor in this workspace; scrambled files can no longer be restored."
            )
            print("Run again with --yes to confirm.")
            return 1
        v.wipe()
        print("Vault wiped.")
    return 0


def _mask(value: str) -> str:
    """Show enough to recognise a value in a review, not enough for a screen share."""
    v = str(value)
    return v if len(v) <= 4 else v[:3] + "…" + ("" if len(v) < 8 else v[-1])


def _print_discovery(results, show_values: bool) -> None:
    for r in results:
        head = f"{BOLD}{r.name}{RESET} {DIM}({r.kind}){RESET}"
        if r.error:
            print(f"{head}  {RED}{r.error}{RESET}")
            continue
        print(head)
        found = [c for c in r.columns if c.category]
        if not found:
            print(f"  {DIM}no sensitive columns found{RESET}")
        for c in found:
            ex = ", ".join(c.examples if show_values else [_mask(e) for e in c.examples])
            extra = (
                f"  {DIM}{c.values} values{', ' + str(c.skipped) + ' skipped' if c.skipped else ''}{RESET}"
                if c.values
                else ""
            )
            print(
                f"  {c.category:<9} {c.table} › {c.column}{extra}  {DIM}[{c.reason}]{RESET}"
                + (f"  e.g. {ex}" if ex else "")
            )
        for sk in r.skipped:
            print(f"  {YELLOW}skipped:{RESET} {sk}")
        counts = r.counts()
        if counts:
            print("  " + GREEN + "→ " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + RESET)
        print()


def cmd_discover(args) -> int:
    from .discover.run import apply, build_sources, scan
    from .discover.sources.files import FolderSource

    engine = _engine(args)
    cfg = engine.config
    action = args.action or "run"

    if action == "status":
        srcs = engine.rules.sources()
        if not srcs and not engine.rules.data["learned"]:
            print(
                "Nothing discovered or learned yet. Add sources under discover: in your config, or run: doublecast discover path FOLDER"
            )
        for name, info in sorted(srcs.items()):
            counts = ", ".join(f"{k} {len(v)}" for k, v in sorted(info.get("terms", {}).items()))
            print(f"{BOLD}{name}{RESET}  refreshed {info.get('refreshed', '?')}  {counts}")
        learned = {k: len(v) for k, v in engine.rules.data["learned"].items() if v}
        if learned:
            print(f"{BOLD}learned on the fly{RESET}  " + ", ".join(f"{k} {v}" for k, v in sorted(learned.items())))
        total = sum(engine.rules.counts().values())
        print(f"\n{total} value(s) protected by discovered and learned rules (plus your own terms: {len(cfg.terms)}).")
        return 0
    if action == "forget":
        if not args.target:
            print("Usage: doublecast discover forget SOURCE|learned", file=sys.stderr)
            return 2
        if args.target == "learned":
            engine.rules.clear_learned()
            ok = True
        else:
            ok = any(
                engine.rules.remove_source(k)
                for k in list(engine.rules.sources())
                if k == args.target or k.endswith(":" + args.target)
            )
        engine.rules.save()
        print("Removed." if ok else "No such source.")
        return 0
    if action == "ignore":
        if not args.target:
            print("Usage: doublecast discover ignore VALUE", file=sys.stderr)
            return 2
        engine.rules.ignore(args.target)
        engine.rules.save()
        print(f"'{args.target}' will never be protected by discovered or learned rules.")
        return 0

    if action == "path":
        if not args.target:
            print("Usage: doublecast discover path FOLDER_OR_FILE", file=sys.stderr)
            return 2
        sources = [FolderSource(Path(args.target).name or "files", args.target)]
    else:
        if not cfg.discover_sources:
            print("No sources configured. Add them under discover: sources: in your config (see docs/discover.md),")
            print("or scan a folder of Excel/CSV files now: doublecast discover path ~/Documents/masterdata")
            return 1
        sources = build_sources(cfg, engine.vault)
        if args.source:
            sources = [s for s in sources if s.name == args.source]

    results = []
    for src in sources:
        if not args.quiet:
            print(f"{DIM}Scanning {src.name} ({src.kind})...{RESET}", file=sys.stderr)
        say = None if args.quiet else (lambda m: print(DIM + m + RESET, file=sys.stderr))
        results.append(scan(src, cfg.discover_sample_rows, cfg.discover_max_values, say))
    if not args.quiet:
        _print_discovery(results, args.show_values)
    total = sum(sum(r.counts().values()) for r in results)
    if args.dry_run or total == 0:
        print("Dry run: nothing saved." if args.dry_run else "Nothing to save.")
        return 0
    if not args.yes:
        answer = input(f"Protect these {total} value(s) from now on? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes", "ν", "ναι"):
            print("Nothing saved.")
            return 0
    apply(results, engine.rules)
    print(f"{GREEN}Saved.{RESET} {total} value(s) are now protected (encrypted in {cfg.rules_path}).")
    return 0


def cmd_bench(args) -> int:
    from .bench import run_benchmark

    if args.auto:
        from .bench import run_auto_benchmark

        report = run_auto_benchmark(n=min(args.n, 150), seed=args.seed)
    else:
        report = run_benchmark(n=args.n, seed=args.seed)
    print(report)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"\n-> {args.output}")
    return 0


def cmd_doctor(args) -> int:
    ok = True
    cfg = load_config(args.config)
    print(f"doublecast {__version__}  python {platform.python_version()}  {platform.system()}")
    print(f"config     {cfg.source_path or 'not found (defaults in use; run doublecast init)'}")
    print(f"workspace  {cfg.workspace}  mode={cfg.mode}  packs={','.join(cfg.packs)}")
    print(f"terms      {len(cfg.terms)} listed")
    key = cfg.key_path
    if key.exists():
        mode = oct(key.stat().st_mode & 0o777)
        flag = (
            GREEN + "ok" + RESET
            if mode in ("0o600", "0o400") or platform.system() == "Windows"
            else YELLOW + f"permissions {mode}, expected 0o600" + RESET
        )
        print(f"key        {key}  {flag}")
    else:
        print(f"key        {YELLOW}missing (created on first use){RESET}")
    try:
        import gliner  # noqa: F401

        print(f"ner        {GREEN}GLiNER installed{RESET} (model {cfg.ner_model})")
    except ImportError:
        print(f"ner        {DIM}not installed (optional: pip install 'doublecast[ner]'){RESET}")
    if not cfg.terms:
        ok = False
        print(
            f"{YELLOW}! No terms listed. Patterns still catch IDs, IBANs, emails, phones and secrets, but company and people names need your lists.{RESET}"
        )
    return 0 if ok else 1


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c", "--config", default=argparse.SUPPRESS, help="config file (default ~/.doublecast/config.yaml)"
    )
    common.add_argument("-w", "--workspace", default=argparse.SUPPRESS, help="workspace name (each has its own vault)")
    p = argparse.ArgumentParser(
        prog="doublecast", description="Keep your data home. Send its double to the AI.", parents=[common]
    )
    p.add_argument("--version", action="version", version=f"doublecast {__version__}")
    p.set_defaults(config=None, workspace=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    _add = sub.add_parser

    def add_parser(name, **kw):
        return _add(name, parents=[common], **kw)

    sub.add_parser = add_parser  # every subcommand accepts -c / -w too

    s = sub.add_parser("init", help="create config, key and vault")
    s.add_argument("--packs", help=f"comma-separated packs ({','.join(ALL_PACKS)})")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("scan", help="show what would be swapped, without changing anything")
    s.add_argument("file", help="file path or - for stdin")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("scramble", help="write a scrambled copy of a file (or stdin -> stdout)")
    s.add_argument("file")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_scramble)

    s = sub.add_parser("restore", help="put the real values back into a file (or stdin -> stdout)")
    s.add_argument("file")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("clip", help="scramble or restore the clipboard (for claude.ai, ChatGPT, Gemini)")
    s.add_argument("direction", choices=["scramble", "restore"])
    s.set_defaults(func=cmd_clip)

    s = sub.add_parser("proxy", help="run the local proxy")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--mode", choices=["warn", "block"])
    s.set_defaults(func=cmd_proxy)

    s = sub.add_parser("run", help="run a command (e.g. claude, codex) through a temporary proxy")
    s.add_argument("--port", type=int)
    s.add_argument("--mode", choices=["warn", "block"])
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("env", help="print environment settings for a tool")
    s.add_argument("tool", choices=["claude", "codex", "openai", "all"])
    s.set_defaults(func=cmd_env)

    s = sub.add_parser("mcp", help="run the MCP server over stdio")
    s.set_defaults(func=cmd_mcp)

    s = sub.add_parser("vault", help="inspect or manage the vault")
    s.add_argument("action", choices=["stats", "list", "forget", "wipe"])
    s.add_argument("value", nargs="?")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_vault)

    s = sub.add_parser(
        "discover",
        help="learn what is sensitive from your systems (Power BI, Microsoft 365, Dynamics 365, SharePoint, SQL, files)",
    )
    s.add_argument("action", nargs="?", choices=["run", "path", "status", "forget", "ignore"], default="run")
    s.add_argument("target", nargs="?", help="folder for 'path', source for 'forget', value for 'ignore'")
    s.add_argument("--source", help="run only the source with this name")
    s.add_argument("--dry-run", action="store_true", help="show what would be protected, save nothing")
    s.add_argument("--yes", action="store_true", help="save without asking (for scheduled refreshes)")
    s.add_argument("--quiet", action="store_true", help="no progress or report output")
    s.add_argument("--show-values", action="store_true", help="show example values in full (default: masked)")
    s.set_defaults(func=cmd_discover)

    s = sub.add_parser("bench", help="run the leak benchmark on synthetic data")
    s.add_argument("-n", type=int, default=300, help="documents per language")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("-o", "--output", help="write the Markdown report here")
    s.add_argument("--auto", action="store_true", help="benchmark auto mode: no lists, only structure and learning")
    s.set_defaults(func=cmd_bench)

    s = sub.add_parser("doctor", help="check the installation")
    s.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    try:
        return int(args.func(args) or 0)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"{RED}error:{RESET} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
