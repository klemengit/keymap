#!/usr/bin/env bash
# keymenu installer
# Sets up autostart, registers a GNOME global shortcut, and installs the package.
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — change these if you want a different hotkey
# ---------------------------------------------------------------------------
HOTKEY="<Alt>space"
HOTKEY_NAME="keymenu"
KEYBINDING_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/keymenu/"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "  --> $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================="
echo "  keymenu installer"
echo "=============================="
echo

# ---------------------------------------------------------------------------
# 1. Check / install Python + GTK bindings
# ---------------------------------------------------------------------------
echo "Step 1: Checking Python GTK bindings..."

if python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" 2>/dev/null; then
    info "python3-gi (PyGObject) with GTK 4 is available."
else
    echo
    echo "python3-gi or GTK 4 typelibs are missing."
    echo "Install them with one of the following commands:"
    echo
    echo "  Debian/Ubuntu:  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0"
    echo "  Fedora:         sudo dnf install python3-gobject gtk4"
    echo "  Arch:           sudo pacman -S python-gobject gtk4"
    echo
    read -rp "Continue anyway? [y/N] " ans
    [[ "${ans,,}" == "y" ]] || exit 1
fi

# ---------------------------------------------------------------------------
# 2. Install the keymenu package
# ---------------------------------------------------------------------------
echo
echo "Step 2: Installing keymenu..."

if command -v uv &>/dev/null; then
    info "Using uv..."
    uv pip install -e "$SCRIPT_DIR"
    # uv installs into the project venv; symlink into ~/.local/bin so GNOME can find the binaries
    mkdir -p "$HOME/.local/bin"
    ln -sf "$SCRIPT_DIR/.venv/bin/keymenu"        "$HOME/.local/bin/keymenu"
    ln -sf "$SCRIPT_DIR/.venv/bin/keymenu-toggle" "$HOME/.local/bin/keymenu-toggle"
elif command -v pip3 &>/dev/null; then
    info "Using pip3..."
    pip3 install --user -e "$SCRIPT_DIR"
elif command -v pip &>/dev/null; then
    info "Using pip..."
    pip install --user -e "$SCRIPT_DIR"
else
    die "Neither uv nor pip found. Please install pip or uv first."
fi

export PATH="$HOME/.local/bin:$PATH"
KEYMENU_BIN="$(command -v keymenu 2>/dev/null || echo "$HOME/.local/bin/keymenu")"
TOGGLE_BIN="$(command -v keymenu-toggle 2>/dev/null || echo "$HOME/.local/bin/keymenu-toggle")"
info "keymenu binary: $KEYMENU_BIN"
info "keymenu-toggle binary: $TOGGLE_BIN"

# ---------------------------------------------------------------------------
# 3. Copy example config if none exists
# ---------------------------------------------------------------------------
echo
echo "Step 3: Setting up config..."

CONFIG_DIR="$HOME/.config/keymenu"
CONFIG_FILE="$CONFIG_DIR/config.toml"
mkdir -p "$CONFIG_DIR"

if [[ -f "$CONFIG_FILE" ]]; then
    info "Config already exists at $CONFIG_FILE — skipping."
else
    cp "$SCRIPT_DIR/config.example.toml" "$CONFIG_FILE"
    info "Created $CONFIG_FILE from example."
    info "Edit it to add your own shortcuts!"
fi

# ---------------------------------------------------------------------------
# 4. Create XDG autostart entry
# ---------------------------------------------------------------------------
echo
echo "Step 4: Creating autostart entry..."

AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/keymenu.desktop"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=keymenu
Comment=Keyboard-driven shortcut tree daemon
Exec=$KEYMENU_BIN
Icon=input-keyboard
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF

info "Created $AUTOSTART_FILE"

# ---------------------------------------------------------------------------
# 5. Register GNOME custom keyboard shortcut (Super+Space → keymenu-toggle)
# ---------------------------------------------------------------------------
echo
echo "Step 5: Registering GNOME keyboard shortcut ($HOTKEY → keymenu-toggle)..."

# Read existing custom keybindings list
EXISTING="$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || echo "@as []")"

# Check if our binding path is already in the list
if echo "$EXISTING" | grep -qF "$KEYBINDING_PATH"; then
    info "Keybinding path already registered."
else
    # Append our path to the list
    if [[ "$EXISTING" == "@as []" || "$EXISTING" == "[]" ]]; then
        NEW_LIST="['$KEYBINDING_PATH']"
    else
        # Strip trailing ] and append
        NEW_LIST="${EXISTING%]}, '$KEYBINDING_PATH']"
    fi
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW_LIST"
    info "Registered keybinding path."
fi

GSETTINGS_BASE="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
gsettings set "$GSETTINGS_BASE:$KEYBINDING_PATH" name    "$HOTKEY_NAME"
gsettings set "$GSETTINGS_BASE:$KEYBINDING_PATH" command "$TOGGLE_BIN"
gsettings set "$GSETTINGS_BASE:$KEYBINDING_PATH" binding "$HOTKEY"

info "Shortcut registered: $HOTKEY → $TOGGLE_BIN"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
echo "=============================="
echo "  Installation complete!"
echo "=============================="
echo
echo "Next steps:"
echo
echo "  1. Start the daemon now (no need to log out):"
echo "     $KEYMENU_BIN &"
echo
echo "  2. Press $HOTKEY to open keymenu."
echo
echo "  3. On your next login the daemon will start automatically via autostart."
echo
echo "  4. Edit your shortcuts:"
echo "     $CONFIG_FILE"
echo "     (or press 'e' inside keymenu to open it in nvim)"
echo
