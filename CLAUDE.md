# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`keymenu` is a GNOME/Wayland daemon providing instant keyboard-driven shortcut trees (inspired by Neovim's which-key). A single global hotkey (Super+Space) shows a GTK4 window; the user navigates nested menus by pressing single keys to fire actions (open URL, run shell command, launch/focus app, paste text).

## Development Setup

```bash
# Install with uv (all dev deps)
uv sync --group dev

# Install the package in editable mode
uv pip install -e .
```

System dependencies required: `python3-gi python3-gi-cairo gir1.2-gtk-4.0`

## Running

```bash
# Start the daemon
keymenu &

# Toggle the window (bind this to Super+Space via GNOME)
keymenu-toggle

# Or use install.sh for full setup (autostart + gsettings hotkey registration)
./install.sh
```

## Architecture

The project uses a **daemon + toggle CLI** model:

- `keymenu/daemon.py` — Long-running GTK4 app. Builds the window once (hidden), listens on `/tmp/keymenu.sock` for IPC, reloads config on every window show.
- `keymenu/toggle.py` — Thin CLI that sends `TOGGLE` to the socket. This is what the global hotkey calls.
- `keymenu/config.py` — Loads `~/.config/keymenu/config.toml` using stdlib `tomllib`. Validates and parses the shortcut tree.
- `keymenu/window.py` — GTK4 window UI: breadcrumb display, key list grid, keyboard event handling, show/hide animations (<120ms).
- `keymenu/actions.py` — Executes the four action types: `url` (xdg-open + best-effort GNOME DBus focus), `app` (focus-or-launch via GLib/gdbus), `shell` (non-blocking subprocess), `text` (xdotool/wtype after 150ms delay).

### Config location

`~/.config/keymenu/config.toml` — reloaded on every toggle (no daemon restart needed).

### Logging

All errors go to `~/.local/share/keymenu/keymenu.log`. Config errors fall back to last valid config; action errors are silent. The window must always respond to Escape.

## Key Design Constraints

- **No external Python dependencies** at runtime — stdlib only (`tomllib`, `subprocess`, `socket`, `pathlib`)
- **GTK4 via PyGObject** for the UI
- **GNOME/Wayland only** — focus-or-launch uses `gdbus` calls to `org.gnome.Shell`
- Config keys must be exactly one character; leaf nodes require both `action` and `value`
- `text` action: window closes first, then types after 150ms to restore focus
- `e` key opens config in nvim; if `e` is taken as a shortcut, this moves to `Ctrl+E`

## Entry Points (pyproject.toml)

```toml
[project.scripts]
keymenu = "keymenu.daemon:main"
keymenu-toggle = "keymenu.toggle:main"
```
