"""Doublecast in the menu bar (macOS) or the system tray (Windows, Linux).

🛡 23            today's swaps, next to the clock
● Protecting Claude Code / Codex     (or ○ Proxy off — Start)
Today: 23 swapped · 9 people · 6 companies · 8 amounts
Total: 1,204 swapped
Last swaps ▸     14:05  person  El••• → Fa•••
Scramble clipboard
Restore clipboard
Start at login ✓

pip install "doublecast[tray]"     # rumps on macOS, pystray elsewhere
doublecast tray                    # run it now
doublecast tray --autostart        # and every time you log in
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .config import load_config

_LABELS = {
    "PERSON": ("person", "people"),
    "ORG": ("company", "companies"),
    "MONEY": ("amount", "amounts"),
    "EMAIL": ("email", "emails"),
    "PHONE": ("phone", "phones"),
}


def _label(cat: str, n: int) -> str:
    one, many = _LABELS.get(cat, (cat.lower(), cat.lower()))
    return f"{n} {one if n == 1 else many}"


class Model:
    """Everything the icon shows and does, independent of the toolkit."""

    def __init__(self, workspace: str | None = None):
        overrides = {"workspace": workspace} if workspace else {}
        self.cfg = load_config(None, **overrides)
        self._engine = None
        self._proxy: subprocess.Popen | None = None
        self.data: dict = {}
        self.mirrors: list = []
        self.refresh()

    def start_mirrors(self) -> None:
        """Keep every folder added with `doublecast mirror` in sync while the icon runs."""
        import dataclasses

        from . import mirror
        from .engine import Engine

        for ws in sorted({m.get("workspace", "default") for m in mirror.registered(self.cfg.home)}):
            engine = Engine(dataclasses.replace(self.cfg, workspace=ws))
            engine.activity.source = "mirror"
            self.mirrors += mirror.run_all(engine)

    # ------------------------------------------------------------ state
    def refresh(self) -> dict:
        from .cli import status_data

        self.data = status_data(self.cfg)
        return self.data

    @property
    def title(self) -> str:
        leaks = len(self.data.get("leaks_today") or [])
        if leaks:
            return f"🛡⚠ {leaks}"  # a known value got through today: look at the menu
        return f"🛡 {self.data.get('today_total', 0)}"

    @property
    def leak_lines(self) -> list[str]:
        leaks = self.data.get("leaks_today") or []
        if not leaks:
            return ["No leaks found today"]
        return [
            f"⚠ {x['time']}  {x['category'].lower()}  {x['value']}  in {x['where']}  ({x['via']})" for x in leaks[:10]
        ]

    @property
    def proxy_line(self) -> str:
        if self.data.get("proxy", {}).get("running"):
            return "● Protecting Claude Code / Codex"
        return "○ Proxy off"

    @property
    def today_line(self) -> str:
        today = self.data.get("today", {})
        parts = [_label(c, n) for c, n in sorted(today.items(), key=lambda kv: -kv[1])[:4]]
        return f"Today: {self.data.get('today_total', 0)} swapped" + (" · " + " · ".join(parts) if parts else "")

    @property
    def total_line(self) -> str:
        return f"Total: {self.data.get('total_all', 0):,} swapped"

    @property
    def last_lines(self) -> list[str]:
        rows = self.data.get("last", [])
        if not rows:
            return ["Nothing swapped yet"]
        return [f"{r['time']}  {r['category'].lower()}  {r['from']} → {r['to']}  ({r['via']})" for r in rows]

    @property
    def mirror_lines(self) -> list[str]:
        if not self.mirrors:
            return ["No mirrored folders (doublecast mirror <folder>)"]
        out = []
        for m in self.mirrors:
            if m.error:
                out.append(f"⚠ {m.src.name}: stopped. {m.error[:80]}")
                continue
            when = f"synced {m.last_sync}" if m.last_sync else "first sync running…"
            held = f"  ·  {m.last_report.held} AI changes held" if m.last_report.held else ""
            out.append(f"{m.src.name} → {m.twin.name}  ·  {when}{held}")
        return out

    # ------------------------------------------------------------ actions
    def engine(self):
        if self._engine is None:
            from .engine import Engine

            self._engine = Engine(self.cfg)
            self._engine.activity.source = "tray"
        return self._engine

    def scramble_clipboard(self) -> str:
        from .cli import _clipboard_get, _clipboard_set

        text = _clipboard_get()
        if not text.strip():
            return "The clipboard is empty."
        result = self.engine().scramble(text)
        _clipboard_set(result.text)
        self.engine().activity.flush()
        return f"{len(result.spans)} value(s) swapped. Paste into the chat."

    def restore_clipboard(self) -> str:
        from .cli import _clipboard_get, _clipboard_set

        text = _clipboard_get()
        if not text.strip():
            return "The clipboard is empty."
        restored = self.engine().restore(text)
        _clipboard_set(restored)
        return "Real values are back in the clipboard." if restored != text else "Nothing to restore."

    def toggle_proxy(self) -> str:
        if self.data.get("proxy", {}).get("running"):
            if self._proxy and self._proxy.poll() is None:
                self._proxy.terminate()
                self._proxy = None
                return "Proxy stopped."
            return "The proxy was started elsewhere; stop it there."
        self._proxy = subprocess.Popen(
            [sys.executable, "-m", "doublecast", "proxy", "-w", self.cfg.workspace],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Proxy starting on {self.data.get('proxy', {}).get('address', '')}."

    def quit(self) -> None:
        if self._proxy and self._proxy.poll() is None:
            self._proxy.terminate()
        if self._engine is not None:
            self._engine.activity.flush()


# ---------------------------------------------------------------- start at login
def _command() -> list[str]:
    exe = shutil.which("doublecast")
    return [exe, "tray"] if exe else [sys.executable, "-m", "doublecast", "tray"]


def _autostart_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "LaunchAgents" / "com.doublecast.tray.plist"
    if system == "Windows":
        startup = Path(os.environ.get("APPDATA", Path.home())) / "Microsoft/Windows/Start Menu/Programs/Startup"
        return startup / "doublecast-tray.cmd"
    return Path.home() / ".config" / "autostart" / "doublecast-tray.desktop"


def autostart_enabled() -> bool:
    return _autostart_path().exists()


def autostart(enable: bool = True) -> str:
    path = _autostart_path()
    if not enable:
        if path.exists():
            path.unlink()
        return "Doublecast will no longer start at login."
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = _command()
    system = platform.system()
    if system == "Darwin":
        args = "".join(f"<string>{a}</string>" for a in cmd)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>'
            "<key>Label</key><string>com.doublecast.tray</string>"
            f"<key>ProgramArguments</key><array>{args}</array>"
            "<key>RunAtLoad</key><true/>"
            "</dict></plist>\n",
            encoding="utf-8",
        )
    elif system == "Windows":
        quoted = " ".join(f'"{a}"' for a in cmd)
        path.write_text(f'@echo off\r\nstart "" /min {quoted}\r\n', encoding="utf-8")
    else:
        path.write_text(
            "[Desktop Entry]\nType=Application\nName=Doublecast\n"
            f"Exec={' '.join(cmd)}\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    return f"Doublecast will start at login ({path})."


# ---------------------------------------------------------------- toolkits
def run_tray(workspace: str | None = None) -> int:
    model = Model(workspace)
    model.start_mirrors()
    if platform.system() == "Darwin":
        return _run_macos(model)
    return _run_pystray(model)


def _run_macos(model: Model) -> int:
    try:
        import rumps
    except ImportError:
        print('The menu-bar icon needs rumps: pip install "doublecast[tray]"', file=sys.stderr)
        return 1

    class App(rumps.App):
        def __init__(self):
            super().__init__("Doublecast", title=model.title, quit_button=None)
            self.proxy_item = rumps.MenuItem(model.proxy_line, callback=self.on_proxy)
            self.today_item = rumps.MenuItem(model.today_line)
            self.total_item = rumps.MenuItem(model.total_line)
            self.last_item = rumps.MenuItem("Last swaps")
            self.mirror_item = rumps.MenuItem("Mirrored folders")
            self.leak_item = rumps.MenuItem("Leak alarm")
            self.login_item = rumps.MenuItem("Start at login", callback=self.on_login)
            self.login_item.state = autostart_enabled()
            self.menu = [
                self.proxy_item,
                None,
                self.today_item,
                self.total_item,
                self.last_item,
                self.leak_item,
                self.mirror_item,
                None,
                rumps.MenuItem("Scramble clipboard", callback=self.on_scramble, key="s"),
                rumps.MenuItem("Restore clipboard", callback=self.on_restore, key="r"),
                None,
                self.login_item,
                rumps.MenuItem("Quit Doublecast", callback=self.on_quit, key="q"),
            ]
            self.redraw()
            rumps.Timer(lambda _: self.redraw(), 5).start()

        def redraw(self):
            model.refresh()
            self.title = model.title
            self.proxy_item.title = model.proxy_line + ("" if model.data["proxy"]["running"] else " — Start")
            self.today_item.title = model.today_line
            self.total_item.title = model.total_line
            try:
                self.last_item.clear()
            except Exception:  # no submenu yet on the first draw
                pass
            for line in model.last_lines:
                self.last_item.add(rumps.MenuItem(line))
            try:
                self.mirror_item.clear()
            except Exception:
                pass
            for line in model.mirror_lines:
                self.mirror_item.add(rumps.MenuItem(line))
            try:
                self.leak_item.clear()
            except Exception:
                pass
            self.leak_item.title = "⚠ Leak alarm" if model.data.get("leaks_today") else "Leak alarm: all clear"
            for line in model.leak_lines:
                self.leak_item.add(rumps.MenuItem(line))

        def _say(self, message: str):
            rumps.notification("Doublecast", "", message)
            self.redraw()

        def on_proxy(self, _):
            self._say(model.toggle_proxy())

        def on_scramble(self, _):
            self._say(model.scramble_clipboard())

        def on_restore(self, _):
            self._say(model.restore_clipboard())

        def on_login(self, item):
            autostart(enable=not item.state)
            item.state = autostart_enabled()

        def on_quit(self, _):
            model.quit()
            rumps.quit_application()

    App().run()
    return 0


def _icon_image():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(32, 4), (58, 14), (54, 40), (32, 60), (10, 40), (6, 14)], fill=(47, 107, 85, 255))
    d.text((24, 22), "D", fill=(255, 255, 255, 255))
    return img


def _run_pystray(model: Model) -> int:
    try:
        import pystray
    except ImportError:
        print('The tray icon needs pystray and pillow: pip install "doublecast[tray]"', file=sys.stderr)
        return 1
    import threading

    def notify(icon, message):
        try:
            icon.notify(message, "Doublecast")
        except Exception:  # some Linux trays cannot notify
            pass
        model.refresh()
        icon.update_menu()

    def last_items():
        return [pystray.MenuItem(line, None, enabled=False) for line in model.last_lines]

    menu = pystray.Menu(
        pystray.MenuItem(lambda _: model.proxy_line, lambda icon, _: notify(icon, model.toggle_proxy())),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda _: model.today_line, None, enabled=False),
        pystray.MenuItem(lambda _: model.total_line, None, enabled=False),
        pystray.MenuItem("Last swaps", pystray.Menu(last_items)),
        pystray.MenuItem(
            lambda _: "⚠ Leak alarm" if model.data.get("leaks_today") else "Leak alarm: all clear",
            pystray.Menu(lambda: [pystray.MenuItem(x, None, enabled=False) for x in model.leak_lines]),
        ),
        pystray.MenuItem(
            "Mirrored folders",
            pystray.Menu(lambda: [pystray.MenuItem(x, None, enabled=False) for x in model.mirror_lines]),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Scramble clipboard", lambda icon, _: notify(icon, model.scramble_clipboard())),
        pystray.MenuItem("Restore clipboard", lambda icon, _: notify(icon, model.restore_clipboard())),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Start at login",
            lambda icon, item: autostart(enable=not autostart_enabled()),
            checked=lambda _: autostart_enabled(),
        ),
        pystray.MenuItem("Quit Doublecast", lambda icon, _: (model.quit(), icon.stop())),
    )
    icon = pystray.Icon("doublecast", _icon_image(), model.title, menu)

    def tick():
        import time

        while True:
            time.sleep(5)
            model.refresh()
            icon.title = f"Doublecast · {model.title} today"
            icon.update_menu()

    threading.Thread(target=tick, daemon=True).start()
    icon.run()
    return 0
