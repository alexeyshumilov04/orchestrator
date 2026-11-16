"""Композиционный КОРЕНЬ: единственное место, где ядро и агентный слой связываются.

Импортируется точками входа (`main.py`, `api.py`) ДО вызова координатора.
`agents/runner.py` импортируется ЛЕНИВО (внутри фабрики), поэтому даже этот
модуль не тянет агентный слой, пока режим `staged` не запрошен.

Без этого импорта `execution.stage_mode: staged` деградирует в монолитный контур
(безопасный fallback) — `core/` не знает про `agents/` (R2 регламента).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.execution import register_executor          # noqa: E402


def _staged_factory(coord, *, decisions=None, run_id: str = "") -> object:
    """Ленивая фабрика исполнителя «staged» (агенты + гейты)."""
    from agents.runner import StageRunner              # лениво: agents не тянется зря
    return StageRunner(coord, decisions=decisions, run_id=run_id)


def wire() -> None:
    """Зарегистрировать исполнителей пайплайна (идемпотентно)."""
    register_executor("staged", _staged_factory)


wire()
