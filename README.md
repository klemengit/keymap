# keymenu

A lightweight GNOME/Wayland daemon that displays a keyboard-driven shortcut tree on a global hotkey. Press `Alt+Space`, navigate nested menus with single keypresses, and fire actions: open URLs, launch or focus apps, run shell commands, or paste text at the cursor. Inspired by Neovim's which-key plugin, but system-wide.

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
4. Register `Alt+Space` as a GNOME custom keyboard shortcut

> **Note:** `Alt+Space` is also used by GNOME for the window menu. If there is a conflict, GNOME may disable your binding when you dismiss the conflict dialog. Re-run `install.sh` to restore it, or change `HOTKEY` at the top of `install.sh` to something like `<Super>space` before installing.

Start the daemon immediately (no logout required):

```bash
~/.local/bin/keymenu &
```

## Usage

| Key | Action |
|-----|--------|
| `Alt+Space` | Open the menu |
| Any defined key | Navigate into a group or execute an action |
| Any other key | Open fuzzy search pre-filled with that character |
| `/` | Open fuzzy search (empty) |
| `Esc` / `Backspace` | Go back one level; close at root |
| `Ctrl+E` | Open config in nvim |
| `?` | Show help overlay |

## Fuzzy Search

Press `/` or any key that isn't a defined shortcut to open the fuzzy search. Results are drawn from three sources, in priority order:

1. **Shortcuts** — all leaves from your `[shortcuts]` tree (shown with their key path, e.g. `g›r`)
2. **Commands** — items from `[[commands]]` in your config (no shortcut key required)
3. **Installed apps** — auto-discovered from desktop files (covers regular, Flatpak, and Snap installs)

Navigate results with `↑`/`↓`, execute with `Enter`, cancel with `Esc`.

## Configuration

Config file: `~/.config/keymenu/config.toml`. Changes take effect on every toggle — no restart needed.

### Settings

```toml
[settings]
terminal     = "alacritty"  # terminal used to open nvim (default: alacritty)
font         = "Monospace 13"
width        = 420
desktop_apps = true         # include installed apps in fuzzy search (default: true)
exclude_apps = ["Gedit", "org.gnome.TextEditor"]  # exclude by Name or .desktop filename stem
```

### Shortcuts

Shortcuts are single-character keys that navigate a nested tree. A node is either a **group** (has children) or a **leaf** (has `action` + `value`).

```toml
# Group — press 'g' to enter this submenu
[shortcuts.g]
label = "GitHub"

# Leaf — press 'r' inside the 'g' group to open the URL
[shortcuts.g.r]
label  = "My Repo"
action = "url"
value  = "https://github.com/username/myrepo"

# Top-level leaf
[shortcuts.t]
label  = "Terminal"
action = "app"
value  = "kitty"

[shortcuts.s]
label  = "Search the web"
action = "shell"
value  = "xdg-open https://google.com"

[shortcuts.p]
label  = "Paste signature"
action = "text"
value  = "Jane Doe\njane@example.com"
```

### Commands

Commands are named actions with no shortcut key. They appear in fuzzy search results but not in the shortcut tree. Useful for things you want accessible but don't need a dedicated key for.

```toml
[[commands]]
label  = "Hacker News"
action = "url"
value  = "https://news.ycombinator.com"

[[commands]]
label  = "Restart NetworkManager"
action = "shell"
value  = "sudo systemctl restart NetworkManager"

[[commands]]
label  = "My work email"
action = "text"
value  = "jane@example.com"
```

### Action types

| Action | Behavior |
|--------|----------|
| `url` | Opens URL via `xdg-open`. Best-effort GNOME focus of the browser window. |
| `app` | Focus the app if already running, otherwise launch it. Uses GNOME Shell DBus. |
| `shell` | Run a shell command non-blocking. |
| `text` | Copy text to clipboard via `wl-copy` (GNOME/Wayland). Falls back to `xdotool type` on X11. |

## Changing the hotkey

Edit `HOTKEY` at the top of `install.sh`, then re-run:

```bash
./install.sh
```

## Restarting the daemon

The config reloads automatically on every toggle, so you only need to restart for code changes:

```bash
pkill -f keymenu && ~/.local/bin/keymenu &
```

## Project structure

```
keymenu/
  daemon.py   — GTK4 app, Unix socket server (/tmp/keymenu.sock)
  toggle.py   — sends TOGGLE to socket (called by the hotkey)
  config.py   — TOML loader and validator
  window.py   — GTK4 window UI and fuzzy search
  actions.py  — action executors (url, app, shell, text)
```

Logs: `~/.local/share/keymenu/keymenu.log`
