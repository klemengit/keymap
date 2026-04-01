"""GTK4 window for keymenu.

The window is created once and shown/hidden as needed; it is never destroyed
and recreated. Config is reloaded on every show_menu() call.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Gdk, Pango  # noqa: E402

if TYPE_CHECKING:
    from keymenu.config import Settings, ShortcutNode

logger = logging.getLogger("keymenu.window")

CONFIG_PATH = Path.home() / ".config" / "keymenu" / "config.toml"

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = b"""
window {
    background-color: #1e1e2e;
    border-radius: 10px;
    border: 1px solid #45475a;
}

.keymenu-breadcrumb {
    color: #6c7086;
    font-size: 0.85em;
    padding: 6px 12px 2px 12px;
}

.keymenu-separator {
    color: #45475a;
    margin: 0 8px;
}

.keymenu-row {
    padding: 2px 12px;
}

.keymenu-key-badge {
    color: #cba6f7;
    background-color: #313244;
    border-radius: 4px;
    padding: 1px 6px;
    font-weight: bold;
    min-width: 18px;
}

.keymenu-label {
    color: #cdd6f4;
    padding-left: 8px;
}

.keymenu-group-indicator {
    color: #6c7086;
    padding-left: 4px;
}

.keymenu-footer {
    color: #585b70;
    font-size: 0.8em;
    padding: 4px 12px 8px 12px;
}

.keymenu-error-flash {
    border: 2px solid #f38ba8;
    border-radius: 10px;
}

.keymenu-help-key {
    color: #89b4fa;
    font-weight: bold;
    min-width: 24px;
}

.keymenu-help-label {
    color: #cdd6f4;
    padding-left: 6px;
}

.keymenu-help-action {
    color: #a6e3a1;
    padding-left: 6px;
    font-size: 0.85em;
}

