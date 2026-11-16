"""C6 — РЕНДЕР tNavigator-воркфлоу из генов узлов и сырых шаблонов функций.

Подход (повторяет проверенный `genetic_algorithms/src/adaptation/builder.py`):
    * обёртка файла воркфлоу (`template_wf.txt`) с плейсхолдером `<РАСЧЕТ>`;
    * блок каждой функции = СЫРОЙ шаблон `templates/<function>.txt` (машинный код v26.1);
    * точечная подстановка (regex): `index = N`, `\\b<code>=<default>` и имя объекта
      внутри `<arg>=typed_object_name (obj_name="...")`.

Выход — валидный `.py` формата тНава v26.1: `declare_workflow` + `begin_wf_item`/
`end_wf_item` + вызовы `tNavigator_python_API`.
"""
from __future__ import annotations

import re
from pathlib import Path

from .workflow_model import FunctionGene, FunctionRule, NodeGene, ObjectRef

_BODY_INDENT = " " * 4
_PLACEHOLDER = "<РАСЧЕТ>"
_INDEX = re.compile(r"index\s*=\s*\d+")
_STRUCT_START = ("typed_object_name", "absolute_object_name", "WellFilterParameters",
                 "Grid2DSettings", "VariogramParameters", "[", "{")
_STRING = re.compile(r'"[^"]*"')


def _paren_delta(line: str) -> int:
    """Разница '(' и ')' в строке (вне строковых литералов) — для нормализации отступов."""
    return _STRING.sub("", line).count("(") - _STRING.sub("", line).count(")")


class RenderError(RuntimeError):
    pass


