"""Координатор v5: обращение → онтология v4 → гены → воркфлоу → тНав → QA/QC.

Собирает контур:
    * C1 OntologyService — операции/стадии/функции/QA/параметры (данные v4);
    * C5 WorkflowAssembler — NodeGene[] из онтологии групп операций;
    * C6 WorkflowBuilder — рендер tNavigator-воркфлоу `.py`;
    * C7 TnavClient — прогон (Python API / subprocess, dry-run);
    * C8 MetaCritic — QA/QC → вердикт (passed/failed/UNKNOWN).
"""
from __future__ import annotations

import json
import math
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from core.config import Config
from core.model_artifacts import persist_model
from core.ontology import OntologyService
from core.pipeline import DONE, ERROR, PENDING_TEMPLATE, RUNNING, Pipeline
from domain.assembler import WorkflowAssembler
from domain.function_rules import FunctionRuleReader
from domain.metacritic import MetaCritic
from domain.tnav_client import TnavClient, TnavRunResult
from domain.qaqc_adapter import evaluate as qaqc_evaluate
from domain.trajectories import prepare_boundary, prepare_trajectories, read_wellheads
from domain.welltops import normalize_marker_wells, read_welltops
from domain.workflow_renderer import WorkflowBuilder


# --- Контроль геометрии сетки -------------------------------------------------
# `run_py_code` в проекте тНава НЕ возвращает значение наружу, поэтому результат
# пишется в tmp-файл (тот же проверенный канал, что и для метрики запасов).
# Путь держим ASCII-совместимым (в пути проекта есть кириллица).
_GEOM_TMP = Path(__file__).resolve().parents[1] / ".grid_geometry.tmp"
_METRIC_TMP = Path(__file__).resolve().parents[1] / ".stoiip.tmp"
_WELLTIE_TMP = Path(__file__).resolve().parents[1] / ".welltie.tmp"

# Суффикс каталога dry-run (task-18/A): dry-run и execute НЕ должны делить каталог
# прогона — иначе артефакты (report одного прогона + steps/gates другого) смешиваются,
# а dry-run подхватывает чужой проект модели. Штатно значение — ДАННЫЕ
# `runs.dry_suffix`; здесь инфраструктурное умолчание ("" → прежнее поведение).
_DEFAULT_DRY_SUFFIX = "_dry"


def _tmp_path(p: Path) -> str:
    """Путь для py-кода тНава: прямые слэши (в пути проекта есть кириллица)."""
    return str(p).replace("\\", "/")


def _branch_model_files(root: Path, field: str) -> list[Path]:
    """Файлы проекта ветки в её каталоге: `<поле>.snp` + каталог `<поле>.snf`."""
    out: list[Path] = []
    snp = root / f"{field}.snp"
    if snp.is_file():
        out.append(snp)
    snf = root / f"{field}.snf"
    if snf.is_dir():
        out.append(snf)
    return out


def _copy_branch_project(src_root: Path, dest_root: Path, field: str) -> bool:
    """Скопировать проект ветки из кэша в каталог ветки (`.snp` + `.snf`)."""
    files = _branch_model_files(src_root, field)
    if not files:
        return False
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        for item in files:
            target = dest_root / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        return True
    except OSError:
        return False


def _branch_cache_put_file(src_root: Path, dest_root: Path, field: str) -> bool:
    """Положить/обновить проект ветки в кэш (копируем только модель, не данные поля)."""
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        for item in _branch_model_files(src_root, field):
            target = dest_root / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        return True
    except OSError:
        return False


_GEOM_KEYS = ("nx", "ny", "nz", "min_x", "max_x", "min_y", "max_y", "min_z", "max_z")
_GEOM_CALLS = ("get_nx", "get_ny", "get_nz", "get_min_x", "get_max_x",
               "get_min_y", "get_max_y", "get_min_z", "get_max_z")

# Разумные пределы для пласта на глубине ~2-3 км (метры, абсолютная отметка).
_Z_ABS_LIMIT = 20_000.0   # |Z| больше — в горизонт попал мусор (напр. бланк novalue)
_Z_SPAN_LIMIT = 5_000.0   # мощность модели >5 км — тоже признак мусора


def check_grid_geometry(geom: dict | None) -> str | None:
    """Текст предупреждения, если геометрия сетки неправдоподобна (иначе None).

    Ловит реальный дефект: бланк структурной карты (novalue) уходит в Z горизонта,
    и сетка вырождается в «иголку» (Z до ±1e7 м при верном плане).
    """
    if not isinstance(geom, dict):
        return None
    min_z, max_z = geom.get("min_z"), geom.get("max_z")
    if not all(isinstance(v, (int, float)) for v in (min_z, max_z)):
        return None
    min_z, max_z = float(min_z), float(max_z)
    if max(abs(min_z), abs(max_z)) > _Z_ABS_LIMIT:
        return (f"Z вырожден: {min_z:.1f}..{max_z:.1f} м — в горизонты попал бланк "
                f"карты (проверь novalue при импорте irap)")
    if (max_z - min_z) > _Z_SPAN_LIMIT:
        return (f"мощность модели {max_z - min_z:.1f} м нереалистична — "
                f"проверь горизонты/толщины")
    return None


def _interval_markers(project: dict) -> tuple[str, str]:
    """Маркеры кровли/подошвы моделируемого интервала — из ДАННЫХ проекта.

    Приоритет: секция `structural:` (интервал структурного агента) →
    `markers:` (`reservoir_top` и следующий по стратиграфическому `order`).
    В коде нет имён маркеров — только чтение данных.
    """
    st = project.get("structural") or {}
    markers = project.get("markers") or {}
    order = [str(m) for m in (markers.get("order") or [])]
    top = str(st.get("interval_top_marker") or markers.get("reservoir_top") or "")
    base = str(st.get("interval_base_marker") or "")
    if (not base or base.upper() == top.upper()) and order:
        idx = next((i for i, m in enumerate(order) if m.upper() == top.upper()), None)
        if idx is not None and idx + 1 < len(order):
            base = order[idx + 1]
    return top, base


