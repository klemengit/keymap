"""Config loader for keymenu.

Reads ~/.config/keymenu/config.toml using stdlib tomllib, validates the
shortcut tree, and returns typed dataclasses.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

CONFIG_PATH = Path.home() / ".config" / "keymenu" / "config.toml"

VALID_ACTIONS = frozenset({"url", "app", "shell", "text"})


@dataclass
class Settings:
    terminal: str = "gnome-terminal"
    font: str = "Monospace 13"
    width: int = 420


@dataclass
class ShortcutLeaf:
    label: str
    action: str  # 'url' | 'app' | 'shell' | 'text'
    value: str


@dataclass
class ShortcutGroup:
    label: str
    shortcuts: dict[str, "ShortcutNode"] = field(default_factory=dict)


ShortcutNode = Union[ShortcutGroup, ShortcutLeaf]


class ConfigError(Exception):
    """Raised when the config file is invalid."""


def _parse_node(key: str, data: dict, path: str) -> ShortcutNode:
    """Recursively parse a single shortcut node from raw TOML data."""
    if len(key) != 1:
        raise ConfigError(
            f"Shortcut key must be exactly one character, got '{key}' at {path}"
        )

    label = data.get("label", key)
    if not isinstance(label, str):
        raise ConfigError(f"'label' must be a string at {path}")

    has_action = "action" in data
    has_value = "value" in data
    has_shortcuts = "shortcuts" in data

    if has_action or has_value:
        # Leaf node
        if not has_action:
            raise ConfigError(f"Leaf node missing 'action' at {path}")
        if not has_value:
            raise ConfigError(f"Leaf node missing 'value' at {path}")
        action = data["action"]
        if action not in VALID_ACTIONS:
            raise ConfigError(
                f"Unknown action '{action}' at {path}. "
                f"Valid actions: {', '.join(sorted(VALID_ACTIONS))}"
            )
        value = data["value"]
        if not isinstance(value, str):
            raise ConfigError(f"'value' must be a string at {path}")
        return ShortcutLeaf(label=label, action=action, value=value)

    elif has_shortcuts:
        # Group node
        raw_shortcuts = data["shortcuts"]
        if not isinstance(raw_shortcuts, dict):
            raise ConfigError(f"'shortcuts' must be a table at {path}")
        if not raw_shortcuts:
            raise ConfigError(f"Group node must have at least one child at {path}")

        children: dict[str, ShortcutNode] = {}
        for child_key, child_data in raw_shortcuts.items():
            child_path = f"{path}.shortcuts.{child_key}"
            if not isinstance(child_data, dict):
                raise ConfigError(
                    f"Shortcut entry must be a table at {child_path}"
                )
            children[child_key] = _parse_node(child_key, child_data, child_path)

        return ShortcutGroup(label=label, shortcuts=children)

    else:
        raise ConfigError(
            f"Node at {path} is neither a leaf (missing 'action'+'value') "
            "nor a group (missing 'shortcuts')"
        )


def _parse_settings(raw: dict) -> Settings:
    """Parse the [settings] section with defaults."""
    settings = Settings()
    if "terminal" in raw:
        v = raw["terminal"]
        if not isinstance(v, str):
            raise ConfigError("settings.terminal must be a string")
        settings.terminal = v
    if "font" in raw:
        v = raw["font"]
        if not isinstance(v, str):
            raise ConfigError("settings.font must be a string")
        settings.font = v
    if "width" in raw:
        v = raw["width"]
        if not isinstance(v, int):
            raise ConfigError("settings.width must be an integer")
        settings.width = v
    return settings


def load_config(
    path: Path = CONFIG_PATH,
) -> tuple[Settings, dict[str, ShortcutNode]]:
    """Load and validate the keymenu config file.

    Returns:
        A tuple of (Settings, shortcuts_tree) where shortcuts_tree maps
        single-character keys to ShortcutNode instances.

    Raises:
        ConfigError: if the file is missing, unparseable, or invalid.
    """
    if not path.exists():
        raise ConfigError(
            f"Config file not found: {path}\n"
            "Run install.sh or create the file manually."
        )

    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML parse error in {path}: {exc}") from exc

    settings = _parse_settings(raw.get("settings", {}))

    raw_shortcuts = raw.get("shortcuts", {})
    if not isinstance(raw_shortcuts, dict):
        raise ConfigError("'shortcuts' must be a top-level table")

    tree: dict[str, ShortcutNode] = {}
    for key, data in raw_shortcuts.items():
        node_path = f"shortcuts.{key}"
        if not isinstance(data, dict):
            raise ConfigError(f"Shortcut entry must be a table at {node_path}")
        tree[key] = _parse_node(key, data, node_path)

    return settings, tree