class WorkflowBuilder:
    """Сборка воркфлоу тНав из узлов (NodeGene) и правил функций (FunctionRule)."""

    _REQ_CACHE: dict | None = None      # кэш требований из онтологии (данные)
    _SKIP_FLAG: bool | None = None      # флаг `workflow.skip_unbound_steps` (по умолчанию выкл.)
    _DEMO_CACHE: list | None = None     # имена демо-проекта из онтологии (данные)

    def __init__(self, *, wrapper: Path, templates_dir: Path,
                 render_name: str = "Structure_modeling") -> None:
        self.wrapper = Path(wrapper)
        self.templates_dir = Path(templates_dir)
        self.render_name = render_name
        if not self.wrapper.is_file():
            raise RenderError(f"Не найдена обёртка воркфлоу: {self.wrapper}")
        self._cache: dict[str, str] = {}
        self.warnings: list[str] = []

    def _template(self, rule: FunctionRule) -> str:
        name = Path(rule.template_path).name
        if name in self._cache:
            return self._cache[name]
        path = self.templates_dir / name
        if not path.is_file():
            raise RenderError(f"Не найден шаблон функции: {path}")
        text = path.read_text(encoding="utf-8")
        self._cache[name] = text
        return text

    def build(self, nodes: list[NodeGene], rules: dict[str, FunctionRule]) -> str:
        blocks: list[str] = []
        index = 1
        for node in nodes:
            for fg in node.functions:
                rule = rules.get(fg.function)
                if rule is None:
                    raise RenderError(f"Нет правила функции '{fg.function}' (узел {node.group}).")
                block, index = self.render_block(rule, fg, index)
                blocks.append(block)
        return self._wrap("\n\n".join(blocks))

    def assemble(self, blocks: list[str]) -> str:
        """Собрать воркфлоу из уже отрендеренных блоков (для пошаговой записи)."""
        return self._wrap("\n\n".join(blocks))


    def _step_requirements(self) -> dict:
        """Требования шагов к привязкам — ИЗ ОНТОЛОГИИ (данные, а не код под объект)."""
        if WorkflowBuilder._REQ_CACHE is None:
            path = Path(__file__).resolve().parents[1] / "ontology" / "input_recognition_rules.yaml"
            data: dict = {}
            if path.is_file():
                try:
                    import yaml
                    data = ((yaml.safe_load(path.read_text(encoding="utf-8")) or {})
                            .get("step_object_requirements") or {})
                except Exception:                       # noqa: BLE001 — данные опциональны
                    data = {}
            WorkflowBuilder._REQ_CACHE = {str(k): dict(v or {}) for k, v in data.items()}
        return WorkflowBuilder._REQ_CACHE

    def _missing_requirements(self, rule: FunctionRule, gene: FunctionGene) -> list[str]:
        """Аргументы шаблона, для которых у гена НЕТ привязки.

        Источник требований — САМ ШАБЛОН tNavigator (`domain/templates/<fn>.txt`): имена
        его аргументов и есть истинный контракт привязок. Рукописные списки (раунд 116)
        оказались неточными — 7 из 14 функций имели придуманные имена, из-за чего механизм
        пропускал законные шаги (раунд 121). Здесь перечень выводится из данных.

        По умолчанию выключено (`workflow.skip_unbound_steps` / env `DSH_SKIP_UNBOUND`):
        включение меняет состав воркфлоу и требует подтверждения приёмочными тестами.
        """
        if not self._skip_enabled():
            return []
        spec = dict(self._step_requirements().get(str(getattr(rule, "name", ""))) or {})
        if str(spec.get("policy") or "") != "bind_or_skip":
            return []
        bound = set((gene.objects or {}).keys())
        bound |= set((getattr(gene, "parameters", None) or {}).keys())
        bound |= set((getattr(gene, "lists", None) or {}).keys())
        # Требованием считаем объектные аргументы шаблона, несущие значение ДЕМО-проекта
        # (перечень — из онтологии, `template_demo_names`). Проверка «любой непривязанный
        # объектный аргумент → пропуск» отвергнута (раунд 148): у части аргументов есть
        # законные значения по умолчанию (`well_filter`, `polygon`, `current_marker_set`),
        # и такая проверка резала рабочие шаги Герасимовского (7 предупреждений, 5 красных
        # файлов тестов). Точный признак — принадлежность значения перечню демо-имён.
        text = self._template(rule)
        demo = set(str(x) for x in self._demo_names())
        found = re.findall(
            r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[A-Za-z_][A-Za-z0-9_]*\s*\(\s*obj_name\s*=\s*\"([^\"]*)\"",
            text)
        return [role for role, obj in found if role not in bound and obj in demo]

    def _demo_names(self) -> list[str]:
        """Имена демо-проекта из шаблонов — ИЗ ОНТОЛОГИИ (`template_demo_names.names`)."""
        if WorkflowBuilder._DEMO_CACHE is None:
            path = Path(__file__).resolve().parents[1] / "ontology" / "input_recognition_rules.yaml"
            names: list[str] = []
            if path.is_file():
                try:
                    import yaml
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    names = [str(x) for x in ((data.get("template_demo_names") or {})
                                              .get("names") or [])]
                except Exception:                       # noqa: BLE001 — данные опциональны
                    names = []
            WorkflowBuilder._DEMO_CACHE = names
        return WorkflowBuilder._DEMO_CACHE

    def _skip_enabled(self) -> bool:
        """Флаг из ДАННЫХ: env `DSH_SKIP_UNBOUND` или `workflow.skip_unbound_steps`."""
        import os as _os
        env = _os.environ.get("DSH_SKIP_UNBOUND", "")
        if env not in ("", None):
            return str(env).strip().lower() in ("1", "true", "yes", "on")
        if WorkflowBuilder._SKIP_FLAG is None:
            enabled = False
            for cand in (Path.cwd() / "config.yaml",
                         Path(__file__).resolve().parents[1] / "config.yaml"):
                if not cand.is_file():
                    continue
                try:
                    import yaml
                    data = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
                    enabled = bool((data.get("workflow") or {}).get("skip_unbound_steps", False))
                except Exception:                       # noqa: BLE001
                    enabled = False
                break
            WorkflowBuilder._SKIP_FLAG = enabled
        return WorkflowBuilder._SKIP_FLAG

    def render_block(self, rule: FunctionRule, gene: FunctionGene,
                     index: int) -> tuple[str, int]:
        # Раунд 120: шаг без обязательных привязок НЕ рендерится телом шаблона. Иначе в
        # воркфлоу попадают имена ДЕМО-проекта из `domain/templates/*.txt`, и tNavigator
        # падает: `Identifier 'BBall_thick' is not defined here` (проверено на втором
        # объекте). Требования к привязкам — ИЗ ОНТОЛОГИИ (`step_object_requirements`),
        # политика `bind_or_skip`: нет привязки → шаг пропускается (правило 6).
        missing = self._missing_requirements(rule, gene)
        if missing:
            self.warnings.append(
                f"шаг '{getattr(rule, 'name', '?')}' пропущен: нет привязки ({', '.join(missing)})")
            return ("# ПРОПУЩЕНО ПО ПОЛИТИКЕ (нет привязки объекта: "
                    + ", ".join(missing) + "):\n"
                    + f"#   {getattr(rule, 'name', '?')} — тело шаблона не выпускается, "
                      "исполнение пометит шаг skipped_by_policy"), index + 1
        text = self._template(rule)
        text = _INDEX.sub(f"index = {index}", text)          # 1) сквозной номер
        for code, value in (gene.parameters or {}).items():   # 2) скаляры
            text = self._put_param(text, code, value)
        for code, values in (gene.lists or {}).items():       # 3) списки (file_names=…)
            text = self._put_list(text, code, values)
        for role, obj in (gene.objects or {}).items():        # 4) объекты
            text = self._put_object(text, role, obj)
        for old, new in (getattr(gene, "replace", None) or {}).items():   # 5) точечная замена
            if old in text:
                text = text.replace(old, str(new))
            else:
                self.warnings.append(f"replace '{old}' не найден")
        return text.rstrip(), index + 1

    # -- подстановки ---------------------------------------------------------
    @staticmethod
    def _arg_of(role: str) -> str:
        """'input_horizon(obj_name)' -> 'input_horizon'."""
        return role.split("(", 1)[0].strip()

    @staticmethod
    def _literal(value) -> str:
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, (int, float)):
            return repr(value)
        if value is None:
            return '""'
        return '"' + str(value).replace('"', '\\"') + '"'

    def _put_param(self, text: str, code: str, value) -> str:
        """Заменить значение скалярного параметра `code` на значение гена."""
        pattern = re.compile(r"(\b" + re.escape(code) + r"\s*=\s*)(\"[^\"]*\"|[^,\n)]+)")

        def repl(m: re.Match) -> str:
            old = m.group(2).strip()
            if any(old.startswith(s) for s in _STRUCT_START):
                return m.group(0)              # структурное значение — не трогаем
            return m.group(1) + self._literal(value)

        new, n = pattern.subn(repl, text)
        if n == 0:
            self.warnings.append(f"param '{code}' не найден в шаблоне")
        return new

    def _put_list(self, text: str, code: str, values) -> str:
        """Заменить flat-список `code=[...]` на новый список строк (например file_names=[…])."""
        pattern = re.compile(r"(\b" + re.escape(code) + r"\s*=\s*)\[[\s\S]*?\]")
        items = ", ".join('"' + str(v).replace('"', '\\"') + '"' for v in (values or []))
        new, n = pattern.subn(lambda m: m.group(1) + "[" + items + "]", text)
        if n == 0:
            self.warnings.append(f"list '{code}' не найден в шаблоне")
        return new

    def _put_object(self, text: str, role: str, obj: ObjectRef) -> str:
        """Заменить имя/тип объекта для роли: typed_object_name / find_object / absolute_object_name.

        Поддерживается и `arg=ctor(...)`, и dict-стиль `"arg": ctor(...)` (например,
        `well_atributes_table=[{"well_attribute": typed_object_name(...)}]`).
        """
        arg = self._arg_of(role)
        ctors = (("typed_object_name", "obj_name", "obj_type"),
                 ("find_object", "name", "type"),
                 ("absolute_object_name", "name", "typed_names"))
        seps = (r"\s*=\s*", r'"\s*:\s*', r"'\s*:\s*")
        for ctor, name_k, type_k in ctors:
            for sep in seps:
                block_re = re.compile(
                    re.escape(arg) + sep + ctor + r"\s*\(([\s\S]*?)\)", re.MULTILINE)
                m = block_re.search(text)
                if not m:
                    continue
                body = m.group(1)
                body = re.sub(r'(' + name_k + r'\s*=\s*")[^"]*(")',
                              lambda x: x.group(1) + obj.obj_name + x.group(2), body)
                if obj.obj_type and type_k == "type":
                    body = re.sub(r'(' + type_k + r'\s*=\s*")[^"]*(")',
                                  lambda x: x.group(1) + obj.obj_type + x.group(2), body)
                return text[:m.start(1)] + body + text[m.end(1):]
        self.warnings.append(f"object role '{role}' не найден в шаблоне")
        return text

    # -- обёртка -------------------------------------------------------------
    def _indent_body(self, body: str) -> str:
        """Выровнять начала инструкций (глубина скобок 0) под тело def; продолжения — как есть."""
        out: list[str] = []
        depth = 0
        for ln in body.splitlines():
            if not ln.strip():
                out.append("")
                continue
            if depth == 0:
                out.append(_BODY_INDENT + ln.strip())
            else:
                out.append(ln if ln[:1] in (" ", "\t") else _BODY_INDENT + ln)
            depth = max(0, depth + _paren_delta(ln))
        return "\n".join(out)

    def _wrap(self, body: str) -> str:
        text = self.wrapper.read_text(encoding="utf-8")
        indented = self._indent_body(body)
        # заменяем ВСЮ строку с плейсхолдером (иначе отступ строки дублируется)
        return re.sub(r"^[ \t]*" + re.escape(_PLACEHOLDER) + r"[ \t]*$",
                      indented, text, count=1, flags=re.MULTILINE)

    def write(self, nodes: list[NodeGene], rules: dict[str, FunctionRule], out: Path) -> Path:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.build(nodes, rules), encoding="utf-8")
        return out