class Coordinator:
    def __init__(self, cfg: Config, *, dry_run: bool | None = None) -> None:
        self.cfg = cfg
        self._ontology: OntologyService | None = None
        if dry_run is not None:
            cfg.set("tnavigator.dry_run", bool(dry_run))

    # -- C1 ----------------------------------------------------------------
    @property
    def ontology(self) -> OntologyService:
        if self._ontology is None:
            self._ontology = OntologyService(self.cfg)
        return self._ontology

    # -- проектный граф (ABox, данные) -------------------------------------
    def project_graph(self, field: str | None = None) -> dict:
        field = field or str(self.cfg.get("project.default_field", "") or "")
        graph_dir = self.cfg.path("project.graph_dir", "ontology_project")
        graph: dict = {}
        for cand in (graph_dir / f"{field}.yaml", graph_dir / f"{field}.yml"):
            if cand.is_file():
                graph = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
                break
        if not graph:
            # иначе — найти YAML, у которого поле `field` совпадает (имя файла не важно)
            for cand in sorted(graph_dir.glob("*.y*ml")):
                data = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict) and str(data.get("field", "")) == field:
                    graph = data
                    break
        # КРИТЕРИЙ (б): состав пайплайна выводится АГЕНТАМИ ИЗ ОНТОЛОГИИ И ДАННЫХ
        # поля, а не берётся только из заранее написанного YAML. Режим — ДАННЫЕ
        # (`workflow.pipeline_source`: yaml | ontology). В режиме ontology YAML
        # служит шаблоном/переопределением, а не единственным источником.
        source = str(self.cfg.get("workflow.pipeline_source", "yaml") or "yaml").lower()
        if source == "ontology" or not graph:
            derived = self.graph_from_ontology(field, template=graph)
            if derived:
                return derived
        return graph

    def _attach_object_requirements(self, graph: dict) -> dict:
        """ОТКЛЮЧЕНО (раунд 146): используйте механизм рендерера.

        Ранее здесь ставился `requires_object` по таблице `step_object_requirements`, имена
        в которой задавались «по смыслу» — 7 из 14 не совпадали с фактическими аргументами
        шаблонов. Это приводило к ложным пропускам (10 шагов) и падению приёмки
        (`scored: 0`, раунд 123). Правильный путь — в `domain/workflow_renderer.py`: там
        требованием считается только объектный аргумент шаблона, несущий значение
        демо-проекта (перечень демо-имён — из онтологии). Метод оставлен как no-op, чтобы
        не было двух конкурирующих механизмов.
        """
        return graph

    # ── Целостность исходных данных (data.source_untouched, см. ontology/
    #    input_recognition_rules.yaml → data_integrity) ─────────────────────────
    def _dataset_manifest(self, field: str) -> dict:
        """Снимок каталога данных поля: {относительный путь: (размер, sha256[:16])}.

        Служит доказательством, что прототип НЕ пишет в данные заказчика (F-28: прогон
        затирал файл отбивок «на месте», сжимая его до 2 байт). Каталог берётся из
        данных поля (`dataset_root`), а не из кода.
        """
        import hashlib
        root = None
        try:
            graph = self.project_graph(field) or {}
            candidate = str(graph.get("dataset_root") or "")
            if candidate:
                from core.config import SERVICE_ROOT
                path = Path(candidate)
                root = path if path.is_absolute() else Path(SERVICE_ROOT) / path
        except Exception:                               # noqa: BLE001 — данные опциональны
            root = None
        if root is None or not Path(root).is_dir():
            return {}
        manifest: dict = {}
        for p in sorted(Path(root).rglob("*")):
            if not p.is_file():
                continue
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            manifest[str(p.relative_to(root)).replace("\\", "/")] = (
                len(raw), hashlib.sha256(raw).hexdigest()[:16])
        return manifest

    def _dataset_integrity(self, before: dict, after: dict) -> dict:
        """Вердикт неприкосновенности данных: changed/removed/added против снимка."""
        if not before:
            return {"verdict": "unverified", "reason": "каталог данных поля не определён"}
        changed = sorted(k for k in before if k in after and after[k] != before[k])
        removed = sorted(k for k in before if k not in after)
        added = sorted(k for k in after if k not in before)
        touched = changed + removed + added
        return {"verdict": "failed" if touched else "passed",
                "files_before": len(before), "files_after": len(after),
                "changed": changed, "removed": removed, "added": added,
                "reason": ("данные поля изменены прогоном" if touched
                           else "каталог данных поля не изменён прогоном")}

    def _template_demo_names(self) -> list[str]:
        """Имена демо-проекта из шаблонов — ИЗ ОНТОЛОГИИ (`template_demo_names.names`)."""
        path = Path(__file__).resolve().parent.parent / "ontology" / "input_recognition_rules.yaml"
        if not path.is_file():
            return []
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:                               # noqa: BLE001 — данные опциональны
            return []
        return [str(x) for x in ((data.get("template_demo_names") or {}).get("names") or [])]

    def _export_paths_check(self, run_dir) -> dict:
        """`data.export_paths_within_run`: все выгрузки обязаны лежать в каталоге прогона.

        Иначе имя выгрузки совпадает с именем файла данных поля и перезаписывает его —
        вторая половина дефекта F-28 (прогон затирал `Well_Tops` в каталоге данных).
        Проверяются параметры `file_name=...` отрендеренных этапов.
        """
        import re as _re
        run_dir = Path(run_dir)
        stages = run_dir / "agents" / "stages"
        if not stages.is_dir():
            return {"verdict": "unverified", "reason": "этапы не отрендерены"}
        violations: list[dict] = []
        checked = 0
        for py in sorted(stages.glob("*.py")):
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _re.finditer(r'file_name\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', text):
                target = (m.group(1) or m.group(2) or "").strip()
                if not target:
                    continue
                checked += 1
                if target.startswith("__"):            # шаблонный плейсхолдер (__FILE__)
                    continue
                resolved = Path(target)
                if not resolved.is_absolute():
                    resolved = (run_dir / resolved).resolve()
                try:
                    resolved.relative_to(run_dir.resolve())
                except ValueError:
                    violations.append({"step_file": py.name, "file_name": target,
                                       "resolved": str(resolved)})
        # Дополнительно: имена ДЕМО-ПРОЕКТА из шаблонов (`template_demo_names` в онтологии)
        # недопустимы в воркфлоу реального поля. Проверено на втором объекте: у поля без
        # привязок они протекают в рендер, и tNavigator падает
        # (`Identifier 'BBall_thick' is not defined here`). У поля с графом их нет —
        # проверено на воркфлоу Герасимовского (0 вхождений).
        demo_names = self._template_demo_names()
        demo_hits: list[dict] = []
        if demo_names:
            for py in sorted(stages.glob("*.py")):
                try:
                    text = py.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for nm in demo_names:
                    if nm in text:
                        demo_hits.append({"step_file": py.name, "demo_name": nm,
                                          "needs": "привязка объекта из данных/онтологии"})
        return {"verdict": "failed" if (violations or demo_hits) else ("passed" if checked else "unverified"),
                "checked": checked, "violations": violations,
                "demo_name_hits": demo_hits,
                "reason": ("имя демо-проекта в воркфлоу" if demo_hits else
                           ("есть выгрузки вне каталога прогона" if violations else
                            ("все выгрузки внутри каталога прогона" if checked
                             else "выгрузок не найдено")))}

    def _data_checks(self, field: str, run_dir=None) -> dict:
        """Четыре контроля данных по правилам ОНТОЛОГИИ (input_recognition_rules.yaml).

        * `inputs_recognized`      — распознаны ли все ОБЯЗАТЕЛЬНЫЕ роли поля;
        * `no_placeholders`        — не осталось ли заглушек (`__todo__`) в графе;
        * `markers_resolved`       — определены ли кровля/подошва (правилом или данными);
        * `format_adapter_matched` — сопоставлен ли формат каждого входного файла адаптеру.

        Вердикты `passed|failed|unverified`; ничего не блокируют, а фиксируются в отчёте
        (правило 6: «неизвестно» не выдаётся ни за успех, ни за провал без свидетельств).
        """
        path = Path(__file__).resolve().parent.parent / "ontology" / "input_recognition_rules.yaml"
        rules: dict = {}
        if path.is_file():
            try:
                import yaml
                rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:                           # noqa: BLE001 — данные опциональны
                rules = {}
        roles = {str(k): dict(v or {}) for k, v in (rules.get("roles") or {}).items()}
        formats = {str(k): dict(v or {}) for k, v in (rules.get("formats") or {}).items()}
        required = [r for r, s in roles.items() if s.get("required")]
        forbidden = [str(x) for x in ((rules.get("policy") or {}).get("placeholder_forbidden") or [])]

        graph: dict = {}
        try:
            graph = self.project_graph(field) or {}
        except Exception:                               # noqa: BLE001
            graph = {}
        inputs = dict(graph.get("inputs") or {})
        markers = dict(graph.get("markers") or {})

        missing = [r for r in required
                   if r not in inputs and str(roles[r].get("internal_key") or "") not in inputs]
        recognized = {"verdict": "unverified" if not roles else
                      ("failed" if missing else "passed"),
                      "required": required, "missing": missing,
                      "found": sorted(inputs)}

        flat = []
        for k, v in list(markers.items()) + [("reservoir_horizon", graph.get("reservoir_horizon"))]:
            if isinstance(v, str):
                flat.append((k, v))
        placeholders = sorted({v for k, v in flat if v in forbidden})
        no_placeholders = {"verdict": "failed" if placeholders else
                           ("unverified" if not flat else "passed"),
                           "placeholder_values": placeholders,
                           "fields": sorted(k for k, v in flat if v in forbidden)}

        top = str(markers.get("reservoir_top") or "")
        markers_resolved = {"verdict": "passed" if top and top not in forbidden else
                            ("unverified" if not markers else "failed"),
                            "reservoir_top": top or None,
                            "reservoir_base": markers.get("reservoir_base")}

        # формат: расширение файла против `formats.*.detect.extensions|filename_patterns`.
        # КАТАЛОГ допустим, если внутри есть файлы описанных форматов (в проектном графе
        # поля роль «логи ГИС» может указывать на папку — импорт раскрывает её сам).
        root = None
        try:
            cand_root = str(graph.get("dataset_root") or "")
            if cand_root:
                from core.config import SERVICE_ROOT
                rp = Path(cand_root)
                root = rp if rp.is_absolute() else Path(SERVICE_ROOT) / rp
        except Exception:                               # noqa: BLE001
            root = None
        known_ext = set()
        for _fname, spec in formats.items():
            det = dict(spec.get("detect") or {})
            known_ext |= {str(e).lower().lstrip(".") for e in (det.get("extensions") or [])}
        unknown_files: list[str] = []
        dirs_expanded: list[str] = []
        for key, value in inputs.items():
            name = Path(str(value)).name
            low = name.lower()
            if root is not None and (Path(root) / str(value)).is_dir():
                inside = [p for p in (Path(root) / str(value)).rglob("*")
                          if p.is_file() and p.suffix.lower().lstrip(".") in known_ext]
                if inside:
                    dirs_expanded.append(f"{name} ({len(inside)} файл(ов))")
                    continue
            hit = False
            for _fname, spec in formats.items():
                det = dict(spec.get("detect") or {})
                exts = [str(e).lower().lstrip(".") for e in (det.get("extensions") or [])]
                pats = [str(p).lower() for p in (det.get("filename_patterns") or [])]
                if exts and low.endswith(tuple("." + e for e in exts)):
                    hit = True
                if pats and any(p in low for p in pats):
                    hit = True
            if not hit:
                unknown_files.append(name)
        format_adapter = {"verdict": "unverified" if not formats else
                          ("passed" if not unknown_files else "failed"),
                          "unknown_files": sorted(unknown_files),
                          "directories_expanded": sorted(dirs_expanded),
                          "checked": len(inputs)}

        return {"inputs_recognized": recognized, "no_placeholders": no_placeholders,
                "markers_resolved": markers_resolved,
                "format_adapter_matched": format_adapter,
                # Сводка правил онтологии: что реально доступно при сборке плана из
                # онтологии (требование заказчика: методы должны читаться из ontology/,
                # а не жить в проектном графе). Список формируется из каталога данных.
                "ontology_rules": self._ontology_rules_summary(),
                # ПЕТРОФИЗИЧЕСКИЕ ПРАВИЛА КАК ПОТРЕБИТЕЛЬ: показываем, что контракт
                # (обработка бланков, проверка единиц, масштаб кривых, лестница источников
                # k-φ) реально прочитан из онтологии при сборке плана. Гейтовое исполнение
                # (petro.*) регистрируется отдельно, чтобы не нарушать кросс-валидацию
                # реестра проверок — здесь фиксируется факт чтения и состав правил.
                "petro_rules": self._petro_rules_summary(),
                # СТРУКТУРНЫЕ И ГЕОСТАТИСТИЧЕСКИЕ ПРАВИЛА как потребитель: подтверждаем,
                # что сборка плана видит правило «подошва от кровли» (исправление «бычьих
                # глаз»), порог вреза и пороги контроля локальной подсадки — ИЗ ОНТОЛОГИИ.
                "struct_rules": self._struct_rules_summary(),
                # КОНТРОЛЬ «БЫЧЬИХ ГЛАЗ» (замечание №1 заказчика): если после прогона есть
                # выгрузки поверхностей, измеряем локальную подсадку на скважины штатным
                # инструментом. Ошибка измерения НИКОГДА не ломает прогон (guarded).
                "struct_bullseye": self._bullseye_report(run_dir, graph),
                # ПЕТРОФИЗИКА ПО ФАКТУ: измеряем распределение кривых из LAS поля и сверяем
                # с ожидаемыми диапазонами (проверка ЕДИНИЦ). Мнемоники и диапазоны —
                # ДАННЫЕ (petrophysics.cubes / petrophysics.expect), доменных имён в коде нет.
                "petro_measured": self._petro_measured_check(graph),
                # ТРАССИРОВКА ПОРОГОВ ПРИЁМКИ К ЧЕКЛИСТУ (ontology/thresholds_rules.yaml):
                # у каждого порога обязан быть источник, а объявленные блоки чеклиста —
                # существовать в оцифрованных данных. Нет источника → unverified.
                "qaqc_provenance": self._qaqc_provenance_check(graph),
                # PVT/SCAL и состав ансамбля: проверяем, что корреляции и правило отбора
                # объявлены в онтологии, а число ветвей не меньше требуемого (ДАННЫЕ).
                "pvt_scal_ensemble": self._pvt_scal_ensemble_check(graph),
                # ПРИВЯЗКИ ОБЪЕКТОВ (ontology/object_binding_rules.yaml): какие обязательные
                # аргументы функций не заполнены данными поля. Это рабочая ведомость для
                # механизма привязки (замены «протёкших» значений шаблонов значениями поля).
                "objects_bindings": self._objects_bindings_check(graph),
                # ПРЕДЛОЖЕНИЕ ОБЪЕКТНОЙ МОДЕЛИ: какие имена объекты получили бы по правилам
                # онтологии (`naming`) и какие привязки из них следуют (`bindings`). Пока
                # только отчёт (рендер не меняется) — чтобы проверить генератор до включения.
                "object_model": self._object_model_proposal(graph),
                # ФОРМАТ ТАБЛИЦЫ ОТБИВОК (round 175–179): импорт маркеров ожидает плоскую
                # таблицу (Well, Marker, MD). Если файл поля в ином формате (например,
                # Petrel Well Tops), импорт не создаст маркеров, и потребители роли
                # `reservoir_top` упадут («Well Marker is not valid») — нужен шаг конвертации.
                "marker_format": self._marker_format_check(graph),
                # ПОТОК ОБЪЕКТОВ (round 184–185): потребитель обязан идти ПОСЛЕ производителя.
                # Проверено на ТЕСТ2: падал item 1 («2D-Map Distances To Well Marker»), то есть
                # потребитель выполнялся до создания объекта. Контроль делает такие нарушения
                # видимыми в отчёте — до запуска tNavigator, а не «сюрпризом» в логе.
                "object_flow": self._object_flow_check(graph)}

    def _object_flow_check(self, graph: dict) -> dict:
        """Нарушения порядка «производитель → потребитель» в выведенном плане."""
        try:
            path = (Path(__file__).resolve().parent.parent / "ontology"
                    / "object_binding_rules.yaml")
            if not path.is_file():
                return {"verdict": "unverified", "reason": "правила связывания не найдены"}
            import yaml
            wiring = dict(((yaml.safe_load(path.read_text(encoding="utf-8")) or {})
                           .get("wiring") or {}))
            producers = {str(k): dict(v or {}) for k, v in (wiring.get("producers") or {}).items()}
            consumers = {str(k): dict(v or {}) for k, v in (wiring.get("consumers") or {}).items()}
            if not producers or not consumers:
                return {"verdict": "unverified", "reason": "связывание не описано"}
            produced: set = set()
            violations: list = []
            steps = 0
            for idx, step in enumerate(self._iter_steps(graph.get("pipeline") or [])):
                fn = str(step.get("function") or "")
                steps += 1
                raw_c = dict(consumers.get(fn) or {})
                if "arg" in raw_c:                     # форма {arg: ..., role: ...}
                    entries = [(str(raw_c.get("arg") or ""), str(raw_c.get("role") or ""))]
                else:                                   # форма {аргумент: {role: ...}}
                    entries = [(str(k), str((v or {}).get("role") or "")
                                if isinstance(v, dict) else str(v))
                               for k, v in raw_c.items()]
                for arg, role in entries:
                    if role and role not in produced:
                        violations.append({"position": idx, "function": fn,
                                           "argument": str(arg), "role": role,
                                           "reason": "потребитель раньше производителя"})
                spec_p = dict(producers.get(fn) or {})
                if spec_p:
                    produced.add(str(spec_p.get("role") or ""))
                    for _a, s2 in dict(spec_p.get("also_produces") or {}).items():
                        if isinstance(s2, dict):
                            for alt in dict(s2.get("role_by_marker") or {}).values():
                                produced.add(str(alt))
                        else:
                            produced.add(str(s2))
            return {"verdict": "passed" if not violations else "unverified",
                    "steps": steps, "violations": violations[:20],
                    "violations_count": len(violations),
                    "produced_roles": sorted(r for r in produced if r)}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка проверки: {exc}"}

    def _prepare_trajectories(self, field: str, run_dir) -> dict:
        """Подготовить плоскую таблицу траекторий (well, MD, X, Y, Z) и свидетельство.

        Проверка data.trajectories (G-DATA) читает свидетельство
        {"written": N, "skipped": M} — без него этап справедливо уходит в bypassed
        (проверено на ТЕСТ2: «траекторий: 0»). Пишем только в каталог прогона.
        """
        try:
            import importlib.util
            root = None
            try:
                from core.config import SERVICE_ROOT
                rp = Path(str((self.project_graph(field) or {}).get("dataset_root") or ""))
                root = rp if rp.is_absolute() else Path(SERVICE_ROOT) / rp
            except Exception:                       # noqa: BLE001
                root = None
            src_dir = None
            if root is not None:
                for cand in root.rglob("*.dev"):
                    src_dir = cand.parent
                    break
            if src_dir is None:
                return {"written": 0, "skipped": 0, "reason": "файлы .dev не найдены"}
            tool = Path(__file__).resolve().parent.parent / "tools" / "prepare_trajectories.py"
            spec = importlib.util.spec_from_file_location("_ptr", tool)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)            # type: ignore[union-attr]
            files = sorted(src_dir.rglob("*.dev"))
            rows, skipped = [], 0
            for f in files:
                got = mod.parse_deviation(f)
                if got:
                    rows += got
                else:
                    skipped += 1
            if not rows:
                return {"written": 0, "skipped": skipped, "reason": "таблица пуста"}
            out = Path(run_dir) / "Wells" / "trajectories.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(mod.to_flat_table(rows), encoding="utf-8")
            return {"written": len(files) - skipped, "skipped": skipped,
                    "rows": len(rows), "files": len(files),
                    "written_to": str(out.relative_to(Path(run_dir))).replace("\\", "/")}
        except Exception as exc:                    # noqa: BLE001 — не ломает прогон
            return {"written": 0, "skipped": 0, "reason": f"ошибка подготовки: {exc}"}

    def _prepare_marker_table(self, field: str, run_dir) -> dict:
        """Подготовить плоскую таблицу отбивок для импорта маркеров (если требуется).

        Пишет ТОЛЬКО в каталог прогона. Источник (данные поля) не изменяется — это
        проверяется контролем `data_integrity` (хеши до/после).
        """
        try:
            graph = self.project_graph(field) or {}
            info = self._marker_format_check(graph)
            if not info.get("needs_conversion"):
                return {"verdict": "passed", "action": "not_needed",
                        "format": info.get("detected"), "file": info.get("file")}
            inputs = dict(graph.get("inputs") or {})
            source = None
            for key in ("welltop", "well_tops"):
                if inputs.get(key):
                    from core.config import SERVICE_ROOT
                    p = Path(str(inputs[key]))
                    p = p if p.is_absolute() else Path(SERVICE_ROOT) / p
                    if p.is_file():
                        source = p
                        break
            if source is None:
                return {"verdict": "unverified", "action": "source_not_found"}
            import importlib.util
            tool = Path(__file__).resolve().parent.parent / "tools" / "prepare_marker_table.py"
            spec = importlib.util.spec_from_file_location("_pmt", tool)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)                # type: ignore[union-attr]
            rows, fmt = mod.parse_well_tops(source)
            if not rows:
                return {"verdict": "unverified", "action": "empty_table",
                        "source": source.name, "format": fmt}
            out = Path(run_dir) / "Markers" / "markers.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(mod.to_flat_table(rows), encoding="utf-8")
            return {"verdict": "passed", "action": "converted",
                    "source": source.name, "format": fmt,
                    "rows": len(rows), "wells": len({w for w, _m, _d in rows}),
                    "markers": len({m for _w, m, _d in rows}),
                    "written": str(out.relative_to(Path(run_dir))).replace("\\", "/")}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка подготовки: {exc}"}

    def _marker_format_check(self, graph: dict) -> dict:
        """Формат файла отбивок против ожиданий импортёра маркеров (данные онтологии)."""
        try:
            inputs = dict(graph.get("inputs") or {})
            root = None
            try:
                from core.config import SERVICE_ROOT
                rp = Path(str(graph.get("dataset_root") or ""))
                root = rp if rp.is_absolute() else Path(SERVICE_ROOT) / rp
            except Exception:                           # noqa: BLE001
                root = None
            candidate = None
            for key in ("welltop", "well_tops", "well_header"):
                value = inputs.get(key)
                if not value:
                    continue
                p = Path(str(value))
                p = p if p.is_absolute() or root is None else (root / p)
                if p.is_file():
                    candidate = p
                    break
            if candidate is None:
                return {"verdict": "unverified", "reason": "файл отбивок не найден"}
            head = candidate.read_text(encoding="utf-8", errors="replace").splitlines()[:12]
            first = (head[0] if head else "").strip()
            flat = False
            marker_column = False
            for line in head:
                parts = line.replace(",", " ").split()
                if len(parts) >= 3 and not line.strip().startswith("#"):
                    flat = True
                up = line.upper()
                if "MARKER" in up or "MD" in up:
                    marker_column = True
            # ожидаемые импортёром колонки — из шаблона (данные)
            expected = ["Well", "Marker", "MD"]
            if first.lower().startswith("#petrel"):
                return {"verdict": "unverified", "file": candidate.name,
                        "detected": "petrel_well_tops", "needs_conversion": True,
                        "expected_columns": expected,
                        "reason": ("файл в формате Petrel Well Tops; импортёр ожидает "
                                   "плоскую таблицу — требуется шаг конвертации")}
            # Плоской таблицы достаточно: имена колонок бывают иными (в т.ч. кириллица),
            # поэтому требование «найти MARKER/MD» давало ложный «unknown» на рабочем поле.
            if flat:
                return {"verdict": "passed", "file": candidate.name, "detected": "flat_table",
                        "needs_conversion": False, "expected_columns": expected,
                        "columns_verified": marker_column,
                        "reason": "плоская таблица пригодна для импорта маркеров"}
            return {"verdict": "unverified", "file": candidate.name, "detected": "unknown",
                    "needs_conversion": True, "expected_columns": expected,
                    "reason": "формат не распознан как плоская таблица"}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка проверки: {exc}"}

    def _apply_composition_rules(self, graph: dict) -> dict:
        """Перенести экспортные шаги, нарушающие поток объектов, в конец их списка.

        Триггер — ДАННЫЕ потока (кто что создаёт/потребляет), а не эвристика: у поля с
        проектным графом нарушений нет (проверено: object_flow passed), поэтому его состав
        не меняется. У нового объекта выгрузки стоят раньше производителей (ТЕСТ2: позиция 0
        — map_2d_export_ascii_format) — такие шаги переносятся в конец, после моделирования.
        """
        try:
            path = (Path(__file__).resolve().parent.parent / "ontology"
                    / "object_binding_rules.yaml")
            if not path.is_file():
                return graph
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            wiring = dict(rules.get("wiring") or {})
            exports = {str(x) for x in ((wiring.get("composition") or {})
                                        .get("export_functions") or [])}
            producers = {str(k): dict(v or {}) for k, v in (wiring.get("producers") or {}).items()}
            consumers = {str(k): dict(v or {}) for k, v in (wiring.get("consumers") or {}).items()}
            if not exports:
                return graph
            produced: set = set()
            moved = 0

            def entries_of(fn: str):
                raw = dict(consumers.get(fn) or {})
                if "arg" in raw:
                    return [(str(raw.get("arg") or ""), str(raw.get("role") or ""))]
                return [(str(k), str((v or {}).get("role") or "")
                         if isinstance(v, dict) else str(v)) for k, v in raw.items()]

            def note_production(fn: str) -> None:
                sp = dict(producers.get(fn) or {})
                if sp:
                    produced.add(str(sp.get("role") or ""))
                    for _a, s2 in dict(sp.get("also_produces") or {}).items():
                        if isinstance(s2, dict):
                            for alt in dict(s2.get("role_by_marker") or {}).values():
                                produced.add(str(alt))
                        else:
                            produced.add(str(s2))

            pending: list = []          # выгрузки с нарушением — в КОНЕЦ всего пайплайна
            last_list: list = []

            def process(lst) -> None:
                nonlocal moved, last_list
                last_list = lst
                keep = []
                for step in lst:
                    if not isinstance(step, dict):
                        keep.append(step)
                        continue
                    fn = str(step.get("function") or "")
                    if fn:
                        bad = any(role and role not in produced for _a, role in entries_of(fn))
                        # двигаем ЛЮБОЙ шаг с неудовлетворённой зависимостью (round 198):
                        # не только выгрузки — иначе импорт карты, требующий маркер, идёт
                        # раньше импорта маркеров (проверено на ТЕСТ2).
                        if bad:
                            pending.append(step)
                            moved += 1
                            continue
                        keep.append(step)
                        note_production(fn)
                    else:
                        for value in step.values():
                            if isinstance(value, list):
                                process(value)
                        keep.append(step)
                lst[:] = keep

            process(graph.get("pipeline") or [])
            if pending and last_list is not None:
                last_list.extend(pending)   # выгрузки — после всех производителей
            graph["_composition_moved"] = moved
            return graph
        except Exception:                               # noqa: BLE001 — не ломает прогон
            return graph

    def _mark_unresolved_exports(self, graph: dict) -> dict:
        """Пометить к пропуску экспортные шаги БЕЗ разрешённого объекта (правила — данные)."""
        try:
            path = (Path(__file__).resolve().parent.parent / "ontology"
                    / "object_binding_rules.yaml")
            if not path.is_file():
                return graph
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            comp = dict((rules.get("wiring") or {}).get("composition") or {})
            exports = {str(x) for x in (comp.get("export_functions") or [])}
            if not exports:
                return graph
            bindings = {str(k): dict(v or {}) for k, v in (rules.get("bindings") or {}).items()}
            marked = 0
            for step in self._iter_steps(graph.get("pipeline") or []):
                fn = str(step.get("function") or "")
                if fn not in exports or step.get("requires_object"):
                    continue
                bound = set((step.get("objects") or {}).keys())
                bound |= set((step.get("parameters") or {}).keys())
                bound |= set((step.get("lists") or {}).keys())
                needed = [str(a) for a, s in bindings.items()
                          if str((s or {}).get("role") or "") and a not in bound]
                # объектных привязок нет вовсе → выгружать нечего
                if not bound or (not step.get("objects") and needed):
                    step["requires_object"] = needed[0] if needed else "export_object"
                    step["skip_reason"] = ("выгрузка без разрешённого объекта: "
                                           + (", ".join(needed[:3]) or "объект не задан"))
                    marked += 1
            graph["_unresolved_exports_marked"] = marked
            return graph
        except Exception:                               # noqa: BLE001 — не ломает прогон
            return graph

    def _apply_object_model(self, graph: dict) -> dict:
        """Заполнить `objects` шагов, у которых привязок НЕТ (универсальность поля).

        Шаги с уже заданными привязками НЕ меняются (поле с проектным графом работает как
        раньше). Для остальных: аргумент шаблона → конкретная роль (`bindings`) → имя из
        данных поля либо порождённое правилами (`naming`). Роли, которые разрешить не
        удалось, не подставляются вовсе (правило 6) — тогда шаг останется с шаблонным
        значением, а конфликт зафиксирует контроль (`objects.bindings_resolved`).
        """
        try:
            path = (Path(__file__).resolve().parent.parent / "ontology"
                    / "object_binding_rules.yaml")
            if not path.is_file():
                return graph
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            bindings = {str(k): dict(v or {}) for k, v in (rules.get("bindings") or {}).items()}
            proposal = self._object_model_proposal(graph)
            role_values: dict = {}
            for role, spec in (proposal.get("produced_roles") or {}).items():
                if (spec or {}).get("name"):
                    role_values[str(role)] = str(spec["name"])
            # значения ролей-«сырьё» (маркеры, скважины) — из данных поля
            markers = dict(graph.get("markers") or {})
            for role, key in (("reservoir_top", "reservoir_top"),
                              ("reservoir_base", "reservoir_base")):
                if markers.get(key):
                    role_values.setdefault(role, str(markers[key]))
            inputs = dict(graph.get("inputs") or {})
            for role, key in (("well_header", "wellhead"), ("well_tops", "welltop"),
                              ("well_logs", "well_logs"), ("boundary", "boundary")):
                if inputs.get(key):
                    role_values.setdefault(role, str(Path(str(inputs[key])).name))
            if not role_values:
                return graph
            # АДРЕСНО (round 170): заполняем ТОЛЬКО те аргументы, которые контроль
            # `objects.bindings_resolved` признал незаполненными И обязательными. У поля с
            # проектным графом таких нет (0 позиций) — значит рабочее поле не может быть
            # задето по построению, в отличие от массовой подстановки (round 169: 16
            # предупреждений и 3 красных теста).
            kinds = {str(k): str((v or {}).get("kind") or "")
                     for k, v in (rules.get("roles") or {}).items()}
            unresolved = {(str(u.get("function")), str(u.get("argument")))
                          for u in (self._objects_bindings_check(graph).get("unresolved") or [])}
            if not unresolved:
                return graph
            applied = 0
            for step in self._iter_steps(graph.get("pipeline") or []):
                fn = str(step.get("function") or "")
                objs = dict(step.get("objects") or {})
                lists = dict(step.get("lists") or {})
                eff = self._bindings_for(rules, fn)
                for arg, spec in eff.items():
                    if (fn, str(arg)) not in unresolved:
                        continue
                    role = str(spec.get("role") or "")
                    value = role_values.get(role)
                    vkind = str(spec.get("value_kind") or "")
                    if vkind == "list":
                        # путь берём по РОЛИ: маркеры → таблица отбивок, траектории → таблица траекторий
                        prep_key = ("prepared_marker_table" if role == "well_tops"
                                    else "prepared_trajectories")
                        prepared = dict(rules.get(prep_key) or {})
                        table = str(prepared.get("path") or "")
                        if role == "well_tops" and table and arg not in lists:
                            lists[str(arg)] = [table]
                            applied += 1
                        continue
                    if not value or arg in objs:
                        continue
                    objs[str(arg)] = {"obj_name": value,
                                      "obj_type": kinds.get(role) or "Object"}
                    applied += 1
                if objs and objs != (step.get("objects") or {}):
                    step["objects"] = objs
                if lists and lists != (step.get("lists") or {}):
                    step["lists"] = lists
            graph["_object_model_applied"] = applied
            return graph
        except Exception:                               # noqa: BLE001 — не ломает прогон
            return graph

    def _object_model_proposal(self, graph: dict) -> dict:
        """Что генератор объектной модели создал бы по правилам онтологии (отчёт)."""
        try:
            path = (Path(__file__).resolve().parent.parent / "ontology"
                    / "object_binding_rules.yaml")
            if not path.is_file():
                return {"verdict": "unverified", "reason": "правила привязок не найдены"}
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            naming = dict((rules.get("naming") or {}).get("rules") or {})
            bindings = {str(k): dict(v or {}) for k, v in (rules.get("bindings") or {}).items()}
            inputs = dict(graph.get("inputs") or {})
            markers = dict(graph.get("markers") or {})
            values = {"marker": markers.get("reservoir_top") or markers.get("reservoir_base"),
                      "reservoir": str(graph.get("reservoir_horizon") or ""),
                      "source": markers.get("reservoir_top")}
            # ИМЯ ИЗ ДАННЫХ ПОЛЯ ПРИОРИТЕТНЕЕ ШАБЛОНА (round 161): если план поля уже связал
            # аргумент с объектом (через `objects`), берём ЭТО имя; шаблон применяется
            # только там, где поле объект не задало. Роль аргумента — из данных (`bindings`).
            existing: dict = {}
            producers = dict((rules.get("wiring") or {}).get("producers") or {})
            top_name = str(markers.get("reservoir_top") or "")
            base_name = str(markers.get("reservoir_base") or "")
            for step in self._iter_steps(graph.get("pipeline") or []):
                fn = str(step.get("function") or "")
                spec_p = dict(producers.get(fn) or {})
                if not spec_p:
                    continue                                # имя берём ТОЛЬКО у производителей
                objs = dict(step.get("objects") or {})
                from_arg = str(spec_p.get("from") or "")
                raw = objs.get(from_arg)
                name = (raw or {}).get("obj_name") if isinstance(raw, dict) else raw
                role = str(spec_p.get("role") or "")
                disc = str(spec_p.get("discriminate_by") or "")
                if disc and disc in objs:
                    got = objs[disc]
                    val = str(((got or {}).get("obj_name") if isinstance(got, dict) else got) or "")
                    if top_name and val == top_name:
                        role = "horizon_top"
                    elif base_name and val == base_name:
                        role = "horizon_base"
                if role and name:
                    # уточнение роли по имени объекта (данные: role_if_name_matches)
                    for pat, alt in dict(spec_p.get("role_if_name_matches") or {}).items():
                        if str(pat) in str(name):
                            role = str(alt)
                    existing[role] = str(name)              # последний производитель побеждает
                # дополнительные объекты, создаваемые тем же шагом (данные: also_produces).
                # Значение — либо имя роли, либо правила по значению маркера шага.
                for arg2, spec2 in dict(spec_p.get("also_produces") or {}).items():
                    raw2 = objs.get(str(arg2))
                    name2 = (raw2 or {}).get("obj_name") if isinstance(raw2, dict) else raw2
                    if not name2:
                        continue
                    if isinstance(spec2, dict):
                        role2 = str(spec2.get("role") or "")
                        for mrole, alt in dict(spec2.get("role_by_marker") or {}).items():
                            marker_val = top_name if str(mrole) == "reservoir_top" else base_name
                            got2 = objs.get(disc) if disc else None
                            cur = str(((got2 or {}).get("obj_name") if isinstance(got2, dict)
                                       else got2) or "")
                            if cur and marker_val and cur == marker_val:
                                role2 = str(alt)
                    else:
                        role2 = str(spec2)
                    if role2:
                        existing[role2] = str(name2)
            # разворачиваем роли в имена: данные поля → иначе шаблон naming
            produced: dict = {}
            for role, spec in naming.items():
                if existing.get(role):
                    produced[role] = {"name": existing[role], "origin": "field_data"}
                    continue
                tpl = str((spec or {}).get("template") or "")
                src = str((spec or {}).get("source") or "")
                if src.startswith("markers."):
                    key = src.split(".", 1)[1]
                    values.setdefault("marker", markers.get(key))
                    data = {**values, "marker": markers.get(key)}
                else:
                    data = dict(values)
                name = tpl
                for k, v in data.items():
                    name = name.replace("{" + k + "}", str(v or ""))
                if "{" in name or not name.strip() or "__todo__" in name or "__todo__" in tpl:
                    # заглушка («__todo__») НИКОГДА не склеивается с шаблоном имени:
                    # при отсутствии источника имя не формируется вовсе (правило 6).
                    produced[role] = {"name": None, "reason": "нет источника данных"}
                else:
                    produced[role] = {"name": name}
            # какие привязки получаются для ролей из bindings
            role_names = {"surface": produced.get("surface", {}).get("name"),
                          "surface_base": produced.get("surface_base", {}).get("name"),
                          "reservoir_top": markers.get("reservoir_top"),
                          "reservoir_base": markers.get("reservoir_base")}
            proposed = {}
            for arg, spec in bindings.items():
                role = str(spec.get("role") or "")
                if role in role_names:
                    proposed[arg] = {"role": role, "value": role_names.get(role),
                                     "required": bool(spec.get("required"))}
            unresolved = sorted(a for a, v in proposed.items()
                                if v.get("required") and not v.get("value"))
            ok = not unresolved and bool(proposed)
            return {"verdict": "passed" if ok else "unverified",
                    "produced_roles": produced, "proposed_bindings": proposed,
                    "unresolved_required": unresolved,
                    "field_roles": {"reservoir_top": markers.get("reservoir_top"),
                                    "reservoir_base": markers.get("reservoir_base"), 
                                    "surface_input": inputs.get("surface")}}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка построения модели: {exc}"}

    @staticmethod
    def _bindings_for(rules: dict, fn: str) -> dict:
        """Привязки аргументов для КОНКРЕТНОЙ функции: глобальные + переопределения.

        Один и тот же аргумент в разных шагах берёт разные данные (ile_names импорта
        маркеров → таблица отбивок, импорта траекторий → таблица траекторий). Переопределения
        заданы ДАННЫМИ в indings_by_function.
        """
        base = {str(k): dict(v or {}) for k, v in (rules.get("bindings") or {}).items()}
        over = {str(k): dict(v or {}) for k, v in
                ((rules.get("bindings_by_function") or {}).get(fn) or {}).items()}
        base.update(over)
        return base

    def _objects_bindings_check(self, graph: dict) -> dict:
        """Незаполненные обязательные привязки объектов — по правилам онтологии."""
        try:
            path = (Path(__file__).resolve().parent.parent / "ontology"
                    / "object_binding_rules.yaml")
            if not path.is_file():
                return {"verdict": "unverified", "reason": "правила привязок не найдены"}
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            bindings = {str(k): dict(v or {}) for k, v in (rules.get("bindings") or {}).items()}
            optional = {str(x) for x in (rules.get("optional_steps") or [])}
            unresolved: list = []
            total = 0
            import re as _re
            cache: dict = {}

            def _fn_object_args(fn: str) -> set:
                """Объектные аргументы ЭТОЙ функции — из её шаблона (данные, не догадки)."""
                if fn not in cache:
                    try:
                        tdir = self.cfg.path("workflow.templates_dir", "domain/templates")
                        tpath = Path(tdir) / f"{fn}.txt"
                        cache[fn] = tpath.read_text(encoding="utf-8") if tpath.is_file() else ""
                    except Exception:                   # noqa: BLE001
                        cache[fn] = ""
                return set(_re.findall(
                    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[A-Za-z_][A-Za-z0-9_]*\s*\(\s*obj_name\s*=",
                    cache[fn]))

            # Перечень имён демо-проекта — из онтологии (данные).
            demo_names = set()
            try:
                demo_names = set(str(x) for x in self._template_demo_names())
            except Exception:                           # noqa: BLE001
                demo_names = set()

            def _foreign_default_args(fn: str) -> set:
                """Аргументы, чьё значение по умолчанию — ИМЯ ДЕМО-ПРОЕКТА (round 171).

                Такое значение обязано прийти из данных поля: у рабочего поля значения свои,
                поэтому оно не затрагивается; у нового объекта это «протечка» шаблона.
                """
                _fn_object_args(fn)                     # заполнить кэш текстом шаблона
                text = cache.get(fn) or ""
                return {a for a, v in _re.findall(
                    r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]*)"', text)
                    if v and v in demo_names}

            for step in self._iter_steps(graph.get("pipeline") or []):
                fn = str(step.get("function") or "")
                if not fn or fn in optional:
                    continue
                bound = set((step.get("objects") or {}).keys())
                bound |= set((step.get("parameters") or {}).keys())
                bound |= set((step.get("lists") or {}).keys())
                eff = self._bindings_for(rules, fn)
                for arg in sorted(_fn_object_args(fn) & set(eff)):
                    spec = eff[arg]
                    if not spec.get("required"):
                        continue
                    total += 1
                    if arg not in bound:
                        unresolved.append({"function": fn, "argument": arg,
                                           "role": spec.get("role")})
                # «протечки» демо-имён: аргумент обязан быть привязан данными поля
                for arg in sorted(_foreign_default_args(fn) & set(bindings)):
                    if arg not in bound:
                        spec = bindings[arg]
                        unresolved.append({"function": fn, "argument": arg,
                                           "role": spec.get("role"),
                                           "reason": "значение шаблона — имя демо-проекта"})
            verdict = "passed" if not unresolved else "unverified"
            return {"verdict": verdict, "checked_required": total,
                    "unresolved": unresolved[:40], "unresolved_count": len(unresolved),
                    "optional_steps": sorted(optional)}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка проверки: {exc}"}

    def _pvt_scal_ensemble_check(self, graph: dict) -> dict:
        """Провенанс корреляций PVT/SCAL и соответствие ансамбля правилам онтологии."""
        try:
            root = Path(__file__).resolve().parent.parent / "ontology"
            import yaml
            out: dict = {}
            verdict = "passed"
            ps_path = root / "pvt_scal_rules.yaml"
            if ps_path.is_file():
                ps = yaml.safe_load(ps_path.read_text(encoding="utf-8")) or {}
                graph_pvt = dict(graph.get("pvt") or {})
                graph_scal = dict(graph.get("scal") or {})
                items = {}
                for key, spec in {"pvt": ps.get("pvt"), "scal": ps.get("scal")}.items():
                    spec = dict(spec or {})
                    declared = bool(spec.get("correlations") or spec.get("methods"))
                    prov = spec.get("provenance", "missing")
                    present = bool(graph_pvt if key == "pvt" else graph_scal)
                    ok = declared and prov != "missing"
                    items[key] = {"declared": declared, "provenance": prov,
                                  "field_values_present": present,
                                  "verdict": "passed" if ok else "unverified"}
                    if not ok and verdict == "passed":
                        verdict = "unverified"
                out["pvt_scal"] = items
            en_path = root / "ensemble_rules.yaml"
            if en_path.is_file():
                en = yaml.safe_load(en_path.read_text(encoding="utf-8")) or {}
                policy = dict(en.get("policy") or {})
                min_b = int(policy.get("min_branches") or 1)
                variations = graph.get("variations") or []
                n_var = len(variations) if isinstance(variations, list) else 0
                sel = dict(en.get("selection") or {})
                ok = n_var >= min_b and bool(sel.get("primary"))
                out["ensemble"] = {"branches_declared": n_var, "min_branches": min_b,
                                   "selection_primary": sel.get("primary"),
                                   "tie_break": policy.get("tie_break"),
                                   "verdict": "passed" if ok else "unverified"}
                if not ok and verdict == "passed":
                    verdict = "unverified"
            return {"verdict": verdict, **out}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка проверки: {exc}"}

    def _curve_continuity(self, curves: dict) -> dict:
        """Непрерывность кривых по правилу онтологии (`curve_continuity`, данные)."""
        path = Path(__file__).resolve().parent.parent / "ontology" / "petrophysics_rules.yaml"
        spec: dict = {}
        if path.is_file():
            try:
                import yaml
                rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                spec = dict(rules.get("curve_continuity") or {})
            except Exception:                           # noqa: BLE001
                spec = {}
        min_unique = int(spec.get("min_unique") or 20)
        max_share = float(spec.get("dominant_share_max") or 0.5)
        items: dict = {}
        verdict = "passed"
        for cube, info in (curves or {}).items():
            uniq = info.get("unique")
            n = info.get("n")
            med = info.get("median")
            share = None
            if uniq and n and med is not None and uniq <= 3:
                # при 1–3 значениях медиана и есть доминанта
                share = 1.0 if uniq == 1 else None
            flag = bool(uniq is not None and n and uniq < min_unique)
            items[cube] = {"log": info.get("log"), "unique": uniq, "n": n,
                           "dominant_share": share, "min_unique": min_unique,
                           "dominant_share_max": max_share,
                           "verdict": (str(spec.get("on_detect") or "unverified") if flag
                                       else "passed"),
                           "reason": ("кривая дискретизирована (уникальных значений "
                                      f"{uniq} < {min_unique}) — куб не является непрерывным "
                                      "свойством" if flag else "непрерывность достаточна")}
            if flag and verdict == "passed":
                verdict = str(spec.get("on_detect") or "unverified")
        return {"verdict": verdict, "curves": items,
                "action": spec.get("action"), "min_unique": min_unique,
                "dominant_share_max": max_share}

    def _qaqc_provenance_check(self, graph: dict) -> dict:
        """Провенанс порогов приёмки и наличие объявленных блоков чеклиста (данные)."""
        try:
            root = Path(__file__).resolve().parent.parent / "ontology"
            path = root / "thresholds_rules.yaml"
            if not path.is_file():
                return {"verdict": "unverified", "reason": "правила порогов не найдены"}
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            declared = dict(rules.get("thresholds") or {})
            graph_thresholds = dict(graph.get("thresholds") or {})
            items: dict = {}
            verdict = "passed"
            for key, value in {**declared, **graph_thresholds}.items():
                spec = dict(declared.get(key) or {})
                source = spec.get("source")
                prov = spec.get("provenance", "missing")
                ok = bool(source and prov != "missing")
                items[str(key)] = {"value": value if key in graph_thresholds else spec.get("range"),
                                   "source": source, "provenance": prov,
                                   "checklist_refs": spec.get("checklist_refs") or [],
                                   "verdict": "passed" if ok else "unverified"}
                if not ok and verdict == "passed":
                    verdict = "unverified"
            # блоки чеклиста: объявленные должны присутствовать в оцифрованных данных
            blocks = [str(b) for b in ((rules.get("checklist") or {}).get("blocks_in_scope") or [])]
            qa_dir = root / "qa_checks"
            available = sorted(p.stem for p in qa_dir.glob("*.csv")) if qa_dir.is_dir() else []
            present = [b for b in blocks
                       if any(b in name for name in available) or any(b in name for name in [str(qa_dir)])]
            missing_blocks = [b for b in blocks if b not in present]
            traceability = {"declared_blocks": blocks, "digitalized_files": available,
                            "present_blocks": present, "missing_blocks": missing_blocks,
                            "verdict": "passed" if (blocks and not missing_blocks) else
                                       ("unverified" if not available else "failed")}
            return {"verdict": verdict, "thresholds": items, "traceability": traceability}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка проверки: {exc}"}

    def _petro_null_values(self) -> list:
        """Список бланков LAS — ИЗ ОНТОЛОГИИ (`petrophysics_rules.log_preparation`)."""
        path = Path(__file__).resolve().parent.parent / "ontology" / "petrophysics_rules.yaml"
        if not path.is_file():
            return []
        try:
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:                               # noqa: BLE001
            return []
        return [float(x) for x in ((rules.get("log_preparation") or {}).get("null_values") or [])]

    def _petro_measured_check(self, graph: dict) -> dict:
        """Измеренные min/медиана/max кривых ГИС против ожидаемых диапазонов (данные)."""
        try:
            import statistics as _st
            pp = dict(graph.get("petrophysics") or {})
            cubes = [c for c in (pp.get("cubes") or []) if isinstance(c, dict)]
            expect = dict(pp.get("expect") or {})
            scale = dict(pp.get("scale") or {})
            if not cubes:
                return {"verdict": "unverified", "reason": "в данных поля не описаны кубы"}
            inputs = dict(graph.get("inputs") or {})
            root = None
            try:
                from core.config import SERVICE_ROOT
                rp = Path(str(graph.get("dataset_root") or ""))
                root = rp if rp.is_absolute() else Path(SERVICE_ROOT) / rp
            except Exception:                           # noqa: BLE001
                root = None
            candidates: list[Path] = []
            # Ключи входов различаются между полями (данные), поэтому каталог ГИС ищем по
            # ВСЕМ входам графа, а не по одному «ожидаемому» имени (правило 1).
            roots: list[Path] = []
            for _k, value in inputs.items():
                if not value:
                    continue
                p = Path(str(value))
                roots.append(p if p.is_absolute() or root is None else (root / p))
            for p in roots:
                if p.is_dir():
                    # приоритет — файлы каротажа (.las), затем любые поддерживаемые
                    las = [q for q in sorted(p.rglob("*")) if q.is_file() and q.suffix.lower() == ".las"]
                    if las:
                        candidates = las
                        break
                    found = [q for q in sorted(p.rglob("*"))
                             if q.is_file() and q.suffix.lower() in (".txt", ".csv")]
                    if found and not candidates:
                        candidates = found
                elif p.is_file() and p.suffix.lower() == ".las":
                    candidates = [p]
                    break
            if not candidates:
                return {"verdict": "unverified", "reason": "файлы ГИС не найдены"}
            wanted = {str(c.get("log")): str(c.get("cube")) for c in cubes if c.get("log")}
            values: dict = {k: [] for k in wanted}
            for path in candidates:
                if path.suffix.lower() not in (".las", ".txt", ".csv"):
                    continue
                section = ""
                names: list = []
                rows: list = []
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for line in text.splitlines():
                    s = line.strip()
                    if s.startswith("~"):
                        section = s[:2].upper()
                        continue
                    if section == "~C" and ":" in s:
                        # МНЕМОНИКА — ДО двоеточия; после двоеточия идёт ОПИСАНИЕ
                        # (`<мнемоника>. : описание кривой`). Проверено на LAS поля.
                        head = s.split(":", 1)[0].strip()
                        names.append(head.strip(".").upper())
                    elif section == "~A" and s and not s.startswith("#"):
                        rows.append(s.replace(",", " ").split())
                idx = {n: i for i, n in enumerate(names)}
                for mnem, bucket in values.items():
                    i = idx.get(str(mnem).upper())
                    if i is None:
                        continue
                    for row in rows:
                        if i < len(row):
                            try:
                                bucket.append(float(row[i]))
                            except ValueError:
                                continue
            out: dict = {}
            verdict = "passed"
            # БЛАНКИ: список null-маркеров — ДАННЫЕ (сначала граф поля, затем онтология,
            # `petrophysics_rules.yaml → log_preparation.null_values`). Исключаем их из
            # статистики полностью: неисключённые бланки искажают min/max и кубы.
            blanks: list = []
            for src in (pp.get("null_values"), self._petro_null_values()):
                if src:
                    blanks = [float(x) for x in src]
                    break

            def _is_blank(v: float) -> bool:
                return any(abs(v - b) < 1e-6 for b in blanks)

            excluded = 0
            for mnem, cube in wanted.items():
                vals = []
                for v in values.get(mnem, []):
                    if _is_blank(v):
                        excluded += 1
                        continue
                    vals.append(v)
                vals.sort()
                blanks_here = sum(1 for v in values.get(mnem, []) if _is_blank(v))
                exp = dict(expect.get(mnem) or {})
                lo, hi = exp.get("min"), exp.get("max")
                if not vals:
                    out[cube] = {"verdict": "unverified", "reason": "значений кривой нет"}
                    if verdict == "passed":
                        verdict = "unverified"
                    continue
                med = _st.median(vals)
                ok = not ((lo is not None and med < float(lo)) or
                          (hi is not None and med > float(hi)))
                out[cube] = {"verdict": "passed" if ok else "failed", "log": mnem,
                             "units": exp.get("units"),
                             "scale": float(scale.get(mnem) or 1.0),
                             "n": len(vals), "median": round(med, 4),
                             "unique": len(set(vals)), "blanks": blanks_here,
                             "non_blank_share": round(len(vals) / max(1, len(vals) + blanks_here), 4),
                             "min": round(vals[0], 4), "max": round(vals[-1], 4),
                             "expected": [lo, hi]}
                if not ok:
                    verdict = "failed"
            # ИСТОЧНИК ПРОНИЦАЕМОСТИ (замечание №2): показываем, откуда взято свойство
            # и законно ли это. Правило — ДАННЫЕ (`perm_from_poro`), измерение — из кривых.
            pf = dict(pp.get("perm_from_poro") or {})
            coeffs = (float(pf.get("a") or 0.0), float(pf.get("b") or 0.0))
            if pf.get("enabled") and any(c != 0.0 for c in coeffs):
                perm_source = {"source": "relation", "form": pf.get("form"),
                               "rule": pf.get("source_rule"),
                               "status": pf.get("knowledge_status"),
                               "verdict": "passed"}
            else:
                # Куб проницаемости — ДАННЫЕ (`perm_from_poro.target_cube`). Если поле его
                # не задало, источник проницаемости НЕ угадывается по метке единиц
                # (метки — словарь конкретного поля, правило 1) и не подменяется нулём:
                # это честный unknown (правило 6).
                target = str(pf.get("target_cube") or "")
                curve_info = dict(out.get(target) or {}) if target else {}
                if not target:
                    perm_source = {
                        "source": "unknown", "log": "", "units": "",
                        "verdict": "unverified",
                        "reason": ("куб проницаемости не задан в данных поля "
                                   "(`perm_from_poro.target_cube`) — источник "
                                   "проницаемости по кривой не определяется без данных "
                                   "(правило 6)")}
                else:
                    perm_source = {"source": "curve", "log": curve_info.get("log"),
                                   "units": curve_info.get("units"),
                                   "measured_median": curve_info.get("median"),
                                   "unique": curve_info.get("unique"),
                                   "non_blank_share": curve_info.get("non_blank_share"),
                                   "blanks_excluded": excluded,
                                   "verdict": "failed",
                                   "reason": ("проницаемость берётся из кривой, а не из "
                                              "зависимости k-φ: коэффициенты связи не "
                                              "заданы (нужны керновые пары либо "
                                              "литературные коэффициенты)")}
            return {"verdict": verdict, "curves": out, "files": len(candidates),
                    "blanks_excluded": excluded, "perm_source": perm_source,
                    "continuity": self._curve_continuity(out)}
        except Exception as exc:                        # noqa: BLE001 — не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка измерения: {exc}"}

    def _bullseye_report(self, run_dir, graph: dict | None = None) -> dict:
        """Измерение локальной подсадки поверхностей после прогона (если есть выгрузки).

        Имена файлов НЕ задаются в коде (правило 1): таблица скважин берётся из ролей
        онтологии/графа поля, поверхности — из шагов выгрузки, объявленных в данных.
        """
        try:
            import importlib.util
            run_dir = Path(run_dir)
            graph = dict(graph or {})
            inputs = dict(graph.get("inputs") or {})
            # скважины: сначала роль из графа поля, иначе любой файл по маске скважин
            wells = None
            cand = str(inputs.get("wellhead") or inputs.get("well_header") or "")
            if cand and (run_dir / Path(cand).name).is_file():
                wells = run_dir / Path(cand).name
            if wells is None:
                for p in sorted(run_dir.glob("*")):
                    if p.is_file() and any(t in p.name.lower()
                                           for t in ("wellhead", "well_header", "header")):
                        wells = p
                        break
            if wells is None:
                return {"verdict": "unverified", "reason": "нет таблицы скважин для контроля"}
            # поверхности: имена выгрузок — из данных (шаги export), иначе по расширению
            wanted: list[str] = []
            for step in self._iter_steps(graph.get("pipeline") or []):
                params = dict(step.get("parameters") or {})
                fname = str(params.get("file_name") or "")
                if fname and fname.endswith(".txt") and "cps" in str(step.get("function", "")):
                    wanted.append(Path(fname).name)
            candidates: list[Path] = []
            for name in wanted:
                if (run_dir / name).is_file():
                    candidates.append(run_dir / name)
            if not candidates:
                candidates = [p for p in sorted(run_dir.glob("*_cps.txt")) if p.is_file()]
            if not candidates:
                return {"verdict": "unverified", "reason": "выгрузок поверхностей нет"}
            tool = Path(__file__).resolve().parent.parent / "tools" / "check_surface_bullseye.py"
            if not tool.is_file():
                return {"verdict": "unverified", "reason": "инструмент контроля не найден"}
            spec = importlib.util.spec_from_file_location("_bs", tool)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)            # type: ignore[union-attr]
            rules = self._struct_rules_summary().get("bullseye_qc") or {}
            radius = int(rules.get("radius_cells") or 3)
            thr = float(rules.get("threshold") or 10.0)
            results = {}
            worst_verdict = "passed"
            for surface in candidates:
                res = mod.bullseyes_geo(surface, wells, radius, thr)
                results[surface.name] = res
                if res.get("verdict") == "failed":
                    worst_verdict = "failed"
                elif res.get("verdict") == "unverified" and worst_verdict == "passed":
                    worst_verdict = "unverified"
            return {"verdict": worst_verdict, "radius_cells": radius, "threshold": thr,
                    "surfaces": results}
        except Exception as exc:                    # noqa: BLE001 — контроль не ломает прогон
            return {"verdict": "unverified", "reason": f"ошибка измерения: {exc}"}

    @staticmethod
    def _iter_steps(items):
        """Все шаги плана (в т.ч. вложенные в этапы) — без доменных имён в коде."""
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("function"):
                yield it
                continue
            for value in it.values():
                if isinstance(value, list):
                    yield from Coordinator._iter_steps(value)
                elif isinstance(value, dict) and value.get("function"):
                    yield value

    def _struct_rules_summary(self) -> dict:
        """Что из правил структуры/геостатики онтологии доступно конвейеру."""
        path = Path(__file__).resolve().parent.parent / "ontology" / "structural_geostat_rules.yaml"
        if not path.is_file():
            return {"verdict": "unverified", "reason": "файл правил не найден"}
        try:
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:                               # noqa: BLE001
            return {"verdict": "unverified", "reason": "файл правил не читается"}
        st = dict(rules.get("structural") or {})
        base = dict(st.get("base_from_top") or {})
        erosion = dict(st.get("erosion") or {})
        qc = dict(st.get("qc") or {})
        var = dict((rules.get("geostatistics") or {}).get("variogram") or {})
        return {"verdict": "passed" if (base or qc) else "unverified",
                "base_from_top": {"enabled": base.get("enabled"), "method": base.get("method"),
                                  "trend_source": base.get("trend_source")},
                "erosion": {"threshold": erosion.get("enabled_when_top_coverage_lt"),
                            "on_skip": erosion.get("on_skip")},
                "bullseye_qc": {"check_id": qc.get("check_id"),
                                "radius_cells": qc.get("radius_cells"),
                                "threshold": qc.get("threshold")},
                "variogram": {"type": var.get("type"), "range_main": var.get("range_main")}}

    def _petro_rules_summary(self) -> dict:
        """Что из петрофизических правил онтологии доступно конвейеру."""
        path = Path(__file__).resolve().parent.parent / "ontology" / "petrophysics_rules.yaml"
        if not path.is_file():
            return {"verdict": "unverified", "reason": "файл правил не найден"}
        try:
            import yaml
            rules = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:                               # noqa: BLE001
            return {"verdict": "unverified", "reason": "файл правил не читается"}
        prep = dict(rules.get("log_preparation") or {})
        model = dict(rules.get("permeability_model") or {})
        ladder = [str(x.get("id")) for x in (model.get("source_ladder") or [])
                  if isinstance(x, dict)]
        core = dict(rules.get("core_data_contract") or {})
        return {"verdict": "passed" if (prep and model) else "unverified",
                "null_values": prep.get("null_values"),
                "null_policy": prep.get("null_policy"),
                "unit_check": {"enabled": (prep.get("unit_check") or {}).get("enabled"),
                               "on_mismatch": (prep.get("unit_check") or {}).get("on_mismatch")},
                "scale_from_data": prep.get("scale_from_data"),
                "perm_source_ladder": ladder,
                "core_fit": core.get("fit"),
                "constraints": model.get("constraints")}

    def _ontology_rules_summary(self) -> dict:
        """Какие файлы правил онтологии загружены и какие проверки в них объявлены."""
        root = Path(__file__).resolve().parent.parent / "ontology"
        files: dict = {}
        for path in sorted(root.glob("*rules*.yaml")) + sorted(root.glob("qa_gate_map.yaml")):
            try:
                import yaml
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception:                           # noqa: BLE001 — данные опциональны
                continue
            ids = []
            for chk in (data.get("checks") or []):
                if isinstance(chk, dict) and chk.get("id"):
                    ids.append(str(chk["id"]))
            files[path.name] = {"sections": sorted(str(k) for k in data)[:12],
                                "declared_checks": ids}
        return {"files": files, "count": len(files),
                "verdict": "passed" if files else "unverified",
                "consumers": ["inputs/markers/formats (graph_generator)",
                              "data integrity (coordinator)",
                              "render controls (workflow_renderer)"]}

    def _reconcile_order(self, derived: dict, template: dict) -> dict:
        """Стадии и ПОРЯДОК шагов — из выверенного шаблона поля, состав — из онтологии.

        Зачем (F-26): производный состав идёт в порядке каталога онтологии, из-за чего
        экспорт карты оказывался ПЕРВЫМ шагом и падал («cannot find object "2D-Map
        Tl_thick"»), а гейты привязаны к стадиям моделирования. Здесь шаги
        раскладываются по стадиям шаблона в его порядке; шаг, которого нет в
        онтологическом выводе, сохраняется из шаблона; лишние онтологические шаги
        уходят в отдельную стадию в конце (имя — ДАННЫЕ).
        """
        tmpl_stages = [s for s in (template.get("pipeline") or []) if isinstance(s, dict)]
        if not tmpl_stages or not (derived.get("pipeline") or []):
            return derived
        by_fn: dict[str, list[dict]] = {}
        for st in derived["pipeline"]:
            for s in (st.get("steps") or []):
                if isinstance(s, dict) and s.get("function"):
                    by_fn.setdefault(str(s["function"]), []).append(dict(s))
        stages: list[dict] = []
        # ВАЖНО (F-27, открыто): попытка учесть неоднозначность повторов функций
        # (несколько выгрузок одной функции) не устранила падение покрытия отбивок
        # в режиме ontology и сломала тесты селекции — откат к проверенному варианту.
        # Диагностику F-27 вести сравнением ОТРЕНДЕРЕННЫХ шагов этапов «отбивки/марки»
        # в обоих режимах (см. docs/09_ПЛАН_остатка.md, пункт 2а).
        for tst in tmpl_stages:
            steps = []
            for tstep in (tst.get("steps") or []):
                if not isinstance(tstep, dict):
                    continue
                fn = str(tstep.get("function") or "")
                pool = by_fn.get(fn) or []
                base = dict(tstep)
                if pool:
                    # Базой остаётся шаг ШАБЛОНА (в нём объектные привязки поля:
                    # objects/params), а онтологический вывод ДОПОЛНЯЕТ недостающие
                    # ключи. Иначе рендер теряет привязки объектов — живой прогон:
                    # «cannot find object "2D-Map <имя>"», 1 карта из 8.
                    d = pool.pop(0)
                    for k, v in d.items():
                        if k in ("objects", "object", "stage", "steps"):
                            continue
                        base.setdefault(k, v)
                steps.append(base)
            if steps:
                stages.append({**tst, "steps": steps})
        extra = [s for pool in by_fn.values() for s in pool]
        mode = str(self.cfg.get("workflow.ontology_extra_steps", "skip") or "skip").lower()
        # `include` — включить безусловно; `agent` — включить и отдать применимость
        # агентам (решение владельца по данным ontology_extra_rules.yaml);
        # `skip` — не включать, но перечислить в отчёте.
        if extra and mode in ("include", "agent"):
            stages.append({"stage": str(self.cfg.get("workflow.extra_stage_label",
                                                     "доп. шаги онтологии")),
                           "steps": extra})
        out = dict(derived)
        out["pipeline"] = stages
        out["order_source"] = "template (выверенный порядок поля)"
        # Шаги, которых нет в выверенном составе поля: НЕ выбрасываем молча —
        # перечисляем в отчёте (проверяемость) и по данным решаем, включать ли их.
        out["ontology_extra_steps"] = [str(s.get("function")) for s in extra]
        out["ontology_extra_steps_mode"] = mode
        if mode == "agent":
            # Правила применимости — ДАННЫЕ (ontology/ontology_extra_rules.yaml).
            # Нет файла → решений нет, поэтому все шаги останутся выключенными
            # агентами (неизвестное != ложь), а не «включим на всякий случай».
            rules_path = self.cfg.path("workflow.ontology_extra_rules",
                                       "ontology/ontology_extra_rules.yaml")
            out["ontology_extra_rules"] = {}
            if rules_path.is_file():
                try:
                    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
                    out["ontology_extra_rules"] = {
                        str(k): dict(v or {}) for k, v in (rules.get("steps") or {}).items()}
                except Exception as exc:                # noqa: BLE001 — данные опциональны
                    out["ontology_extra_rules_error"] = str(exc)
        return out

    def graph_from_ontology(self, field: str, template: dict | None = None) -> dict:
        """Собрать граф поля из онтологии + данных (без заранее готового YAML).

        Перенесено из проверенной интеграции v7 (core/graph_generator.build_draft +
        core/project_generator.derive_pipeline/merge_with_template). Все имена и пути —
        из данных: входные файлы распознаёт detect_inputs, состав шагов — онтология.
        Ошибка/пустой результат → пустой граф (неизвестное != ложь), вызывающий код
        откатывается на YAML.
        """
        template = template or {}
        try:
            from core.graph_generator import build_draft
            from core.project_generator import (derive_pipeline, merge_with_template,
                                                template_functions)
        except ImportError:                             # pragma: no cover — модуль данных
            return {}
        ds = template.get("dataset_root")
        if ds:
            data_root = self.cfg.resolve(ds)
        else:
            base = self.cfg.get("project.data_root")
            data_root = self.cfg.resolve(base) if base else \
                self.cfg.path("project.data_dir", "data") / field
            if isinstance(data_root, Path) and (data_root / "Source").is_dir():
                data_root = data_root / "Source"
        try:
            draft = build_draft(field, data_root, template)
            # ПОРЯДОК ШАГОВ берём из шаблона поля (проверенный), а СОСТАВ — из
            # онтологии: иначе шаги идут в порядке каталога и, например, экспорт
            # карты выполняется РАНЬШЕ её создания (живой прогон: item 1 «Export
            # 2D-Map … cannot find object "2D-Map <имя>"»).
            # ВАЖНО (F-26, открыто): `functions=` у derive_pipeline НЕ задаёт порядок
            # исполнения — попытка передать туда порядок шаблона дала 29 шагов и
            # сохранила неверный порядок (экспорт карты раньше создания). Пока
            # используется проверенный вызов без `functions`; согласование порядка
            # «каталог онтологии → стадии моделирования» — отдельная задача данных.
            derived = derive_pipeline(self.ontology,
                                      rules_dir=self.cfg.path("workflow.rules_dir",
                                                              "domain/ontology_rules"),
                                      templates_dir=self.cfg.path("workflow.templates_dir"))
            draft.graph["pipeline"] = merge_with_template(derived, draft.graph)
            # F-26: порядок и стадирование — из шаблона поля (состав — из онтологии).
            draft.graph = self._reconcile_order(draft.graph, template)
            # Раунд 118: требования к объектам из онтологии → пропуск шагов без привязок.
            draft.graph = self._attach_object_requirements(draft.graph)
            # ГЕНЕРАТОР ОБЪЕКТНОЙ МОДЕЛИ: реализован (`_apply_object_model`), но ВЫКЛЮЧЕН.
            # Проверка round 169 показала: заполнение привязок у ВСЕХ шагов без `objects`
            # задевает и рабочее поле (16 предупреждений, 3 красных файла тестов) — у части
            # шагов аргументы имеют законные значения по умолчанию (тот же урок, что в
            # раундах 148 и 150). Включать нужно адресно: только те аргументы, которые
            # контроль `objects.bindings_resolved` признал незаполненными (6 позиций),
            # и с обязательной проверкой приёмки Герасимовского. До этого — только отчёт.
            draft.graph = self._apply_object_model(draft.graph)
            # СОСТАВ: выгрузка без разрешённого объекта (round 189). Правила — в онтологии
            # (`wiring.composition`). Реализовано консервативно: экспортный шаг, у которого
            # объект НЕ привязан, помечается к пропуску штатным механизмом (`requires_object`
            # + on_missing: skip) — воркфлоу tNavigator не станет экспортировать то, чего нет
            # (проверено: у ТЕСТ2 это давало падение на item 1). Шаги с привязками (состав
            # поля) не трогаются — приёмка Герасимовского не зависит от этой правки.
            draft.graph = self._apply_composition_rules(draft.graph)
            # F-27: явные данные поля СИЛЬНЕЕ вывода онтологии. Вывод добавляет свои
            # ключи (например, `markers.candidates`, `markers_candidates`), и они
            # подменяли проверенные маркеры поля — из-за этого падало покрытие
            # отбивок в структурном отчёте (yaml 69/0 против ontology 69/1).
            for _k, _v in template.items():
                if _k in ("pipeline",):
                    continue
                draft.graph[_k] = _v
            draft.graph.setdefault("field", field)
            draft.graph["pipeline_source"] = "ontology"
            return draft.graph
        except Exception as exc:                        # noqa: BLE001 — откат на YAML
            self._graph_error = str(exc)
            return {}

    # -- C5/C6/C7/C8 -------------------------------------------------------
    def function_rules(self):
        return FunctionRuleReader(self.cfg.path("workflow.rules_dir", "domain/ontology_rules"))

    def assembler(self, field: str | None = None,
                  stage_dir: Path | None = None) -> WorkflowAssembler:
        proj = self.project_graph(field)
        # ВЫВЕДЕННЫЙ СОСТАВ → В СБОРКУ ВОРКФЛОУ (round 197): у поля без проектного
        # пайплайна ассемблер шёл по группам онтологии (_ontology_genes), поэтому весь
        # выверенный аппарат (роли → привязки → генератор объектов → правила состава и
        # порядка) не влиял на реальный воркфлоу. Передаём выведенный пайплайн как
        # проектный — тогда работает _pipeline_genes. Поля с графом не затрагиваются.
        if not (proj or {}).get("pipeline"):
            try:
                derived = self.graph_from_ontology(field)
                pl = list((derived or {}).get("pipeline") or [])
                if pl:
                    proj = {**(proj or {}), "pipeline": pl}
            except Exception:                       # noqa: BLE001 — не ломает прогон
                pass
        ds = proj.get("dataset_root")
        data_root = self.cfg.resolve(ds) if ds else None
        return WorkflowAssembler(self.cfg.path("workflow.ontology_rdf"),
                                 project=proj, data_root=data_root,
                                 stage_dir=stage_dir)

    def workflow_builder(self) -> WorkflowBuilder:
        return WorkflowBuilder(
            wrapper=self.cfg.path("workflow.wrapper"),
            templates_dir=self.cfg.path("workflow.templates_dir"),
            render_name=str(self.cfg.get("workflow.render_name", "Structure_modeling")))

    def tnav(self) -> TnavClient:
        return TnavClient(self.cfg)

    def metacritic(self) -> MetaCritic:
        return MetaCritic(self.ontology.qa_rules(formalized_only=False),
                          self.ontology.parameters())

    # -- планирование -------------------------------------------------------
    def plan(self, field: str | None = None) -> dict:
        nodes = self.assembler(field).node_genes()
        stages = self.ontology.stages()
        return {
            "field": field or self.cfg.get("project.default_field"),
            "ontology": self.ontology.stats(),
            "stages": [{"id": s.id, "label": s.label, "order": s.order} for s in stages[:20]],
            "nodes": [{"group": n.group, "method": n.method,
                       "functions": [f.function for f in n.functions]} for n in nodes],
            "nodes_total": len(nodes),
            "functions_total": sum(len(n.functions) for n in nodes),
        }

    # -- прогон -------------------------------------------------------------
    @staticmethod
    def _step_object(fg, rule) -> str:
        for obj in (rule.creates if rule else ()):
            if obj.obj_name:
                return obj.obj_name
        for obj in (fg.objects or {}).values():
            if getattr(obj, "obj_name", ""):
                return obj.obj_name
        return ""

    def _boundary_object_name(self, graph: dict | None = None) -> str:
        """Имя объекта границы модели — ИЗ ДАННЫХ поля (роли — из онтологии).

        Роли-кандидаты и их порядок — ДАННЫЕ `ontology/object_binding_rules.yaml`
        (`boundary_name_roles`); имя берётся из объектов шагов графа. Ничего не
        найдено → пустая строка: контур не пишется (правило 6), а не угадывается.
        """
        rules = self._object_binding_rules()
        roles = [str(role) for role in (rules.get("boundary_name_roles") or [])]
        if not roles:
            return ""
        data = graph if graph is not None else self.project_graph()
        for stage in (data.get("pipeline") or []):
            if not isinstance(stage, dict):
                continue
            for step in (stage.get("steps") or []):
                objects = (step or {}).get("objects")
                if not isinstance(objects, dict):
                    continue
                for role in roles:
                    obj = objects.get(role)
                    if isinstance(obj, dict) and str(obj.get("obj_name") or "").strip():
                        return str(obj["obj_name"]).strip()
        return ""

    def _object_binding_rules(self) -> dict:
        """Правила привязки объектов — ДАННЫЕ онтологии (иначе пусто, правило 6)."""
        path = (Path(__file__).resolve().parent.parent / "ontology"
                / "object_binding_rules.yaml")
        if not path.is_file():
            return {}
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:                               # noqa: BLE001
            return {}
        return data if isinstance(data, dict) else {}

    def _stage_data(self, run_dir: Path, field: str) -> dict:
        """Разложить данные месторождения рядом с проектом тНава + подготовить траектории.

        тНав разрешает относительные пути к файлам данных поля (таблицы отбивок,
        каротаж, подготовленные таблицы траекторий) ОТ ПАПКИ ПРОЕКТА (`.snp`),
        поэтому `dataset_root` копируется в `run_dir`.
        Затем из `inputs.wellhead` + `inputs.inclinometry` готовятся таблицы
        `Wells/<well>.txt` (`MD X Y Z`) — они создают объекты `Wells`/`Trajectories`.
        """
        proj = self.project_graph(field)
        ds = proj.get("dataset_root")
        root = self.cfg.resolve(ds) if ds else None
        info: dict = {"root": str(root) if root else "", "copied": 0, "trajectories": []}
        if root is None or not Path(root).exists():
            return info
        for item in sorted(Path(root).iterdir()):
            dst = run_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
            info["copied"] += 1
        inputs = proj.get("inputs") or {}
        wh, incl = inputs.get("wellhead"), inputs.get("inclinometry")
        if wh and incl:
            # ФОРМАТО-ОСОЗНАННАЯ ПОДГОТОВКА (round 215): у второго объекта инклинометрия —
            # это файлы Petrel .dev, которых проектная функция не читает (давала 0
            # траекторий → проверка data.trajectories «failed»). Для .dev используем
            # проверенный адаптер; иначе — прежний путь.
            incl_path = run_dir / str(incl)
            # роль может вести и к КАТАЛОГУ (.dev-набор), и к ОДНОМУ файлу — тогда берём
            # весь набор .dev из его каталога (иначе подготавливалась 1 траектория из 67).
            if incl_path.is_dir():
                dev_files = sorted(incl_path.rglob("*.dev"))
            elif incl_path.suffix.lower() == ".dev":
                dev_files = sorted(incl_path.parent.rglob("*.dev")) or [incl_path]
            else:
                dev_files = []
            if dev_files:
                import importlib.util as _ilu
                _tool = (Path(__file__).resolve().parent.parent
                         / "tools" / "prepare_trajectories.py")
                _spec = _ilu.spec_from_file_location("_ptr_stage", _tool)
                _mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)      # type: ignore[union-attr]
                _rows, _ok, _bad = [], [], []
                for _f in dev_files:
                    _got = _mod.parse_deviation(_f)
                    if _got:
                        _rows += _got
                        _ok.append(_f.name)
                    else:
                        _bad.append(_f.name)
                if _rows:
                    _out = run_dir / "Wells" / "trajectories.txt"
                    _out.parent.mkdir(parents=True, exist_ok=True)
                    _out.write_text(_mod.to_flat_table(_rows), encoding="utf-8")
                info["trajectories"] = _ok
                info["trajectories_skipped"] = _bad
            else:
                res = prepare_trajectories(run_dir / str(wh), run_dir / str(incl),
                                           run_dir / "Wells")
                info["trajectories"] = res.get("written") or []
                info["trajectories_skipped"] = res.get("skipped") or []
        surface = inputs.get("surface") or inputs.get("surface_std")
        if surface:
            # Имя объекта границы модели — ИЗ ДАННЫХ поля (роли шагов — из онтологии
            # `object_binding_rules.boundary_name_roles`), не литерал кода (правило 1).
            b = prepare_boundary(run_dir / str(surface), run_dir / "Polygons",
                                 name=self._boundary_object_name())
            info["boundary"] = str(b) if b else ""
        # Отбивки: имена скважин приводим к ИМЕНАМ ПРОЕКТА (регистр!), иначе тНав
        # теряет маркеры («Well ... is not present in the project») и IDW-горизонты пустеют.
        welltop = inputs.get("welltop")
        if welltop:
            wells_dir = run_dir / "Wells"
            names = {p.stem for p in wells_dir.glob("*.txt")} if wells_dir.is_dir() else set()
            info["markers"] = normalize_marker_wells(run_dir / str(welltop), names)
        return info

    def run(self, field: str | None = None, *, run_dir: Path | None = None,
            execute: bool = False, on_event=None, ensemble_size: int = 0,
            on_log=None, decisions=None, run_id: str = "",
            on_phase=None, caller: str = "unknown") -> dict:
        field = field or self.cfg.get("project.default_field")
        if run_dir:
            run_dir = Path(run_dir)
        else:
            # task-18/A: dry-run пишет в СВОЙ каталог (суффикс — ДАННЫЕ `runs.dry_suffix`),
            # иначе общий `runs/run_<поле>` смешивал артефакты dry и execute (отчёт одного
            # прогона + steps/gates другого), а dry-run подхватывал чужой проект модели.
            base = self.cfg.path("runs.root", "runs") / f"run_{field}"
            suffix = "" if execute else str(
                self.cfg.get("runs.dry_suffix", _DEFAULT_DRY_SUFFIX) or "")
            run_dir = Path(f"{base}{suffix}")
        run_dir.mkdir(parents=True, exist_ok=True)
        # Ключ прогона: один и тот же для каталога модели, веток ансамбля и манифеста
        # (веб передаёт свой `run_id`, CLI получает имя каталога + метку времени).
        run_key = str(run_id or "").strip() or (
            f"{run_dir.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        def phase(name: str, detail: str = "", **extra) -> None:
            """Фаза прогона для индикации прогресса (не критична — ошибки глотаются)."""
            if callable(on_phase):
                try:
                    on_phase(name, detail, extra)
                except Exception:              # noqa: BLE001
                    pass

        phase("plan", f"поле={field}, execute={execute}")
        if callable(on_log):
            on_log(f"подготовка данных: {run_dir}")
        staging = self._stage_data(run_dir, field)
        phase("data", f"данных: {staging['copied']} объектов, "
                      f"траекторий {len(staging.get('trajectories') or [])}")
        if callable(on_log):
            on_log(f"данные разложены: {staging['copied']} объектов, "
                   f"траекторий {len(staging.get('trajectories') or [])}")

        rules = self.function_rules()
        rule_map = {name: rules.read(name) for name in rules.all_names()}
        rule_map = {k: v for k, v in rule_map.items() if v is not None}

        nodes = self.assembler(field, stage_dir=run_dir).node_genes()
        builder = self.workflow_builder()
        wf_name = str(self.cfg.get("workflow.render_name", "Structure_modeling"))
        workflow_path = run_dir / f"{wf_name}.py"

        # B: сборка воркфлоу. staged — агенты+гейты (execution.stage_mode=staged);
        # иначе — прежний монолитный контур (остаётся рабочим fallback-ом).
        staged = None
        if str(self.cfg.get("execution.stage_mode", "monolithic") or "").lower() == "staged":
            from agents.runner import StageRunner
            phase("render", "этапы: агенты и гейты")
            # data.source_untouched: снимок каталога данных поля ДО прогона, чтобы
            # доказать, что прототип не пишет в данные заказчика (F-28: прогон затирал
            # файл отбивок «на месте» и сжимал его до 2 байт).
            data_before = self._dataset_manifest(field)
            # ПОДГОТОВКА ТАБЛИЦЫ ОТБИВОК (round 182): если формат поля не плоский, импорт
            # маркеров не создаст объектов — адаптер пишет плоскую таблицу `Well Marker MD`
            # в КАТАЛОГ ПРОГОНА (данные поля не трогаются). У поля с плоской таблицей шаг
            # не выполняется вовсе (данные решают).
            marker_table = self._prepare_marker_table(field, run_dir)
            trajectories = self._prepare_trajectories(field, run_dir)
            staged = StageRunner(self, decisions=decisions, run_id=run_id).run_staged(
                field, run_dir, execute=execute, on_event=on_event,
                on_log=on_log, staging=staging, on_phase=on_phase)
            data_integrity = self._dataset_integrity(data_before, self._dataset_manifest(field))
            export_paths = self._export_paths_check(run_dir)
            data_checks = self._data_checks(field, run_dir)
            if staged is not None:
                staged["data_integrity"] = data_integrity
                staged["export_paths"] = export_paths
                staged["data_checks"] = data_checks
            if data_integrity.get("verdict") == "failed":
                log_line = ("данные поля ИЗМЕНЕНЫ прогоном: "
                            + ", ".join(str(x) for x in (data_integrity.get("changed") or [])[:5]))
                if callable(on_log):
                    on_log(log_line)
            phase("render", "этапы отрендерены")
        pipe = Pipeline(on_event=on_event)
        blocks: list[str] = []
        index = 1
        if staged and staged.get("mode") == "staged":
            workflow_path.write_text(staged["workflow_text"], encoding="utf-8")
        else:
            staged = None
            for node in nodes:
                for fg in node.functions:
                    rule = rule_map.get(fg.function)
                    obj = self._step_object(fg, rule)
                    ev = pipe.add(stage=node.stage or node.group,
                                  stage_label=node.stage or node.group,
                                  operation=node.group, function=fg.function, object=obj,
                                  status=RUNNING)
                    if rule is None:
                        pipe.update(ev, PENDING_TEMPLATE, "нет шаблона функции в наборе")
                        continue
                    try:
                        block, index = builder.render_block(rule, fg, index)
                        blocks.append(block)
                        pipe.update(ev, DONE, f"{len(block.splitlines())} строк кода")
                    except Exception as exc:              # noqa: BLE001
                        pipe.update(ev, ERROR, str(exc))
            workflow_path.write_text(builder.assemble(blocks), encoding="utf-8")
            pipe.save(run_dir / "steps.json")

        (run_dir / "plan.json").write_text(
            json.dumps(self.plan(field), ensure_ascii=False, indent=2), encoding="utf-8")

        # прогон: dry-run по умолчанию; иначе — сборка моделей через Python API
        client = self.tnav()
        if callable(on_log):
            client.set_log(on_log)
        base_snp = run_dir / f"{field}.snp"
        if execute:
            client.cfg.set("tnavigator.dry_run", False)
            client.dry_run = False
        if execute and not staged:
            # ЧИСТЫЙ проект на каждый прогон — ТОЛЬКО когда проект создаёт этот же
            # код ниже (не-staged контур). В переиспользуемом `.snp` остаются объекты
            # прошлого прогона (в первую очередь сетка), и
            # `grid_3d_create_by_horizons (mesh=find_object(name="<сетка>"))`
            # натыкается на старую сетку -> «The resulting grid has no elements!».
            # Удаляем проект и его рабочий каталог `.snf`; импорт выполнится заново.
            #
            # F-30: в staged-контуре проект УЖЕ построен и сохранён StageRunner-ом
            # именно по этим путям (см. `agents/runner.py`: base_snp = run_dir/<поле>.snp).
            # Безусловная очистка при execute УДАЛЯЛА готовую модель с диска — модель
            # существовала только в памяти сессии тНава, а в каталоге прогона её не было
            # («не вижу, чтобы модели сохранялись»). Ветки ансамбля (models/S00N) этот
            # блок не задевал — они создаются позже, поэтому и оставались на диске.
            for stale in (base_snp, base_snp.with_suffix(".snf")):
                try:
                    if stale.is_dir():
                        shutil.rmtree(stale, ignore_errors=True)
                    elif stale.exists():
                        stale.unlink()
                except OSError:
                    pass
        if execute and callable(on_log):
            # Свидетельство сохранения: проект базового прогона ДОЛЖЕН быть на диске
            snf = base_snp.with_suffix(".snf")
            snf_bytes = (sum(p.stat().st_size for p in snf.rglob("*") if p.is_file())
                         if snf.is_dir() else 0)
            on_log(f"проект базового прогона: {base_snp} "
                   f"({'есть' if base_snp.is_file() else 'НЕТ'}, "
                   f"{base_snp.stat().st_size if base_snp.is_file() else 0} Б) + "
                   f"{snf.name} ({snf_bytes} Б)")
        if staged:
            # staged-прогон уже выполнен StageRunner-ом (этап за этапом, один проект)
            run_result = TnavRunResult(ok=bool(staged.get("tnav_ok", True)), kind="staged",
                                       target=str(run_dir),
                                       error=str(staged.get("tnav_error") or ""))
        else:
            if callable(on_log):
                on_log("этап тНава: сборка базовой модели")
            try:
                if not client.dry_run:
                    client.open(project_path=base_snp, create=True)
                run_result = client.run_workflow(workflow_path, save=True)
                if not client.dry_run:
                    client.save_project()
            except Exception as exc:              # noqa: BLE001 — не роняем прогон целиком
                run_result = TnavRunResult(ok=False, kind="workflow",
                                           target=str(workflow_path), error=str(exc))
            finally:
                client.close()

        # QA/QC (artifact-значения; физические свойства появятся при реальном прогоне)
        wf_lines = len(workflow_path.read_text(encoding="utf-8").splitlines())
        if staged:
            artifacts = {"workflow": wf_name, "workflow_lines": wf_lines,
                         "nodes": len(nodes), "functions": sum(len(n.functions) for n in nodes),
                         "objects": len(staged.get("objects") or []),
                         "steps_done": (staged.get("steps") or {}).get("summary", {}).get("done", 0)}
        else:
            artifacts = {"workflow": wf_name, "workflow_lines": wf_lines,
                         "nodes": len(nodes), "functions": sum(len(n.functions) for n in nodes),
                         "objects": len({s.object for s in pipe.steps if s.object}),
                         "steps_done": pipe.summary()["done"]}
        critic = self.metacritic().evaluate(artifacts)
        phase("qa", f"вердикт QA/QC: {critic.verdict}")

        # C: ансамбль — ветки в пер-прогонной зоне (task-18/A), метрика запасов, отбор
        phase("ensemble", f"ветвей: {ensemble_size or 'из проекта'}")
        ensemble = self._build_ensemble(field, nodes, rule_map, builder, wf_name,
                                        execute, ensemble_size, on_log, on_phase=on_phase,
                                        run_key=run_key,
                                        available=(staged or {}).get("available_objects") or [])

        # F-29/task-17: МОДЕЛЬ ДОЛЖНА ОСТАВАТЬСЯ НА ДИСКЕ. Проект `<поле>.snp` и
        # рабочий каталог `<поле>.snf` создаются внутри каталога прогона; если прогон
        # запущен с ВРЕМЕННЫМ `run_dir`, они исчезают вместе с ним («не вижу, чтобы
        # модели сохранялись»). Копируем модель в предсказуемое место (`models/<run_id>`
        # либо `project.model_dir` из данных) СРАЗУ ЗДЕСЬ — до возврата управления
        # вызывающей стороне, которая может удалить временный каталог, — и пишем манифест.
        tnav_version = ""
        if execute:
            try:
                tnav_version = str((client.preflight() or {}).get("version") or "")
            except Exception:                      # noqa: BLE001 — версия не критична
                tnav_version = ""
        model_artifacts = persist_model(
            self.cfg, run_dir, field, run_id=str(run_id or ""), run_key=run_key,
            execute=bool(execute), caller=str(caller or "unknown"),
            tnav_version=tnav_version,
            tnav_executable=str(self.cfg.get("tnavigator.executable", "") or ""),
            branches=[dict(b) for b in (ensemble.get("branches") or [])],
            extra={"workflow": wf_name,
                   "staged": bool(staged),
                   "steps_done": (staged.get("steps") or {}).get("summary", {}).get("done")
                                 if staged else pipe.summary()["done"]})
        if callable(on_log):
            on_log(f"модель: {model_artifacts.get('verdict')} — "
                   f"{model_artifacts.get('dir') or 'не сохранено'} "
                   f"({model_artifacts.get('files', 0)} файл(ов), "
                   f"{model_artifacts.get('bytes', 0)} Б)")
            if model_artifacts.get("warning"):
                on_log(f"ВНИМАНИЕ: {model_artifacts['warning']}")

        project = {
            "field": field, "name": f"GM_{field}",
            "run_dir": str(run_dir), "workflow": str(workflow_path),
            "snp": str(base_snp), "models_dir": ensemble["models_dir"],
            "variants_total": len(ensemble["branches"]),
            "ensemble": ensemble,
            "model_artifacts": model_artifacts,
            "grid": "corner-point (grid_3d_create_by_horizons)",
            "open_in_tnav": "проект .snp открывается в тНаве (tNavigator.exe)",
        }
        (run_dir / "project.json").write_text(
            json.dumps(project, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        if staged:
            steps_summary = (staged.get("steps") or {}).get("summary", {})
            objects_sorted = sorted(staged.get("objects") or [])
        else:
            steps_summary = pipe.to_dict()["summary"]
            objects_sorted = sorted({s.object for s in pipe.steps if s.object})
        report = {
            "field": field, "run_dir": str(run_dir), "workflow": str(workflow_path),
            "snp": str(base_snp),
            # task-18/5: атрибуция прогона — по снапшоту видно КТО его запускал.
            "caller": str(caller or "unknown"),
            "execute": bool(execute),
            "run_key": run_key,
            "models_dir": str(self.cfg.path("project.models_dir", "models")),
            "staging": staging,
            "render_warnings": sorted(set(builder.warnings)),
            "steps": steps_summary,
            "objects": objects_sorted,
            "project": project,
            # task-17: где лежит сохранённая модель + манифест (хеши/размеры/версия).
            "model_artifacts": model_artifacts,
            "tnav": run_result.to_dict(),
            "critic": critic.to_dict(),
            "agents": (staged or {}).get("agents"),
            "structural": (staged or {}).get("structural"),
            "grid_policy": (staged or {}).get("grid_policy"),
            "facies_policy": (staged or {}).get("facies_policy"),
            "petro_policy": (staged or {}).get("petro_policy"),
            # QA/QC верхнего уровня: сводку собирает агентный слой (agents/checks/report.py)
            # в staged-прогоне — здесь только переносим её в отчёт (слоистость core → agents
            # не нарушается). Нет staged-прогона → честное «неизвестно» с причиной.
            # F-21: значения модели сняты с открытого проекта внутри staged-контура
            # (даже при деградации отдельной стадии) — отдаём их в отчёт верхнего уровня.
            "model": (staged or {}).get("model") or {},
            "grid_geometry": ((staged or {}).get("model") or {}).get("grid_geometry"),
            # data.source_untouched: неприкосновенность каталога данных поля (F-28).
            "data_integrity": (staged or {}).get("data_integrity")
                              or {"verdict": "unverified",
                                  "reason": "контур стадий не запускался"},
            # data.export_paths_within_run: выгрузки не должны покидать каталог прогона.
            "export_paths": (staged or {}).get("export_paths")
                            or {"verdict": "unverified",
                                "reason": "контур стадий не запускался"},
            "marker_table": marker_table,
            # свидетельство для проверки data.trajectories (G-DATA)
            "trajectories": trajectories,
            # Контроли данных: inputs_recognized / no_placeholders / markers_resolved /
            # format_adapter_matched (правила — в ontology/input_recognition_rules.yaml).
            "data_checks": (staged or {}).get("data_checks") or {},
            "qaqc": ((staged or {}).get("qaqc") or {
                "units": "checks", "total": None, "passed": None, "failed": None,
                "not_applicable": None, "unknown": None, "by_block": {},
                "kq": None, "kc": None, "fitness": None, "physical": None,
                "failed_checks": [],
                "reason": ("staged-контур не выполнялся: QA/QC-сводка не собрана "
                           "(неизвестное ≠ ложь)")}),
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        (run_dir / "report.json").write_text(payload, encoding="utf-8")
        # F-17: артефакт РЕАЛЬНОГО прогона не должен теряться при последующих dry-run
        # (оба пишут report.json). Имя файла-снимка — ДАННЫЕ.
        if execute:
            name = str(self.cfg.get("runs.execute_report", "report_execute.json")
                       or "report_execute.json")
            (run_dir / name).write_text(payload, encoding="utf-8")
            # F-17: каталог прогона пересоздаётся каждым `run`, поэтому артефакт
            # приёмки дублируется ВНЕ него — в архив с меткой времени (ДАННЫЕ:
            # runs.execute_archive_dir). Иначе первичные факты прогона теряются.
            try:
                root = self.cfg.path("runs.execute_archive_dir", "runs/artifacts")
                dest = root / f"execute_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                dest.mkdir(parents=True, exist_ok=True)
                (dest / name).write_text(payload, encoding="utf-8")
            except OSError:
                pass
        return report

    # -- D: проектный вывод + вариации --------------------------------------
    def variations(self, field: str | None = None) -> list[dict]:
        return self.project_graph(field).get("variations") or []

    # -- B: кэш ветки по ключу вариации ------------------------------------
    def _branch_cache_key(self, cache_root: Path, vid: str, vparams: dict) -> str:
        """Путь готового проекта ветки в кэше, ЕСЛИ он полон (`.snp` + `.snf`).

        Ключ — sha256 от идентификатора ветки и её параметров (данные): одинаковые
        вариации разных прогонов переиспользуют один проект, поэтому соседний прогон
        больше не пересобирает (и не может испортить) уже построенную модель.
        """
        import hashlib as _hashlib
        payload = json.dumps({"id": str(vid or ""), "params": vparams or {}},
                             ensure_ascii=False, sort_keys=True, default=str)
        digest = _hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        cand = cache_root / digest
        field = ""
        for item in sorted(cand.glob("*.snp")) if cand.is_dir() else []:
            if item.with_suffix(".snf").is_dir():
                field = item.stem
                break
        return str(cand) if field else ""

    def _branch_cache_put(self, cache_root: Path, vid: str, vparams: dict,
                          vdir: Path, field: str, on_log=None) -> None:
        """Положить построенный проект ветки в кэш (модель, без данных поля)."""
        import hashlib as _hashlib
        payload = json.dumps({"id": str(vid or ""), "params": vparams or {}},
                             ensure_ascii=False, sort_keys=True, default=str)
        digest = _hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        target = cache_root / digest
        if not (vdir / f"{field}.snp").is_file():
            return
        if _branch_cache_put_file(vdir, target, field) and callable(on_log):
            on_log(f"ветка {vid}: проект добавлен в кэш вариаций ({target.name})")

    def _variant_gene(self, fg, rule, params: dict):
        """Скопировать ген. `params` = {function_name: {param_code: value}} — вариация.

        Параметры вариации применяются к СООТВЕТСТВУЮЩЕЙ функции по коду параметра
        (например, {horizon_smooth: {radius: 400}}). Так ветки реально различаются.
        """
        from dataclasses import replace as _replace
        patched = dict(fg.parameters or {})
        patched.update((params or {}).get(fg.function, {}) or {})
        return _replace(fg, parameters=patched)

    def _build_ensemble(self, field, nodes, rule_map, builder, wf_name,
                        execute: bool, ensemble_size: int, on_log,
                        on_phase=None, available=None, run_key: str = "") -> dict:
        """Собрать ветки ансамбля (воркфлоу + проект + метрика из данных).

        `available` — объекты, ПОДТВЕРЖДЁННЫЕ свидетельством базового прогона
        (`grid_properties`): по ним в ветвях так же пропускаются шаги с
        `requires_object`, иначе ветвь падает на отсутствующем объекте
        («Parameter "Property" … is not valid»), получает ok=false и метрика
        не считается. Пусто → пропусков по данным НЕТ (неизвестное != ложь).

        task-18/B: проекты веток пишутся в ПЕР-ПРОГОННУЮ зону
        `models/branches/<run_key>/<vid>` (раньше — общий `models/<vid>`, который
        каждый прогон пересобирал через `rmtree`; из-за этого прогон-сосед, в том
        числе вырожденный, УНИЧТОЖАЛ модели веток предыдущей приёмки).
        Дополнительно — кэш по ключу вариации (`models/branches/_cache/<hash>`):
        полный проект переиспользуется, а не пересобирается.
        """
        available_set = {str(x) for x in (available or [])}
        invalid_variations: list[dict] = []
        pipeline_functions: set[str] = set()
        steps_by_stage: dict[str, list[dict]] = {}
        for _stage in (self.project_graph(field).get("pipeline") or []):
            if isinstance(_stage, dict):
                _steps = [s for s in (_stage.get("steps") or []) if isinstance(s, dict)]
                steps_by_stage[str(_stage.get("stage") or "")] = _steps
                pipeline_functions.update(
                    str(s.get("function")) for s in _steps if s.get("function"))
        require_key = str(self.cfg.get("workflow.requires_object_key",
                                      "requires_object") or "requires_object")
        models_dir = self.cfg.path("project.models_dir", "models")
        # Зона веток: ДАННЫЕ `project.branches_dir` (по умолчанию — подкаталог models).
        branches_root = self.cfg.path("project.branches_dir",
                                      str(models_dir / "branches"))
        run_zone = branches_root / (run_key or "unknown_run")
        cache_root = branches_root / "_cache"
        # Кэш вариаций — ОПЦИЯ (ДАННЫЕ `project.branch_cache`, по умолчанию ВЫКЛ):
        # кэш экономит пересборку ветки при повторе вариации, но стоит ещё одну копию
        # проекта (~160 МБ на уникальную вариацию), поэтому включается осознанно.
        cache_enabled = bool(self.cfg.get("project.branch_cache", False))
        variants = self.variations(field)
        if not variants:
            fallback = self.cfg.get("ensemble.default_variant") or {}
            variants = [{"id": str(fallback.get("id") or ""),
                         "label": str(fallback.get("label") or ""),
                         "parameters": {}}]
        if ensemble_size and ensemble_size > 0:
            variants = variants[:max(1, ensemble_size)]
        branches: list[dict] = []
        for i, v in enumerate(variants, start=1):
            vid = str(v.get("id", f"S{i:03d}"))
            vparams = v.get("parameters", {}) or {}
            # F-24: вариация обязана адресовать ФУНКЦИЮ, существующую в пайплайне,
            # иначе её патч ни к чему не применяется и ветвь становится копией
            # базовой (скрытый дубликат). Проверка — по данным, без списков в коде.
            unknown = sorted(set(vparams) - pipeline_functions)
            if unknown:
                invalid_variations.append({
                    "id": vid, "unknown_functions": unknown,
                    "reason": ("вариация адресует функции, которых нет в пайплайне: "
                               + ", ".join(unknown) + " — ветвь была бы копией базовой")})
                if callable(on_log):
                    on_log(f"ветка {vid}: вариация неполна — нет функций {unknown}; "
                           f"ветвь помечена как дубликат базовой")
            if callable(on_phase):
                try:
                    on_phase("ensemble", f"ветка {vid} ({i}/{len(variants)})",
                             {"stage": vid, "index": i, "total": len(variants)})
                except Exception:              # noqa: BLE001 — прогресс не критичен
                    pass
            vdir = run_zone / vid
            blocks: list[str] = []
            warnings: list[str] = []
            index = 1
            unconfirmed = {str(x) for x in
                           (self.cfg.get("workflow.unconfirmed_steps") or [])}
            for node in nodes:
                node_steps = list(steps_by_stage.get(
                    str(getattr(node, "stage", "") or "")) or [])
                pos = 0
                for fg in node.functions:
                    step = node_steps[pos] if pos < len(node_steps) else {}
                    pos += 1
                    required = str(step.get(require_key) or "")
                    if required and available_set and required not in available_set:
                        if callable(on_log):
                            on_log(f"ветка {vid}: шаг {fg.function} пропущен — нет "
                                   f"объекта-предпосылки «{required}»")
                        continue
                    rule = rule_map.get(fg.function)
                    if rule is None:
                        continue
                    # F-21: неподтверждённые пробой шаги НЕ рендерятся и в ветвях —
                    # иначе падает весь воркфлоу ветки («Facies Modelling … Parameter
                    # "Grid" is not specified»), ветвь получает ok=false, метрика не
                    # считается и свёртка ансамбля вырождается.
                    if fg.function in unconfirmed:
                        if callable(on_log):
                            on_log(f"ветка {vid}: шаг {fg.function} пропущен — "
                                   f"сигнатура не подтверждена пробой (правило 8)")
                        continue
                    vfg = self._variant_gene(fg, rule, vparams)
                    block, index = builder.render_block(rule, vfg, index)
                    blocks.append(block)
            vwf = vdir / f"{wf_name}.py"
            vsnp = vdir / f"{field}.snp"
            metric, geom, qaqc, tie, ok, err = None, None, None, None, True, ""
            if execute:
                # Каталог ветки создаётся ТОЛЬКО для реального прогона — внутри СВОЕЙ
                # зоны прогона (`models/branches/<run_key>/`), поэтому прогон-сосед
                # больше не может стереть модели веток чужой приёмки (F-32). `rmtree`
                # допустим только здесь — внутри своей зоны.
                vdir.mkdir(parents=True, exist_ok=True)
                # Каталоги выгрузок в папке проекта ветки (тНав их не создаёт,
                # а внутри элемента воркфлоу инструкции Python недопустимы) — ДАННЫЕ.
                for rel in (self.cfg.get("workflow.export_dirs") or []):
                    try:
                        (vdir / str(rel)).mkdir(parents=True, exist_ok=True)
                    except OSError as exc:
                        if callable(on_log):
                            on_log(f"ветка {vid}: каталог выгрузки «{rel}» не создан — {exc}")
                # Данные поля (Polygons/Wells/…) — рядом с проектом ветки: без них
                # падает «Import Polygons (txt format)» в воркфлоу ветки.
                self._stage_data(vdir, field)
                # Кэш по ключу вариации: полный проект (`.snp` + `.snf`) переиспользуем,
                # а не пересобираем — это и сохранность моделей, и экономия времени.
                cached = self._branch_cache_key(cache_root, vid, vparams) \
                    if cache_enabled else ""
                reused = False
                if cached:
                    _copy_branch_project(Path(cached), vdir, field)
                    if (vdir / f"{field}.snp").is_file() and \
                            (vdir / f"{field}.snf").is_dir():
                        reused = True
                        if callable(on_log):
                            on_log(f"ветка {vid}: проект взят из кэша вариации ({cached})")
                if reused:
                    c = self.tnav()
                    if callable(on_log):
                        c.set_log(on_log)
                    c.cfg.set("tnavigator.dry_run", False)
                    c.dry_run = False
                    try:
                        c.open(project_path=vsnp, create=False)
                        metric = self._read_stoiip(c)
                        geom = self._read_grid_geometry(c)
                        tie = self._read_well_tie(
                            c, vdir,
                            str(self.project_graph(field).get("reservoir_horizon", "") or ""))
                        c.close()
                        ok = True
                    except Exception as exc:          # noqa: BLE001 — деградация, не падение
                        ok, err = False, f"кэш вариации не открылся: {exc}"
                        if callable(on_log):
                            on_log(f"ветка {vid}: {err}")
                else:
                    vwf.write_text(builder.assemble(blocks), encoding="utf-8")
                    if callable(on_log):
                        on_log(f"ветка {vid}: тНав → {vsnp.name}")
                    try:
                        c = self.tnav()
                        if callable(on_log):
                            c.set_log(on_log)
                        c.cfg.set("tnavigator.dry_run", False)
                        c.dry_run = False
                        c.open(project_path=vsnp, create=True)
                        r = c.run_workflow(vwf, save=True)
                        c.save_project()
                        metric = self._read_stoiip(c)
                        geom = self._read_grid_geometry(c)
                        tie = self._read_well_tie(
                            c, vdir,
                            str(self.project_graph(field).get("reservoir_horizon", "") or ""))
                        c.close()
                        ok = bool(r.ok)
                        if not ok:                 # ошибка воркфлоу (не исключение) — запомнить текст
                            err = r.error or "workflow failed"
                    except Exception as exc:       # noqa: BLE001
                        ok, err = False, str(exc)
                        if callable(on_log):
                            on_log(f"ветка {vid}: ошибка — {exc}")
                if ok and cache_enabled:
                    self._branch_cache_put(cache_root, vid, vparams, vdir, field, on_log)
                if ok:
                    geom_warn = check_grid_geometry(geom)
                    if geom_warn:
                        warnings.append(geom_warn)
                    # QAQC: 652 оцифрованные проверки качества → kq/kc/ff + физичность
                    qaqc = qaqc_evaluate(self._qaqc_values(field, geom, tie))
                    if qaqc.physical is False:
                        warnings.append(f"QAQC: не пройдено проверок {qaqc.failed}")
                    if callable(on_log):
                        on_log(f"ветка {vid}: готово (метрика={metric})")
                        on_log(f"ветка {vid}: QAQC kq={qaqc.kq:.3f} kc={qaqc.kc:.3f} "
                               f"ff={qaqc.fitness:.3f} (применимо "
                               f"{qaqc.passed + qaqc.failed}, физично={qaqc.physical})")
                        if geom_warn:
                            on_log(f"ветка {vid}: ВНИМАНИЕ — {geom_warn}")
            branches.append({"id": vid, "label": v.get("label", ""), "parameters": vparams,
                             "path": str(vsnp), "workflow": str(vwf),
                             "metric": metric, "ok": ok, "error": err,
                             "grid_geometry": geom, "warnings": warnings,
                             "qaqc": qaqc.to_dict() if qaqc else None})
        scored = [b for b in branches if isinstance(b.get("metric"), (int, float))]
        best = max(scored, key=lambda b: b["metric"])["id"] if scored else None
        return {"root": f"GM_{field}", "models_dir": str(models_dir),
                "metric_name": str(self.cfg.get("ensemble.metric", "") or ""),
                "branches": branches, "best": best, "scored": len(scored),
                # F-24: вариации, чьи патчи не нашли цели в пайплайне (иначе
                # молчаливые дубликаты базовой ветви). Причины — в отчёте.
                "invalid_variations": invalid_variations}

    def _stoiip_code(self, out_path: str) -> str:
        """Python-сниппет чтения запасов; результат — в tmp-файл (`имя|сумма`).

        Подтверждено эталонным воркфлоу (пример ГМ; `a` = сетка):
            prop4 = a.get_property_by_name (name='<кандидат>')
            total = prop4.compute_statistics (type='sum')

        Имя сетки — ДАННЫЕ (`project.grid_name`); не задано → сниппет не строится
        (правило 6: источник запасов неизвестен, а не «первая попавшаяся сетка»).
        """
        grid_name = str(self.cfg.get("project.grid_name", "") or "")
        if not grid_name:
            return ""
        names = [str(x) for x in (self.cfg.get("project.stoiip_candidates") or [])]
        return (
            f"a = get_grid_by_name (name='{grid_name}')\n"
            f"names = {names!r}\n"
            "got = ''\n"
            "for nm in names:\n"
            "    try: p = a.get_property_by_name (name=nm)\n"
            "    except Exception: continue\n"
            "    try: v = p.compute_statistics (type='sum')\n"
            "    except Exception: v = None\n"
            "    if isinstance (v, dict):\n"
            "        v = v.get ('sum') if isinstance (v.get ('sum'), (int, float)) else None\n"
            "    if isinstance (v, (int, float)):\n"
            "        got = nm + '|' + repr (float (v))\n"
            "        break\n"
            f"open (r'{out_path}', 'w').write (got)\n"
            "'ok'\n"
        )

    def _qaqc_values(self, field: str, geom: dict | None,
                     tie: list | None = None) -> dict:
        """Значения модели для QAQC-проверок (ключи — мнемоники самих проверок).

        Собираем всё, что реально есть по данным: отбивки скважин (наблюдения),
        толщины пласта, альтитуды, размеры сетки. Проверка без своих данных
        помечается `not_applicable` и модель не штрафует.
        """
        proj = self.project_graph(field)
        ds = proj.get("dataset_root")
        root = self.cfg.resolve(ds) if ds else None
        inputs = proj.get("inputs") or {}
        values: dict = {}
        if root:
            root = Path(root)
            # Путь к отбивкам — ДАННЫЕ (`inputs.welltop`); нет ключа → нет свидетельства
            # (правило 6: неизвестное не подменяется значением по умолчанию).
            welltop_rel = inputs.get("welltop")
            tops = read_welltops(root / str(welltop_rel)) if welltop_rel else {}
            top_name, base_name = _interval_markers(proj)
            top: list[float] = []
            bot: list[float] = []
            thick: list[float] = []
            for _well, marks in tops.items():
                marks_by = {m.upper(): v for m, v in marks}
                t = next((v for k, v in marks_by.items()
                          if top_name and k.startswith(top_name.upper())), None)
                b = next((v for k, v in marks_by.items()
                          if base_name and k.startswith(base_name.upper())), None)
                if t is not None and b is not None:
                    top.append(-t)          # TVDSS (отрицательная отметка)
                    bot.append(-b)
                    thick.append(abs(b - t))
            if top:
                values.update({"H_top": top, "H_bot": bot, "THICKNESS": thick})
            if tie:
                # ЧЕСТНАЯ пара «наблюдение–модель» для проверок сходимости в точках
                # скважин: отбивка резервуара в TVDSS (KB − MD) против отметки
                # МОДЕЛИРУЕМОГО горизонта, отобранной в той же точке.
                # Раньше сюда ошибочно попадали отбивки ДВУХ РАЗНЫХ маркеров
                # (мелкий как «наблюдение» и более глубокий как «модель») — их разность
                # равна толщине пласта, и ~30 проверок падали на неверных данных.
                values["observed"] = [o for o, _m in tie]
                values["model"] = [m for _o, m in tie]
            wellhead_rel = inputs.get("wellhead")
            heads = read_wellheads(root / str(wellhead_rel)) if wellhead_rel else {}
            if heads:
                values["H_well"] = [v["kb"] for v in heads.values()]
        if geom:
            values["GRID"] = [float(geom.get("nx") or 0), float(geom.get("ny") or 0),
                              float(geom.get("nz") or 0)]
            values["H_grid"] = [float(geom.get("min_z") or 0), float(geom.get("max_z") or 0)]
        return values

    def _read_py_capture(self, client, *, code: str, tmp: Path,
                         keys: tuple[str, ...], ints: tuple[str, ...] = ()) -> dict | None:
        """Выполнить py-код в проекте тНава и прочитать результат из tmp-файла.

        `run_py_code` значения наружу НЕ возвращает (проверено на 26.1: приходит `null`),
        поэтому метрика, геометрия сетки и QC-значения читаются ЕДИНЫМ каналом
        «код → файл → разбор по ключам». Значения, которые не разобрались, опускаются.
        """
        proj = getattr(client, "_project", None)
        if proj is None:
            return None
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            proj.run_py_code(code=code)
        except Exception:                         # noqa: BLE001
            return None
        try:
            raw = tmp.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        out: dict = {}
        for key, val in zip(keys, raw.split("|")):
            val = (val or "").strip()
            if not val:
                continue
            try:
                out[key] = int(float(val)) if key in ints else float(val)
            except ValueError:
                out[key] = val
        return out or None

    def _read_stoiip(self, client) -> float | None:
        """Суммарная метрика запасов из проекта тНава (волюметрия) — файловым каналом.

        Документированный API (мануал тНава, `COMMON1.14_.../Grid_Cells_Data.py`):
            grid = get_grid_by_name (name='<grid>')
            prop = grid.get_property_by_name (name='<куб-метрика>')
            prop.compute_statistics (type='sum')
        """
        code = self._stoiip_code(_tmp_path(_METRIC_TMP))
        if not code:                                    # имя сетки не задано данными
            return None
        res = self._read_py_capture(client, code=code,
                                    tmp=_METRIC_TMP, keys=("name", "total"))
        if not res:
            return None
        total = res.get("total")
        return float(total) if isinstance(total, (int, float)) else None

    def _geometry_code(self, out_path: str) -> str:
        """Python-сниппет: записать размеры/границы сетки в tmp-файл.

        Использует документированные методы Grid3d (проверено на проекте):
            get_nx/get_ny/get_nz, get_min_x/get_max_x, ..., get_min_z/get_max_z
        Имя сетки — ДАННЫЕ (`project.grid_name`); не задано → сниппет не строится.
        """
        grid_name = str(self.cfg.get("project.grid_name", "") or "")
        if not grid_name:
            return ""
        return (
            f"g = get_grid_by_name (name='{grid_name}')\n"
            f"calls = {list(_GEOM_CALLS)!r}\n"
            "vals = []\n"
            "for m in calls:\n"
            "    try: vals.append (str (getattr (g, m) ()))\n"
            "    except Exception: vals.append ('')\n"
            f"open (r'{out_path}', 'w').write ('|'.join (vals))\n"
            "'ok'\n"
        )

    def _read_grid_geometry(self, client) -> dict | None:
        """Размеры и границы сетки из проекта тНава (единый файловый канал)."""
        code = self._geometry_code(_tmp_path(_GEOM_TMP))
        if not code:                                    # имя сетки не задано данными
            return None
        return self._read_py_capture(client, code=code, tmp=_GEOM_TMP, keys=_GEOM_KEYS,
                                     ints=("nx", "ny", "nz"))

    # -- сшивка скважин (наблюдение vs модель) ------------------------------
    def _welltie_code(self, points: list, out_path: str, horizon: str) -> str:
        """Python-сниппет: отобрать МОДЕЛИРУЕМЫЙ горизонт в точках скважин.

        Горизонт хранится как 2D-массив узлов `(nx_nodes, ny_nodes)`; план-бокс —
        из `get_rectangle()` (origin_x/origin_y, size_x/size_y). Отбор билинейный.
        Результат — значения по точкам, склеенные `|` (тот же файловый канал).
        """
        return (
            "import numpy as np\n"
            f"h = get_horizon_by_name (name='{horizon}')\n"
            "a = h.get_2d_np_array ().astype (float)\n"
            "r = h.get_rectangle ()\n"
            "n0, n1 = a.shape\n"
            "dx = r.size_x / max (1, (n0 - 1))\n"
            "dy = r.size_y / max (1, (n1 - 1))\n"
            f"pts = {list(points)!r}\n"
            "vals = []\n"
            "for _nm, x, y in pts:\n"
            "    fi = (x - r.origin_x) / dx\n"
            "    fj = (y - r.origin_y) / dy\n"
            "    i0 = int (np.floor (fi)); j0 = int (np.floor (fj))\n"
            "    if 0 <= i0 < n0 - 1 and 0 <= j0 < n1 - 1:\n"
            "        ti = fi - i0; tj = fj - j0\n"
            "        v = (a[i0, j0] * (1 - ti) * (1 - tj) + a[i0 + 1, j0] * ti * (1 - tj)\n"
            "             + a[i0, j0 + 1] * (1 - ti) * tj + a[i0 + 1, j0 + 1] * ti * tj)\n"
            "        vals.append ('%.6f' % float (v))\n"
            "    else:\n"
            "        vals.append ('')\n"
            f"open (r'{out_path}', 'w').write ('|'.join (vals))\n"
            "'ok'\n"
        )

    def _read_well_tie(self, client, run_dir: Path, horizon: str) -> list[tuple[float, float]]:
        """Честная пара «наблюдение–модель»: отбивка резервуара в TVDSS vs модель.

        Наблюдение = альтитуда устья (подготовленная таблица траекторий, первая точка)
        минус глубина отбивки по таблице отбивок поля (маркер `markers.reservoir_top`
        проекта). Модель = отметка моделируемого горизонта в точке скважины.
        """
        run_dir = Path(run_dir)
        wells_dir = run_dir / "Wells"
        graph = self.project_graph(None)
        marker = str((graph.get("markers") or {}).get("reservoir_top", "") or "")
        # Стадированный файл отбивок — ДАННЫЕ (`inputs.welltop`), без литералов пути.
        welltop_rel = (graph.get("inputs") or {}).get("welltop")
        tops = read_welltops(run_dir / str(welltop_rel)) if welltop_rel else {}
        if not wells_dir.is_dir() or not tops or not horizon:
            return []
        pts: list[tuple[str, float, float, float]] = []
        for p in sorted(wells_dir.glob("*.txt")):
            marks = tops.get(p.stem) or []
            md = next((d for m, d in marks
                       if marker and m.upper().startswith(marker.upper())), None)
            if md is None:
                continue
            rows: list[tuple[float, float, float, float]] = []
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
                parts = ln.split()
                if len(parts) >= 4:
                    try:
                        rows.append((float(parts[0]), float(parts[1]),
                                     float(parts[2]), float(parts[3])))
                    except ValueError:
                        continue
            if len(rows) < 2:
                continue
            rows.sort()
            if not (rows[0][0] <= md <= rows[-1][0]):
                continue                       # отбивка вне ствола скважины
            # Отметка отбивки = Z СТВОЛА на глубине отбивки (MD → Z с учётом наклона);
            # «KB − MD» верно только для вертикальных стволов и даёт выбросы в сотни
            # метров на наклонных/горизонтальных (проверки берут max отклонения).
            for (m0, _x0, _y0, z0), (m1, _x1, _y1, z1) in zip(rows, rows[1:]):
                if m0 <= md <= m1:
                    t = (md - m0) / (m1 - m0) if m1 > m0 else 0.0
                    pts.append((p.stem, rows[0][1], rows[0][2], z0 + (z1 - z0) * t))
                    break
        if not pts:
            return []
        code = self._welltie_code([(n, x, y) for n, x, y, _o in pts],
                                  _tmp_path(_WELLTIE_TMP), horizon)
        res = self._read_py_capture(client, code=code, tmp=_WELLTIE_TMP,
                                    keys=tuple(n for n, _x, _y, _o in pts))
        if not res:
            return []
        tie: list[tuple[float, float]] = []
        for n, _x, _y, obs in pts:
            mv = res.get(n)
            if not isinstance(mv, (int, float)):
                continue
            try:
                mv_f = float(mv)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(mv_f):
                continue               # бланк поверхности в точке скважины (nan) — нет сравнения
            tie.append((float(obs), mv_f))
        return tie

