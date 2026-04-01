# keymenu — Product Requirements Document

## Overview

`keymenu` is a lightweight Linux desktop utility for GNOME + Wayland that provides
instant, keyboard-driven navigation through a user-defined tree of shortcuts. The user
triggers it with a single global hotkey, then navigates nested menus by pressing single
keys, ultimately firing an action (open URL, run shell command, open app, paste text).
It is inspired by Neovim's which-key plugin but works system-wide as a standalone daemon.

---

## Goals

- Lightning fast: window appears instantly (daemon model, no cold start)
- Zero mouse usage: everything is keyboard-driven
- Simple to configure: one TOML file, human-readable, no programming required
- Arbitrarily deep shortcut trees (like Neovim leader key chains)
- Smart focus-or-launch: if the target app/URL is already open, focus it instead of
  opening a new instance
- Easy config editing: a dedicated key opens the config file in nvim

---

## Technology Stack

- **Language**: Python 3.11+
- **UI**: GTK4 via PyGObject
- **Config format**: TOML (parsed with `tomllib`, stdlib in Python 3.11+)
- **IPC**: Unix domain socket (for the CLI toggle command to signal the daemon)
- **Focus-or-launch**: `gdbus` / GLib DBus calls to GNOME Shell where possible,
  with graceful fallback to plain launch
- **Autostart**: XDG autostart `.desktop` file
- **Global hotkey**: Registered as a GNOME custom keyboard shortcut via `gsettings`,
  pointing to a small `keymenu-toggle` CLI command

---

## Project Structure

```
keymenu/
├── keymenu/
│   ├── __init__.py
│   ├── daemon.py        # GTK4 app + window, IPC socket server
│   ├── toggle.py        # CLI entrypoint: sends toggle signal to daemon
│   ├── config.py        # TOML loader + tree parser
│   ├── actions.py       # Action executors (url, shell, app, text)
│   └── window.py        # GTK4 window UI logic
├── config.example.toml  # Example config with comments
├── install.sh           # Sets up autostart, gsettings shortcut, installs deps
├── pyproject.toml       # Project metadata + entry points
└── README.md
```

---

## Daemon Lifecycle

1. On login, `keymenu` daemon starts via XDG autostart
2. It loads `~/.config/keymenu/config.toml`
3. It builds the GTK4 window but keeps it hidden
4. It listens on a Unix socket at `/tmp/keymenu.sock`
5. When `keymenu-toggle` is called (by the global hotkey), it sends a `TOGGLE` message
   to the socket
6. The daemon shows the window, resets to the root of the shortcut tree
7. On action execution or Escape, the window hides again
8. Config is reloaded each time the window is shown (so edits take effect immediately
   without restarting the daemon)

---

## Window Design

- Centered on screen, floating, no window decorations (borderless)
- Dark background, monospace font, high contrast
- Always on top, does not appear in taskbar or Alt+Tab
- Shows the current navigation path at the top (breadcrumb), e.g. `> g > p`
- Lists available keys and their labels in a clean grid or list:
  ```
  g  GitHub
  t  Terminal
  n  Notes
  ─────────────
  ?  help   Esc  back/close
  ```
- Updates instantly on each keypress (no Enter required)
- Pressing a key that does not exist in the current node: flash a subtle error indicator,
  do not close
- The window width adjusts to content, with a sensible minimum and maximum width
- Subtle animation on show/hide (fade or slide, very short, <120ms)

---

## Keyboard Behaviour Inside the Window

| Key         | Behaviour                                              |
|-------------|--------------------------------------------------------|
| Any defined key | Navigate into that node or execute its action     |
| `Escape`    | Go one level up; if at root, close/hide the window     |
| `Backspace` | Same as Escape                                         |
| `e`         | Open `~/.config/keymenu/config.toml` in nvim (in a new terminal window). If `e` is also defined as a shortcut in the current node, the shortcut takes priority and this binding is moved to `Ctrl+E` |
| `?`         | Toggle a help overlay showing all keys at current level with descriptions |
| Undefined key | Flash indicator, ignore                              |

---

## TOML Config Format

The config file lives at `~/.config/keymenu/config.toml`.

### Schema

Each node in the tree is either a **group** (has children) or a **leaf** (has an action).

