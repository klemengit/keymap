"""Action executors for keymenu.

Each executor is non-blocking. Errors are caught and logged; they never
propagate to the caller.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path

LOG_PATH = Path.home() / ".local" / "share" / "keymenu" / "keymenu.log"

logger = logging.getLogger("keymenu.actions")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gdbus_raise_browser() -> None:
    """Best-effort: raise the default browser via GNOME Shell DBus."""
    script = (
        "global.get_window_actors()"
        ".filter(w => {"
        "  const cls = w.meta_window.get_wm_class() || '';"
        "  return ['firefox', 'chrome', 'chromium', 'brave', 'epiphany', 'opera']"
        "    .some(b => cls.toLowerCase().includes(b));"
        "})"
        ".forEach(w => w.meta_window.activate(global.get_current_time()));"
    )
    try:
        subprocess.run(
            [
                "gdbus", "call",
                "--session",
                "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/Shell",
                "--method", "org.gnome.Shell.Eval",
                script,
            ],
            timeout=2,
            capture_output=True,
        )
    except Exception as exc:
        logger.debug("gdbus raise-browser failed (non-fatal): %s", exc)


def _gdbus_focus_app(app_name: str) -> bool:
    """Try to focus a running app via GNOME Shell DBus.

    Returns True if the call succeeded (not necessarily that the window was
    actually focused — DBus Eval always returns success even for no-ops).
    """
    safe_name = app_name.lower().replace("'", "\\'").replace('"', '\\"')
    script = (
        f"global.get_window_actors()"
        f".filter(w => (w.meta_window.get_wm_class() || '').toLowerCase()"
        f"  .includes('{safe_name}'))"
        f".forEach(w => w.meta_window.activate(global.get_current_time()));"
    )
    try:
        result = subprocess.run(
            [
                "gdbus", "call",
                "--session",
                "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/Shell",
                "--method", "org.gnome.Shell.Eval",
                script,
            ],
            timeout=2,
            capture_output=True,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.debug("gdbus focus-app failed (non-fatal): %s", exc)
        return False


def _is_app_running(app_name: str) -> bool:
    """Scan /proc/*/cmdline to check if an app process is running."""
    search = app_name.lower()
    proc_root = Path("/proc")
    try:
        for pid_dir in proc_root.iterdir():
            if not pid_dir.name.isdigit():
                continue
            cmdline_file = pid_dir / "cmdline"
            try:
                cmdline = cmdline_file.read_bytes().decode("utf-8", errors="replace")
                # cmdline is NUL-separated; check if any part matches
                parts = cmdline.split("\x00")
                for part in parts:
                    if search in Path(part).name.lower():
                        return True
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
    except Exception as exc:
        logger.debug("Scanning /proc failed: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Public action executors
# ---------------------------------------------------------------------------

def execute_url(value: str) -> None:
    """Open a URL in the default browser.

    1. Best-effort: raise the existing browser window via GNOME Shell DBus.
    2. Open the URL with xdg-open.
    """
    try:
        _gdbus_raise_browser()
        subprocess.Popen(
            ["xdg-open", value],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.error("url action failed for '%s': %s", value, exc)


def execute_app(value: str) -> None:
    """Focus an already-running app or launch it if not running.

    The *value* is the binary/desktop name (e.g. 'kitty', 'obsidian').
    """
    try:
        app_basename = Path(value).name  # strip any path prefix
        if _is_app_running(app_basename):
            # Try to bring the window to front via GNOME Shell DBus.
            _gdbus_focus_app(app_basename)
            # DBus Eval is fire-and-forget; we always fall through to the
            # Popen guard only if we know it is NOT running. For running apps
            # the activation is best-effort.
        else:
            subprocess.Popen(
                [value],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:
        logger.error("app action failed for '%s': %s", value, exc)


def execute_shell(value: str) -> None:
    """Run a shell command non-blocking."""
    try:
        subprocess.Popen(
            value,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.error("shell action failed for '%s': %s", value, exc)


def execute_text(value: str, hide_callback: "Callable[[], None] | None" = None) -> None:  # noqa: F821
    """Type *value* at the current cursor position.

    The window is hidden first (via *hide_callback*), then after 150 ms the
    text is typed using wtype (Wayland) or xdotool (X11) as a fallback.
    """
    if hide_callback is not None:
        try:
            hide_callback()
        except Exception as exc:
            logger.debug("hide_callback failed: %s", exc)

    def _type() -> None:
        try:
            # On GNOME/Wayland wtype doesn't work (no virtual-keyboard protocol).
            # Copy to clipboard with wl-copy instead — reliable on all Wayland compositors.
            if shutil.which("wl-copy") is not None:
                proc = subprocess.run(
                    ["wl-copy", "--", value],
                    capture_output=True,
                )
                if proc.returncode == 0:
                    logger.debug("text action: copied to clipboard via wl-copy")
                    return
            # Fallback: xdotool for X11 / XWayland
            if shutil.which("xdotool") is not None:
                subprocess.Popen(
                    ["xdotool", "type", "--clearmodifiers", "--", value],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                logger.error(
                    "text action: neither 'wl-copy' nor 'xdotool' is installed"
                )
        except Exception as exc:
            logger.error("text action failed: %s", exc)

    timer = threading.Timer(0.15, _type)
    timer.daemon = True
    timer.start()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def execute_action(
    action: str,
    value: str,
    hide_callback: "Callable[[], None] | None" = None,  # noqa: F821
) -> None:
    """Dispatch to the correct executor based on *action* type."""
    if action == "url":
        execute_url(value)
    elif action == "app":
        execute_app(value)
    elif action == "shell":
        execute_shell(value)
    elif action == "text":
        execute_text(value, hide_callback=hide_callback)
    else:
        logger.error("Unknown action type '%s'", action)
