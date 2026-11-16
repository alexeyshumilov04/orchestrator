"""C5 — ГЕН воркфлоу: единица рендера tNavigator (узел → функции → параметры/объекты).

Ген описывает ОДИН узел = одну операцию (одна итерация группы для выбранного метода).
Узел рендерится в несколько элементов воркфлоу (`begin_wf_item`/`end_wf_item`).

Источник имён объектов и формул — ТАБЛИЦА ПЕРЕХОДОВ (данные, не код). Источник
параметров/доменов — правила функций (`<function>.rdf`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ObjectRef:
    """Ссылка на объект тНава внутри typed_object_name(obj_name=..., obj_type=...)."""

    obj_name: str
    obj_type: str = ""

    def is_empty(self) -> bool:
        return not self.obj_name and not self.obj_type


@dataclass(frozen=True)
class ParameterSpec:
    """Параметр функции: код, тип, домен значений, условие."""

    code: str
    type: str = "string"                 # string | integer | float | bool | date | struct
    domain: tuple = ()                   # перечисление возможных значений
    condition: tuple[str, ...] = ()      # условия (напр. "radius <= 1000")
    label: str = ""


@dataclass(frozen=True)
class FunctionRule:
    """Правило одной вычислительной функции тНава (из <function>.rdf)."""

    name: str
    template_path: Path
    parameters: tuple[ParameterSpec, ...] = ()
    creates: tuple[ObjectRef, ...] = ()
    uses: tuple[ObjectRef, ...] = ()
    code: str = ""                        # код функции (по умолчанию = name)


@dataclass
class FunctionGene:
    """Значения параметров + имена объектов для одного вызова функции."""

    function: str
    parameters: dict = field(default_factory=dict)   # {code: value}
    objects: dict = field(default_factory=dict)      # {role: ObjectRef}
    lists: dict = field(default_factory=dict)        # {code: [values]} — списки (file_names=…)
    replace: dict = field(default_factory=dict)      # {old_str: new_str} — точечная замена
    formula: str | None = None


@dataclass
class NodeGene:
    """Узел воркфлоу: группа операций + итерация + метод + функции."""

    group: str
    iteration: int = 1
    method: str = ""
    stage: str = ""                       # этап (для пошагового трекинга/UI)
    functions: list[FunctionGene] = field(default_factory=list)

    def add(self, fg: FunctionGene) -> "NodeGene":
        self.functions.append(fg)
        return self

    def label(self) -> str:
        funcs = " -> ".join(fg.function for fg in self.functions)
        return f"{self.group}: {funcs}"
