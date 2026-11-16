"""Конфигурация сервиса: единая точка чтения config.yaml и разрешения путей.

Относительные пути разрешаются от корня сервиса (папка, где лежит main.py).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

SERVICE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SERVICE_ROOT / "config.yaml"
LOCAL_CONFIG_NAME = "config.local.yaml"


class ConfigError(RuntimeError):
    pass


class Config:
    """Обёртка над словарём конфигурации: доступ через точку + разрешение путей."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self._data = data
        self.source_path = path
        self._overrides: dict[str, Any] = {}

    # -- доступ -------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        node = self.get(name, {})
        return node if isinstance(node, dict) else {}

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    # -- пути ---------------------------------------------------------------
    def resolve(self, value: str | os.PathLike[str] | None, *,
                base: Path | None = None) -> Path:
        if value is None:
            return SERVICE_ROOT
        p = Path(str(value))
        if p.is_absolute():
            return p
        return (base or SERVICE_ROOT) / p

    def path(self, dotted: str, default: str | None = None) -> Path:
        return self.resolve(self.get(dotted, default))

    def ensure_dir(self, p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    # -- изменение и сохранение --------------------------------------------
    def set(self, dotted: str, value: Any) -> None:
        """Установить значение по точечному пути (и запомнить как переопределение)."""
        parts = dotted.split(".")
        node: Any = self._data
        over: Any = self._overrides
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
            if not isinstance(over.get(part), dict):
                over[part] = {}
            over = over[part]
        node[parts[-1]] = value
        over[parts[-1]] = value

    def apply_overrides(self, overrides: dict) -> None:
        """Наложить переопределения (из config.local.yaml) на базовую конфигурацию."""
        self._overrides = dict(overrides or {})
        self._merge(self._data, self._overrides)

    @staticmethod
    def _merge(base: dict, over: dict) -> None:
        for key, value in (over or {}).items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                Config._merge(base[key], value)
            else:
                base[key] = value

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        """Сохранить ПЕРЕОПРЕДЕЛЕНИЯ в config.local.yaml (базовый config.yaml не трогаем)."""
        target = Path(path) if path else (self.source_path.parent / LOCAL_CONFIG_NAME)
        with target.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(self._overrides or {}, fh, allow_unicode=True, sort_keys=False)
        return target


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    cfg_path = Path(path).resolve() if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(f"Конфигурация не найдена: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError("config.yaml должен содержать словарь верхнего уровня")
    cfg = Config(data, cfg_path)
    local = cfg_path.parent / LOCAL_CONFIG_NAME
    if local.exists():
        try:
            overrides = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            overrides = {}
        if isinstance(overrides, dict):
            cfg.apply_overrides(overrides)
    return cfg
