"""keymenu daemon — main entry point.

Starts a GTK4 application that:
  - Builds and hides a KeymenuWindow once.
  - Listens on /tmp/keymenu.sock for TOGGLE messages.
  - On TOGGLE: reloads config and shows/hides the window safely via GLib.idle_add.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from keymenu.config import ConfigError, load_config
from keymenu.window import KeymenuWindow

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

LOG_DIR = Path.home() / ".local" / "share" / "keymenu"
LOG_PATH = LOG_DIR / "keymenu.log"
SOCKET_PATH = Path("/tmp/keymenu.sock")

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stderr),
        ],
    )


logger = logging.getLogger("keymenu.daemon")

# ---------------------------------------------------------------------------
# Singleton app state (module-level so the socket thread can reference it)
# ---------------------------------------------------------------------------

_window: KeymenuWindow | None = None
_window_visible = False
_last_valid_config: tuple | None = None  # (settings, tree, commands)


# ---------------------------------------------------------------------------
# Config loading with fallback
# ---------------------------------------------------------------------------


def _load_config_safe() -> tuple | None:
    """Load config, returning None (and logging) on error.

    Updates _last_valid_config on success so later failures can fall back.
    """
    global _last_valid_config
    try:
        result = load_config()
        _last_valid_config = result
        return result
    except ConfigError as exc:
        logger.error("Config error: %s", exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error loading config: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Toggle handler (called from GLib main loop via idle_add)
# ---------------------------------------------------------------------------


def _handle_toggle() -> bool:
    """Show or hide the window. Must be called from the GTK main thread."""
    global _window_visible

    if _window is None:
        return GLib.SOURCE_REMOVE

    if _window_visible:
        _window.hide_menu()
        _window_visible = False
    else:
        config = _load_config_safe()
        if config is None:
            config = _last_valid_config
        if config is None:
            logger.error("No valid config available — cannot show window")
            return GLib.SOURCE_REMOVE
        settings, tree, commands = config
        _window.show_menu(tree, settings, commands)
        _window_visible = True

    return GLib.SOURCE_REMOVE


def _on_window_hidden() -> None:
    """Called by the window when it finishes hiding itself."""
    global _window_visible
    _window_visible = False


# ---------------------------------------------------------------------------
# Unix socket server (runs in a background daemon thread)
# ---------------------------------------------------------------------------


def _socket_server() -> None:
    """Background thread: accept connections and dispatch messages."""
    while True:
        try:
            _run_socket_server()
        except Exception as exc:
            logger.error("Socket server crashed, restarting: %s", exc, exc_info=True)


def _run_socket_server() -> None:
    # Remove stale socket
    if SOCKET_PATH.exists():
        try:
            SOCKET_PATH.unlink()
        except OSError as exc:
            logger.warning("Could not remove stale socket %s: %s", SOCKET_PATH, exc)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCKET_PATH))
    srv.listen(5)
    logger.info("Socket server listening on %s", SOCKET_PATH)

    try:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            try:
                with conn:
                    data = conn.recv(256).decode("utf-8", errors="replace").strip()
                    if data == "TOGGLE":
                        logger.debug("Received TOGGLE")
                        GLib.idle_add(_handle_toggle)
                    else:
                        logger.warning("Unknown message: %r", data)
            except Exception as exc:
                logger.error("Error handling connection: %s", exc)
    finally:
        srv.close()
        try:
            SOCKET_PATH.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# GTK Application
# ---------------------------------------------------------------------------


def _on_activate(app: Gtk.Application) -> None:
    global _window

    if _window is not None:
        # Already activated (happens on second activate signal)
        return

    logger.info("keymenu daemon starting")

    # Pre-load config to catch errors early
    config = _load_config_safe()
    if config is None and _last_valid_config is None:
        logger.warning("No valid config on startup; daemon will wait for a valid one")

    _window = KeymenuWindow(application=app)
    _window.on_hidden = _on_window_hidden
    # Keep the GTK app alive even with no windows shown
    app.hold()

    # Start the socket server in a background daemon thread
    thread = threading.Thread(target=_socket_server, name="keymenu-socket", daemon=True)
    thread.start()

    logger.info("keymenu daemon ready")


def main() -> None:
    _setup_logging()

    # Remove stale socket before the app loop even starts (belt-and-suspenders)
    if SOCKET_PATH.exists():
        try:
            SOCKET_PATH.unlink()
        except OSError:
            pass

    app = Gtk.Application(
        application_id="io.github.keymenu",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.connect("activate", _on_activate)

    exit_code = app.run(sys.argv)

    # Cleanup on exit
    try:
        SOCKET_PATH.unlink(missing_ok=True)
    except OSError:
        pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