.keymenu-help-overlay {
    background-color: #181825;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 8px;
    margin: 4px;
}
"""


# ---------------------------------------------------------------------------
# Main window class
# ---------------------------------------------------------------------------

class KeymenuWindow(Gtk.ApplicationWindow):
    """The keymenu floating shortcut-tree window."""

    def __init__(self, application: Gtk.Application) -> None:
        super().__init__(application=application)

        self._shortcuts_tree: dict[str, "ShortcutNode"] = {}
        self._settings: "Settings | None" = None
        self._nav_stack: list[tuple[str, dict[str, "ShortcutNode"]]] = []
        # Current node's shortcuts
        self._current_shortcuts: dict[str, "ShortcutNode"] = {}
        self._help_visible = False
        self._is_visible = False
        self._fade_timer_id: int | None = None
        # Optional callback invoked after the window finishes hiding
        self.on_hidden: "Callable[[], None] | None" = None  # noqa: F821

        self._setup_css()
        self._setup_window()
        self._build_ui()
        self._setup_key_controller()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _setup_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _setup_window(self) -> None:
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_default_size(420, -1)

        # Try gtk4-layer-shell for proper Wayland always-on-top behaviour.
        self._layer_shell_active = False
        try:
            gi.require_version("GtkLayerShell", "0.1")
            from gi.repository import GtkLayerShell  # type: ignore

            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(
                self, GtkLayerShell.KeyboardMode.EXCLUSIVE
            )
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, False)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, False)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, False)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, False)
            self._layer_shell_active = True
            logger.debug("gtk4-layer-shell active")
        except (ValueError, ImportError):
            # gtk4-layer-shell not available; no keep_above in GTK4 on Wayland.
            # The window will still appear on top when focused.
            logger.debug("gtk4-layer-shell not available, proceeding without always-on-top")

        # GTK4 doesn't have set_skip_taskbar_hint directly; set via startup_id
        # workaround is to just not show the window in the taskbar by design.
        # The window type hint equivalent in GTK4 is handled via the layer shell
        # (OVERLAY layer) on Wayland.

    def _build_ui(self) -> None:
        """Build the static parts of the UI. Dynamic content goes in _refresh_content."""
        # Root container — overlay lets us stack the help panel on top
        self._overlay = Gtk.Overlay()
        self.set_child(self._overlay)

        # Main vertical box
        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._overlay.set_child(self._main_box)

        # Breadcrumb
        self._breadcrumb = Gtk.Label(label="")
        self._breadcrumb.set_halign(Gtk.Align.START)
        self._breadcrumb.set_ellipsize(Pango.EllipsizeMode.END)
        self._breadcrumb.add_css_class("keymenu-breadcrumb")
        self._main_box.append(self._breadcrumb)

        # Top separator
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep1.add_css_class("keymenu-separator")
        self._main_box.append(sep1)

        # Shortcut list area (scrollable to handle large configs)
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_max_content_height(500)
        self._scroll.set_propagate_natural_height(True)
        self._main_box.append(self._scroll)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._scroll.set_child(self._list_box)

        # Bottom separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.add_css_class("keymenu-separator")
        self._main_box.append(sep2)

        # Footer
        self._footer = Gtk.Label(label="?  help    Esc  back/close    e  edit config")
        self._footer.set_halign(Gtk.Align.START)
        self._footer.add_css_class("keymenu-footer")
        self._main_box.append(self._footer)

        # Help overlay (initially hidden, added as overlay child)
        self._help_widget = self._build_help_widget()
        self._help_widget.set_visible(False)
        self._overlay.add_overlay(self._help_widget)

    def _build_help_widget(self) -> Gtk.Widget:
        """Build the help overlay panel."""
        frame = Gtk.Frame()
        frame.add_css_class("keymenu-help-overlay")
        frame.set_halign(Gtk.Align.FILL)
        frame.set_valign(Gtk.Align.FILL)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        title = Gtk.Label(label="Key Bindings")
        title.set_markup("<b>Key Bindings</b>")
        title.set_halign(Gtk.Align.START)
        box.append(title)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.append(sep)

        rows = [
            ("Any key", "Navigate / execute shortcut"),
            ("Esc / Backspace", "Go up one level; close if at root"),
            ("e / Ctrl+E", "Edit config in nvim"),
            ("?", "Toggle this help overlay"),
        ]
        for key_text, desc in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            k = Gtk.Label(label=key_text)
            k.add_css_class("keymenu-help-key")
            k.set_halign(Gtk.Align.START)
            k.set_width_chars(18)
            d = Gtk.Label(label=desc)
            d.add_css_class("keymenu-help-label")
            d.set_halign(Gtk.Align.START)
            row.append(k)
            row.append(d)
            box.append(row)

        frame.set_child(box)
        return frame

    # ------------------------------------------------------------------
    # Content refresh
    # ------------------------------------------------------------------

    def _refresh_content(self) -> None:
        """Rebuild the shortcut list for the current navigation level."""
        # Remove all existing rows
        while True:
            child = self._list_box.get_first_child()
            if child is None:
                break
            self._list_box.remove(child)

        # Update breadcrumb
        if self._nav_stack:
            path = " > ".join(label for label, _ in self._nav_stack)
            self._breadcrumb.set_text(f"> {path}")
        else:
            self._breadcrumb.set_text("")

        # Determine width from settings
        width = 420
        if self._settings is not None:
            width = self._settings.width
        self.set_default_size(width, -1)

        # Populate rows
        from keymenu.config import ShortcutGroup, ShortcutLeaf

        for key, node in sorted(self._current_shortcuts.items()):
            row = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=0,
            )
            row.add_css_class("keymenu-row")
            row.set_margin_top(2)
            row.set_margin_bottom(2)

            key_label = Gtk.Label(label=key)
            key_label.add_css_class("keymenu-key-badge")
            key_label.set_halign(Gtk.Align.CENTER)
            key_label.set_valign(Gtk.Align.CENTER)

            desc_label = Gtk.Label(label=node.label)
            desc_label.add_css_class("keymenu-label")
            desc_label.set_halign(Gtk.Align.START)
            desc_label.set_hexpand(True)

            row.append(key_label)
            row.append(desc_label)

            if isinstance(node, ShortcutGroup):
                indicator = Gtk.Label(label="›")
                indicator.add_css_class("keymenu-group-indicator")
                indicator.set_halign(Gtk.Align.END)
                row.append(indicator)
            elif isinstance(node, ShortcutLeaf):
                action_label = Gtk.Label(label=f"[{node.action}]")
                action_label.add_css_class("keymenu-help-action")
                action_label.set_halign(Gtk.Align.END)
                row.append(action_label)

            self._list_box.append(row)

        # Update footer to show whether 'e' is taken
        e_taken = "e" in self._current_shortcuts
        edit_hint = "Ctrl+E" if e_taken else "e"
        self._footer.set_text(
            f"?  help    Esc  back/close    {edit_hint}  edit config"
        )

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def _setup_key_controller(self) -> None:
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(
        self,
        controller: Gtk.EventControllerKey,
        keyval: int,
        keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        from keymenu.config import ShortcutGroup, ShortcutLeaf
        from keymenu.actions import execute_action

        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        # Escape / Backspace: go up or close
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_BackSpace):
            if self._nav_stack:
                _, parent_shortcuts = self._nav_stack.pop()
                self._current_shortcuts = parent_shortcuts
                self._refresh_content()
            else:
                self.hide_menu()
            return True

        # Help toggle
        if keyval == Gdk.KEY_question:
            self._toggle_help()
            return True

        # Edit config: Ctrl+E always works; plain 'e' only if not a shortcut
        e_taken = "e" in self._current_shortcuts
        if keyval == Gdk.KEY_e and (ctrl or not e_taken):
            self._open_config_in_editor()
            return True

        # Convert keyval to character
        char = chr(keyval) if 32 <= keyval <= 126 else None
        if char is None:
            return False  # pass through modifier keys, function keys, etc.

        node = self._current_shortcuts.get(char)

        if node is None:
            # Unknown key — flash the window border briefly
            self._flash_error()
            return True

        if isinstance(node, ShortcutGroup):
            self._nav_stack.append((char, self._current_shortcuts))
            self._current_shortcuts = node.shortcuts
            self._refresh_content()
            return True

        if isinstance(node, ShortcutLeaf):
            if node.action == "text":
                execute_action(node.action, node.value, hide_callback=self.hide_menu)
            else:
                self.hide_menu()
                execute_action(node.action, node.value)
            return True

        return False

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _open_config_in_editor(self) -> None:
        terminal = "gnome-terminal"
        if self._settings is not None:
            terminal = self._settings.terminal
        try:
            subprocess.Popen(
                [terminal, "--", "nvim", str(CONFIG_PATH)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            # Some terminals use -e instead of --
            try:
                subprocess.Popen(
                    [terminal, "-e", "nvim", str(CONFIG_PATH)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                logger.error("Failed to open config in editor: %s", exc)
        self.hide_menu()

    def _toggle_help(self) -> None:
        self._help_visible = not self._help_visible
        self._help_widget.set_visible(self._help_visible)

    # ------------------------------------------------------------------
    # Error flash
    # ------------------------------------------------------------------

    def _flash_error(self) -> None:
        """Briefly add an error CSS class to give visual feedback."""
        self.add_css_class("keymenu-error-flash")

        def _remove_flash() -> bool:
            self.remove_css_class("keymenu-error-flash")
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(250, _remove_flash)

    # ------------------------------------------------------------------
    # Show / hide with fade animation
    # ------------------------------------------------------------------

    def show_menu(
        self,
        shortcuts_tree: "dict[str, ShortcutNode]",
        settings: "Settings",
    ) -> None:
        """Reset to root, reload content, and present the window."""
        self._shortcuts_tree = shortcuts_tree
        self._settings = settings
        self._nav_stack = []
        self._current_shortcuts = shortcuts_tree
        self._help_visible = False
        self._help_widget.set_visible(False)

        self._refresh_content()

        # Apply font from settings
        if settings is not None:
            # Update CSS with font
            font_css = f"window {{ font-family: monospace; }}".encode()
            # The font string from GTK is like "Monospace 13" — parse it
            parts = settings.font.rsplit(" ", 1)
            font_family = parts[0] if len(parts) == 2 else settings.font
            font_size = parts[1] if len(parts) == 2 else "13"
            font_css = (
                f"* {{ font-family: '{font_family}', monospace; "
                f"font-size: {font_size}pt; }}"
            ).encode()
            provider = Gtk.CssProvider()
            provider.load_from_data(font_css)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
            )

        self._cancel_fade()
        self.set_opacity(0.0)
        self._is_visible = True
        self.present()
        self._fade_in()

    def hide_menu(self) -> None:
        """Fade out and hide the window."""
        if not self._is_visible:
            return
        self._is_visible = False
        self._cancel_fade()
        self._fade_out()

    def _cancel_fade(self) -> None:
        if self._fade_timer_id is not None:
            GLib.source_remove(self._fade_timer_id)
            self._fade_timer_id = None

    def _fade_in(self, step: float = 0.0) -> None:
        step = min(step + 0.15, 1.0)
        self.set_opacity(step)
        if step < 1.0:
            self._fade_timer_id = GLib.timeout_add(15, self._fade_in, step)
        else:
            self._fade_timer_id = None

    def _fade_out(self, step: float = 1.0) -> None:
        step = max(step - 0.2, 0.0)
        self.set_opacity(step)
        if step > 0.0:
            self._fade_timer_id = GLib.timeout_add(15, self._fade_out, step)
        else:
            self._fade_timer_id = None
            self.set_visible(False)
            if self.on_hidden is not None:
                try:
                    self.on_hidden()
                except Exception as exc:
                    logger.debug("on_hidden callback failed: %s", exc)
