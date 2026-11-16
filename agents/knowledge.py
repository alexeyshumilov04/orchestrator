"""БАЗА ЗНАНИЙ агентов: статическая (онтология) + динамическая (опыт прогонов).

Два слоя, оба — ДАННЫЕ, код только читает и считает:

1) **Статическая БЗ** (`StaticKnowledge`) — онтология BDI v4.1 из
   `agents.bdi_dir` (`config.yaml`): таблицы решений (1796 формальных guard-ов),
   правила из литературы/архитектуры, схема убеждений. Только чтение.

2) **Динамическая БЗ** (`KnowledgeBase`) — ЖУРНАЛ ОПЫТА агентов: что агент
   решил на каком этапе, с какими параметрами и свидетельствами, чем это
   закончилось (вердикт гейта, kq/kc, попытки, деградация). Формат — JSONL
   (append-only), два адреса:
     * накопительный: `agents.kb_dir` (по умолчанию `knowledge/agents/ledger.jsonl`);
     * внутри прогона: `runs/<id>/agents/kb/<agent>.jsonl`.

   Извлечение (`recall`) — ДЕТЕРМИНИРОВАННОЕ: фильтр по агенту/этапу/набору
   функций + близость по нормированному вектору числовых параметров. LLM в
   расчёте чисел не участвует (LLM только советует, см. `agents/advisor.py`).

Статусы знания и продвижение (`candidate → repeatable → approved`) — по числу
наблюдений из данных (`agents.policy.promotion`). Влияние на план по умолчанию
оказывает только `approved`-опыт; «неизвестное != ложь»: нет опыта — нет подсказки.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CANDIDATE, REPEATABLE, APPROVED = "candidate", "repeatable", "approved"
STATUS_ORDER = (CANDIDATE, REPEATABLE, APPROVED)

# Колонки-носители в CSV онтологии BDI (идентификаторы СХЕМЫ, не значения поля).
DECISIONS_FILE = "decision_tables_v4_1.csv"
LITERATURE_FILE = "literature_and_architecture_rules.csv"
BELIEFS_FILE = "belief_schema_v4_1.csv"


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ExperienceRecord:
    """Одна запись опыта: решение агента и его исход (ДАННЫЕ)."""

    agent: str
    stage: str = ""
    gate: str = ""
    field_name: str = ""                    # имя поля (не путать с dataclasses.field)
    mode: str = ""
    verdict: str = ""
    attempts: int = 1
    degraded: bool = False
    outcome: str = ""                       # passed | degraded | failed (сводка)
    functions: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    plan_hash: str = ""
    evidence_hash: str = ""
    metrics: dict = field(default_factory=dict)
    status: str = CANDIDATE
    provenance: str = ""
    ts: str = ""

    def key(self) -> tuple:
        """Ключ опыта: агент + этап + набор функций (для подсчёта наблюдений)."""
        return (self.agent, self.stage, tuple(sorted(self.functions)))

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ExperienceRecord":
        known = {f for f in ExperienceRecord.__dataclass_fields__}      # noqa: SLF001
        return ExperienceRecord(**{k: v for k, v in (data or {}).items() if k in known})


class KnowledgeBase:
    """Журнал опыта агентов (append-only JSONL) + детерминированное извлечение."""

    def __init__(self, cfg=None, *, root: Path | str | None = None,
                 run_dir: Path | str | None = None) -> None:
        self.cfg = cfg
        self._run_dir = Path(run_dir) if run_dir else None
        if root is not None:
            self.root = Path(root)
        elif cfg is not None:
            self.root = cfg.path("agents.kb_dir", "knowledge/agents")
        else:
            self.root = Path("knowledge/agents")

    # -- адреса ------------------------------------------------------------------
    @property
    def ledger(self) -> Path:
        return self.root / "ledger.jsonl"

    def run_ledger(self, agent: str) -> Path | None:
        if self._run_dir is None:
            return None
        rel = "agents.kb_runs_dir"
        sub = (self.cfg.get(rel, "agents/kb") if self.cfg is not None else "agents/kb")
        path = self._run_dir / str(sub) / f"{agent or 'agent'}.jsonl"
        return path

    # -- запись ------------------------------------------------------------------
    def remember(self, record: ExperienceRecord) -> str:
        """Дописать запись опыта в накопительный и внутрипрогонный журналы."""
        if not record.ts:
            from agents.contracts import utc_now
            record.ts = utc_now()
        payload = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True)
        for path in (self.ledger, self.run_ledger(record.agent)):
            if path is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(payload + "\n")
        return record.ts

    # -- чтение ------------------------------------------------------------------
    def history(self, *, agent: str | None = None, stage: str | None = None,
                limit: int | None = None) -> list[dict]:
        """Весь (или отфильтрованный) журнал опыта, новые записи — последними."""
        out: list[dict] = []
        if not self.ledger.is_file():
            return out
        for line in self.ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if agent and row.get("agent") != agent:
                continue
            if stage and row.get("stage") != stage:
                continue
            out.append(row)
        out = out[-limit:] if limit else out
        return out

    # -- близость и извлечение ----------------------------------------------------
    def _tolerance(self) -> float:
        if self.cfg is None:
            return 0.25
        return float(self.cfg.get("agents.recall.numeric_tolerance", 0.25) or 0.25)

    def _distance(self, want: dict, have: dict) -> float:
        """0.0 (совпало) … 1.0 (далеко): нормированное расхождение числовых параметров.

        Нечисловые параметры сравниваются на равенство. Параметров нет с обеих
        сторон — расстояние 0.0 (сравнивать нечего, это не «ложь»).
        """
        keys = {k for k in want if _num(want[k]) is not None} | \
               {k for k in have if _num(have[k]) is not None}
        diffs: list[float] = []
        for key in sorted(keys):
            a, b = _num(want.get(key)), _num(have.get(key))
            if a is None or b is None:
                continue
            scale = max(abs(a), abs(b)) or 1.0
            diffs.append(min(1.0, abs(a - b) / scale))
        for key in sorted((set(want) | set(have)) - keys):
            diffs.append(0.0 if want.get(key) == have.get(key) else 1.0)
        return sum(diffs) / len(diffs) if diffs else 0.0

    def recall(self, *, agent: str, stage: str | None = None,
               functions: list[str] | None = None, parameters: dict | None = None,
               k: int | None = None, min_status: str | None = None,
               only_success: bool = True) -> list[dict]:
        """Похожий опыт: сортировка «успех → близость → свежесть» (детерминированно)."""
        k = int(k if k is not None else
                (self.cfg.get("agents.recall.k", 5) if self.cfg is not None else 5) or 5)
        if min_status is None and self.cfg is not None:
            min_status = str(self.cfg.get("agents.recall.min_status", "") or "")
        min_rank = STATUS_ORDER.index(min_status) if min_status in STATUS_ORDER else -1
        want_fn = set(functions or [])
        scored: list[tuple] = []
        for row in self.history(agent=agent, stage=stage):
            if min_rank >= 0 and STATUS_ORDER.index(
                    row.get("status") or CANDIDATE) < min_rank:
                continue
            if only_success and str(row.get("outcome") or "") not in ("passed", "degraded"):
                continue
            have_fn = set(row.get("functions") or [])
            overlap = len(want_fn & have_fn) / len(want_fn | have_fn) if (want_fn | have_fn) else 1.0
            dist = self._distance(parameters or {}, row.get("parameters") or {})
            score = (round(overlap, 6), round(-dist, 6), str(row.get("ts") or ""))
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [row for _score, row in scored[:max(1, k)]]

    def suggest(self, *, agent: str, stage: str | None = None,
                functions: list[str] | None = None, parameters: dict | None = None,
                k: int | None = None) -> dict:
        """Рекомендация параметров из похожего опыта: {function: {код: значение}}.

        Значение — МЕДИАНА числовых наблюдений из похожих удачных записей
        (устойчиво к единичному выбросу). Нет опыта — пустой словарь
        («неизвестное != ложь», план остаётся на данных проекта).
        """
        rows = self.recall(agent=agent, stage=stage, functions=functions,
                           parameters=parameters, k=k)
        if not rows:
            return {}
        buckets: dict[str, dict[str, list[float]]] = {}
        for row in rows:
            for fn, params in (row.get("parameters") or {}).items():
                if not isinstance(params, dict):
                    continue
                for code, value in params.items():
                    num = _num(value)
                    if num is None:
                        continue
                    buckets.setdefault(fn, {}).setdefault(code, []).append(num)
        out: dict[str, dict] = {}
        for fn, codes in buckets.items():
            out[fn] = {}
            for code, values in codes.items():
                values.sort()
                mid = len(values) // 2
                median = (values[mid] if len(values) % 2 else
                          (values[mid - 1] + values[mid]) / 2.0)
                out[fn][code] = int(median) if float(median).is_integer() else median
        return out

    # -- продвижение знания -------------------------------------------------------
    def promote(self) -> dict:
        """Пересчитать статусы опыта: candidate → repeatable → approved (данные).

        Критерий — число УДАЧНЫХ наблюдений одного и того же ключа опыта
        (агент + этап + набор функций). Возвращает переписанный журнал.
        """
        rules = {}
        if self.cfg is not None:
            rules = dict(self.cfg.get("agents.policy.promotion") or {})
        need_repeat = int(rules.get("repeatable_runs", 2) or 2)
        need_approve = int(rules.get("approved_runs", 3) or 3)

        rows = self.history()
        good: dict[tuple, int] = {}
        for row in rows:
            rec = ExperienceRecord.from_dict(row)
            if str(rec.outcome or "") in ("passed", "degraded"):
                good[rec.key()] = good.get(rec.key(), 0) + 1
        changed = 0
        for row in rows:
            rec = ExperienceRecord.from_dict(row)
            count = good.get(rec.key(), 0)
            status = (APPROVED if count >= need_approve else
                      REPEATABLE if count >= need_repeat else CANDIDATE)
            # Провальная запись остаётся кандидатом: отрицательный опыт полезен,
            # но плана по умолчанию не задаёт.
            if str(rec.outcome or "") not in ("passed", "degraded"):
                status = CANDIDATE
            if status != (row.get("status") or CANDIDATE):
                row["status"] = status
                changed += 1
        if changed:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.ledger.open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return {"records": len(rows), "changed": changed,
                "repeatable_runs": need_repeat, "approved_runs": need_approve}

    # -- сводка -------------------------------------------------------------------
    def stats(self) -> dict:
        rows = self.history()
        by_status: dict[str, int] = {}
        by_agent: dict[str, int] = {}
        for row in rows:
            by_status[row.get("status") or CANDIDATE] = \
                by_status.get(row.get("status") or CANDIDATE, 0) + 1
            by_agent[row.get("agent") or ""] = by_agent.get(row.get("agent") or "", 0) + 1
        return {"dir": str(self.root), "ledger": str(self.ledger), "records": len(rows),
                "by_status": by_status, "by_agent": by_agent}


class StaticKnowledge:
    """Статическая БЗ онтологии BDI v4.1 (только чтение CSV, кэш в памяти).

    Кроме каталога BDI читает ЛИТЕРАТУРНЫЕ данные, если они зарегистрированы
    в конфигурации (`agents.literature.*`): индекс источников, правила с ссылкой
    на источник и страницу, карту «агент → правила». Пути — ДАННЫЕ; файлов нет →
    пустой результат (неизвестное != ложь), никакой паники.
    """

    def __init__(self, bdi_dir: Path | str | None = None, cfg=None) -> None:
        self.bdi_dir = Path(bdi_dir) if bdi_dir else None
        self.cfg = cfg
        self._cache: dict[str, list[dict]] = {}

    # -- литература (данные, зарегистрированные в config.yaml) ---------------------
    def _lit_path(self, key: str) -> Path | None:
        if self.cfg is None:
            return None
        value = self.cfg.get(f"agents.literature.{key}")
        return self.cfg.resolve(value) if value else None

    def literature_index(self) -> list[dict]:
        """Инвентаризация источников литературы (путь, тип, область, темы)."""
        path = self._lit_path("index")
        return self._csv(path) if path else []

    def literature_rules_ext(self) -> list[dict]:
        """Правила, извлечённые из литературы (с ссылкой на источник и страницу)."""
        path = self._lit_path("rules_ext")
        return self._csv(path) if path else []

    def literature_rules_all(self) -> list[dict]:
        """Правила литературы: базовый набор BDI v4.1 + расширение из «Литература/»."""
        return list(self.literature_rules()) + self.literature_rules_ext()

    def agent_literature(self) -> dict:
        """Карта «агент → правила/источники», которыми он обосновывает выбор метода."""
        path = self._lit_path("agent_map")
        if path is None or not path.is_file():
            return {}
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:                               # noqa: BLE001 — данные опциональны
            return {}
        return data if isinstance(data, dict) else {}

    def _csv(self, path: Path) -> list[dict]:
        if path is None or not path.is_file():
            return []
        import csv
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [{str(k).strip(): (v or "").strip() for k, v in row.items()}
                    for row in csv.DictReader(fh)]

    @property
    def available(self) -> bool:
        return bool(self.bdi_dir) and self.bdi_dir.is_dir()

    def rows(self, name: str) -> list[dict]:
        """Строки CSV онтологии как словари (пусто, если файла нет)."""
        if name in self._cache:
            return self._cache[name]
        import csv
        path = (self.bdi_dir / name) if self.bdi_dir else None
        out: list[dict] = []
        if path is not None and path.is_file():
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                out = [{str(k).strip(): (v or "").strip() for k, v in row.items()}
                       for row in csv.DictReader(fh)]
        self._cache[name] = out
        return out

    def decisions(self) -> list[dict]:
        """Таблицы решений BDI v4.1 (правила с формальными guard-ами)."""
        return self.rows(DECISIONS_FILE)

    def literature_rules(self) -> list[dict]:
        """Правила, выведенные из литературы и архитектуры (83 записи)."""
        return self.rows(LITERATURE_FILE)

    def belief_schema(self) -> list[dict]:
        """Схема убеждений агента (типы belief-ов и их источники)."""
        return self.rows(BELIEFS_FILE)

    def rules_for(self, *, branch_id: str | None = None,
                  activity: str | None = None) -> list[dict]:
        """Правила по развилке/активности (guard-и для решения агента)."""
        out = []
        for source in (self.decisions(), self.literature_rules(),
                       self.literature_rules_ext()):
            for row in source:
                if branch_id and row.get("branch_id") != branch_id:
                    continue
                if activity and row.get("activity") != activity:
                    continue
                out.append(row)
        out.sort(key=lambda r: (r.get("branch_id", ""), _num(r.get("priority")) or 0))
        return out

    def stats(self) -> dict:
        return {"available": self.available, "dir": str(self.bdi_dir or ""),
                "decisions": len(self.decisions()),
                "literature_rules": len(self.literature_rules()),
                "literature_rules_ext": len(self.literature_rules_ext()),
                "literature_sources": len(self.literature_index()),
                "agent_literature": len(self.agent_literature()),
                "beliefs": len(self.belief_schema())}
