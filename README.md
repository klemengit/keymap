# keymenu

A lightweight GNOME/Wayland daemon that displays a keyboard-driven shortcut tree on a global hotkey. Press `Super+K`, navigate nested menus with single keypresses, and fire actions: open URLs, launch or focus apps, run shell commands, or paste text at the cursor. Inspired by Neovim's which-key plugin, but system-wide.

## Requirements

- Python 3.12+
- GTK4 via PyGObject
- GNOME on Wayland

Install system dependencies if missing:

```bash
# Debian/Ubuntu
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 wl-clipboard

# Fedora
sudo dnf install python3-gobject gtk4 wl-clipboard

# Arch
sudo pacman -S python-gobject gtk4 wl-clipboard
```

`wl-clipboard` is required for the `text` action (copies text to clipboard). `xdotool` is used as a fallback on X11.

## Installation

```bash
git clone <repo-url>
cd keymenu
./install.sh
```

The installer will:
1. Install the package in editable mode (via `uv` or `pip`)
2. Copy `config.example.toml` to `~/.config/keymenu/config.toml` if no config exists
3. Create an XDG autostart entry so the daemon runs on login
4. Register `Super+K` as a GNOME custom keyboard shortcut

Start the daemon immediately (no logout required):

```bash
~/.local/bin/keymenu &
```

## Usage

| Key | Action |
|-----|--------|
| `Super+K` | Open the menu |
| Any defined key | Navigate into a group or execute an action |
| `Esc` / `Backspace` | Go back one level; close at root |
| `e` (or `Ctrl+E`) | Open config in nvim |
| `?` | Show help overlay |

## Configuration

Config file: `~/.config/keymenu/config.toml`. Changes take effect on every toggle -- no restart needed.

```toml
[settings]
terminal = "alacritty"   # terminal used to open nvim
font     = "Monospace 13"
width    = 420

# Group (has children, no action)
[shortcuts.g]
label = "GitHub"

[shortcuts.g.r]
label  = "My Repo"
action = "url"
value  = "https://github.com/username/myrepo"

# Leaf nodes (has action + value)
[shortcuts.t]
label  = "Terminal"
action = "app"
value  = "kitty"

[shortcuts.s]
label  = "Search"
action = "shell"
value  = "xdg-open https://google.com"

[shortcuts.p]
label  = "Paste signature"
action = "text"
value  = "Jane Doe\njane@example.com"
```

### Action types

| Action | Behavior |
|--------|----------|
| `url` | Opens URL via `xdg-open`. Best-effort GNOME focus of the browser window. |
| `app` | Focus the app if already running, otherwise launch it. |
| `shell` | Run a shell command (non-blocking subprocess). |
| `text` | Copy text to clipboard via `wl-copy` (GNOME/Wayland). Falls back to `xdotool` on X11. |

## Changing the hotkey

Edit `HOTKEY` at the top of `install.sh`, then re-run:

```bash
./install.sh
```

## Updating after code changes

The package is installed in editable mode, so source changes apply immediately. Restart the daemon to pick them up:

```bash
pkill -f keymenu.daemon && ~/.local/bin/keymenu &
```

## Project structure

```
keymenu/
  daemon.py   — GTK4 app, Unix socket server (/tmp/keymenu.sock)
  toggle.py   — sends TOGGLE to socket (called by the hotkey)
  config.py   — TOML loader and validator
  window.py   — GTK4 window UI
  actions.py  — action executors (url, app, shell, text)
```

Logs: `~/.local/share/keymenu/keymenu.log`
