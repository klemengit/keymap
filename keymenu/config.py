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
class Command:
    """A named action without a shortcut key — searchable via fuzzy find."""

    label: str
    action: str  # 'url' | 'app' | 'shell' | 'text'
    value: str


@dataclass
class Settings:
    terminal: str = "alacritty"
    font: str = "Monospace 13"
    width: int = 420
    desktop_apps: bool = True
    exclude_apps: list[str] = field(default_factory=list)


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

    _RESERVED = {"label", "action", "value"}

    if "action" in data or "value" in data:
        # Leaf node
        if "action" not in data:
            raise ConfigError(f"Leaf node missing 'action' at {path}")
        if "value" not in data:
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

    # Group node — children are single-character sub-keys
    children: dict[str, ShortcutNode] = {
        k: v for k, v in data.items() if k not in _RESERVED and isinstance(v, dict)
    }
    if not children:
        raise ConfigError(
            f"Node at {path} is neither a leaf (missing 'action'+'value') "
            "nor a group (no single-character child tables found)"
        )
    result: dict[str, ShortcutNode] = {}
    for child_key, child_data in children.items():
        child_path = f"{path}.{child_key}"
        result[child_key] = _parse_node(child_key, child_data, child_path)
    return ShortcutGroup(label=label, shortcuts=result)


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
    if "desktop_apps" in raw:
        v = raw["desktop_apps"]
        if not isinstance(v, bool):
            raise ConfigError("settings.desktop_apps must be a boolean")
        settings.desktop_apps = v
    if "exclude_apps" in raw:
        v = raw["exclude_apps"]
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            raise ConfigError("settings.exclude_apps must be a list of strings")
        settings.exclude_apps = v
    return settings


def _parse_commands(raw_commands: list) -> list[Command]:
    """Parse the [[commands]] array-of-tables section."""
    if not isinstance(raw_commands, list):
        raise ConfigError("'commands' must be an array of tables ([[commands]])")
    commands: list[Command] = []
    for i, cmd in enumerate(raw_commands):
        loc = f"commands[{i}]"
        if not isinstance(cmd, dict):
            raise ConfigError(f"Each command must be a table at {loc}")
        for required in ("label", "action", "value"):
            if required not in cmd:
                raise ConfigError(f"Command missing '{required}' at {loc}")
        label = cmd["label"]
        action = cmd["action"]
        value = cmd["value"]
        if not isinstance(label, str):
            raise ConfigError(f"'label' must be a string at {loc}")
        if not isinstance(action, str) or action not in VALID_ACTIONS:
            raise ConfigError(
                f"Unknown action '{action}' at {loc}. "
                f"Valid actions: {', '.join(sorted(VALID_ACTIONS))}"
            )
        if not isinstance(value, str):
            raise ConfigError(f"'value' must be a string at {loc}")
        commands.append(Command(label=label, action=action, value=value))
    return commands


def load_config(
    path: Path = CONFIG_PATH,
) -> tuple[Settings, dict[str, ShortcutNode], list[Command]]:
    """Load and validate the keymenu config file.

    Returns:
        A tuple of (Settings, shortcuts_tree, commands) where shortcuts_tree
        maps single-character keys to ShortcutNode instances, and commands is
        a list of named actions accessible via fuzzy search (no shortcut key).

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

    commands = _parse_commands(raw.get("commands", []))

    return settings, tree, commands