```toml
# Top-level settings
[settings]
terminal = "gnome-terminal"   # terminal emulator used to open nvim and shell actions
font = "JetBrains Mono 13"    # GTK font string
width = 420                   # window width in pixels (optional, default 420)

# Shortcuts are defined under [shortcuts]
# Each key is a single character (letter, digit, or symbol)

[shortcuts.g]
label = "GitHub"
# No action = this is a group; define children below

[shortcuts.g.r]
label = "My Repo"
action = "url"
value = "https://github.com/username/myrepo"

[shortcuts.g.p]
label = "Pull Requests"
action = "url"
value = "https://github.com/pulls"

[shortcuts.g.n]
label = "New Issue"
action = "url"
value = "https://github.com/username/myrepo/issues/new"

[shortcuts.t]
label = "Terminal"
action = "app"
value = "kitty"
# app action: focus existing window if running, launch if not

[shortcuts.n]
label = "Notes"
action = "app"
value = "obsidian"

[shortcuts.s]
label = "Search Web"
action = "shell"
value = "xdg-open 'https://google.com'"

[shortcuts.c]
label = "Copy Git Branch"
action = "shell"
value = "git branch --show-current | wc -l | xclip -selection clipboard"

[shortcuts.h]
label = "Home Directory"
action = "shell"
value = "nautilus ~"

[shortcuts.p]
label = "Paste Signature"
action = "text"
value = "John Doe\njohn@example.com\n+1 555 0100"
# text action: types/pastes the value at the current cursor position
```

### Action Types

| Action  | Behaviour |
|---------|-----------|
| `url`   | Open `value` in the default browser. If the browser is already focused on that URL, bring it to front (best effort via GNOME DBus). Fallback: `xdg-open value` |
| `app`   | Focus the running app if found, otherwise launch it. App matching is by process name or `.desktop` file name. Value is the app binary name or `.desktop` name (e.g. `kitty`, `obsidian`, `com.obsidian.Obsidian`) |
| `shell` | Run `value` as a shell command via `subprocess`. Non-blocking. |
| `text`  | Type `value` at the current cursor using `xdotool type` or `wtype` (Wayland-compatible). Window closes first, then text is typed after a short delay (150ms) to allow focus to return. |

### Validation

On startup (and on each reload), the config is validated:
- Each shortcut key must be exactly one character
- Each leaf node must have both `action` and `value`
- Each group node must have at least one child under `shortcuts`
- Unknown action types produce a clear error message
- On any config error, the daemon logs the error and falls back to the last valid config
  (or shows an error state in the window if no valid config has been loaded yet)

---

## Focus-or-Launch Behaviour

### For `app` actions
1. Query running applications via GLib / `gio` or by scanning `/proc`
2. If found, call GNOME Shell DBus `org.gnome.Shell` to activate the window
3. If DBus focus fails, fall back to `subprocess.Popen([value])`
4. If not found, launch via `subprocess.Popen([value])`

### For `url` actions
1. Open with `xdg-open value` (always — reliable cross-browser behaviour)
2. Best-effort focus: attempt to raise the default browser window via GNOME DBus
   before opening, so the URL opens in the existing browser session

### Fallback policy
All focus attempts are best-effort. If they fail, always fall back to a plain launch.
Never crash or show an error to the user for focus failures — just launch.

---

## Installation (`install.sh`)

The install script must:

1. Install Python dependencies: `pip install pygobject` (or guide user to
   `sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0`)
2. Copy `~/.config/keymenu/config.toml` from `config.example.toml` if it doesn't exist
3. Create XDG autostart entry at `~/.config/autostart/keymenu.desktop`
4. Register GNOME custom shortcut via `gsettings` binding `Super+Space` (or another
   key — make it a variable at the top of the script) to run `keymenu-toggle`
5. Print clear next steps: log out and back in, or run `keymenu &` manually to start now

---

## Entry Points (pyproject.toml)

```toml
[project.scripts]
keymenu = "keymenu.daemon:main"
keymenu-toggle = "keymenu.toggle:main"
```

---

## Error Handling & Logging

- All errors logged to `~/.local/share/keymenu/keymenu.log`
- Config parse errors: log and fall back to last good config, or show inline error
  in the window
- Socket errors: log and attempt to recreate socket
- Action execution errors: log silently, never crash the daemon
- The window should never be in an unresponsive state — Escape always closes it

---

## Non-Goals (explicitly out of scope)

- Mouse support inside the window
- Search/fuzzy filtering (this is a key-sequence tool, not a launcher)
- Sync or cloud config
- GUI config editor
- Support for non-GNOME desktops (though the core may work on other compositors)
- Theming beyond the settings in config.toml

---

## Example User Flow

1. User presses `Super+Space` → keymenu window appears instantly at screen center
2. Window shows root-level shortcuts: `g GitHub`, `t Terminal`, `n Notes`, ...
3. User presses `g` → breadcrumb updates to `> g`, window now shows GitHub shortcuts:
   `r My Repo`, `p Pull Requests`, `n New Issue`
4. User presses `p` → browser opens (or focuses) GitHub Pull Requests page, window hides
5. User presses `Super+Space` again → back at root
6. User presses `Escape` → window hides
