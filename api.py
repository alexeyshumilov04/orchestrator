"""Веб-слой orchestrator-v5 на FastAPI (вариант B).

REST + WebSocket поверх `core.Coordinator`:
    GET  /health                        — живость
    GET  /api/ontology                  — сводка онтологии v4
    GET  /api/plan?field=...            — план из онтологии (без запуска)
    POST /api/chat                      — обращение → постановка → фон-прогон
    GET  /api/runs                      — список прогонов
    GET  /api/runs/{id}                 — состояние прогона
    DELETE /api/runs/{id}               — удалить прогон
    WS   /api/runs/{id}/events          — стрим статуса/лога
    GET  /                              — SPA (frontend/)

Запуск: python main.py serve --host 127.0.0.1 --port 8770
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect   # noqa: E402
from fastapi.responses import FileResponse                                    # noqa: E402
from fastapi.staticfiles import StaticFiles                                   # noqa: E402
from pydantic import BaseModel                                               # noqa: E402

from agents.decisions import DecisionBroker                                  # noqa: E402
from agents.gates import DECISION_ACTIONS, policies, update_policies         # noqa: E402
from core.config import load_config                                          # noqa: E402
from core.coordinator import Coordinator                                     # noqa: E402
import wire                                                                  # noqa: E402  (композиционный корень)
from core.llm_gateway import LLMGateway, converse, parse_ensemble_from_text   # noqa: E402
from core.runner import utc_now                                              # noqa: E402


class ChatRequest(BaseModel):
    message: str = ""
    field: str | None = None
    execute: bool = False


class RunRequest(BaseModel):
    """Детерминированный запуск прогона (кнопка «Запустить прогон», без LLM)."""

    field: str | None = None
    execute: bool = True
    ensemble_size: int = 0
    message: str = ""


class GatePolicyRequest(BaseModel):
    """Переключения из панели «Гейты и байпас» (данные → gates_override)."""

    gate_bypass: bool | None = None
    gates: dict[str, dict] = {}


class GateResolveRequest(BaseModel):
    """Решение оператора по гейту в режиме ask."""

    action: str
    author: str = ""
    comment: str = ""


@dataclass
class RunRecord:
    run_id: str
    field: str
    message: str = ""
    execute: bool = False
    status: str = "queued"          # queued | running | done | error
    created_at: str = field(default_factory=utc_now)
    log: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    reasoning: str = ""             # рассуждения LLM (reasoning_content)
    reply: str = ""                 # ответ LLM пользователю
    suggestions: list[str] = field(default_factory=list)   # предложения
    llm_source: str = ""            # "llm" | "fallback"
    ensemble_size: int = 0          # число реализаций (ансамбль)
    result: dict = field(default_factory=dict)
    error: str = ""
    pending_gate: str = ""                       # гейт, ожидающий решения (режим ask)
    gate_decisions: list[dict] = field(default_factory=list)   # журнал решений
    progress: dict = field(default_factory=dict)                # фаза/этап/проценты
    maps: list[dict] = field(default_factory=list)              # PNG-карты прогона

    def add(self, text: str) -> None:
        self.log.append(f"[{utc_now()}] {text}")
        if len(self.log) > 1000:
            del self.log[:500]

    def set_phase(self, phase: str, detail: str = "", *, stage: str = "",
                  index: int = 0, total: int = 0, **extra) -> None:
        """Фаза прогона для индикации прогресса (plan→data→render→execute→qa→ensemble)."""
        if total and index:
            percent = int(round(100 * index / total))
        elif phase in ("done", "error"):
            percent = 100
        else:
            percent = int(self.progress.get("percent", 0) or 0)
        self.progress = {"phase": phase, "detail": detail, "stage": stage,
                         "index": index, "total": total, "percent": percent,
                         "ts": utc_now(), **extra}

    def upsert_step(self, step: dict) -> None:
        i = int(step.get("index", 0)) - 1
        if 0 <= i < len(self.steps):
            self.steps[i] = step
        else:
            self.steps.append(step)
        obj = step.get("object")
        if obj and obj not in self.objects:
            self.objects.append(obj)

    def to_dict(self) -> dict:
        return asdict(self)


# -- реестр прогонов (в памяти процесса) -------------------------------------
_RUNS: dict[str, RunRecord] = {}
_LOCK = threading.Lock()
_CFG = load_config()

# -- история диалога (чат) ---------------------------------------------------
_CHAT: list[dict] = []
_PENDING: dict = {}                # ожидание уточнения (N реализаций)
_ENSEMBLE_WORDS = ("ансамбл", "реализац", "вариант", "ветк", "несколько модел", "много модел")
ENSEMBLE_QUESTION = ("Сколько реализаций собрать в ансамбль? Укажите число (1–32), "
                     "например «8 моделей».")


def _append(role: str, text: str, **extra) -> dict:
    msg = {"role": role, "text": text, "ts": utc_now(), **extra}
    _CHAT.append(msg)
    if len(_CHAT) > 300:
        del _CHAT[:150]
    _save_state()
    return msg


# -- персистентность состояния (прогоны + чат) -------------------------------
_STATE_FILE = _ROOT / "runs" / "_web_state.json"
_LAST_SAVE = [0.0]


def _save_state(force: bool = False) -> None:
    """Сохранить реестр прогонов и историю чата на диск (с троттлингом)."""
    now = time.time()
    if not force and now - _LAST_SAVE[0] < 2.0:
        return
    _LAST_SAVE[0] = now
    try:
        data = {"runs": {k: v.to_dict() for k, v in _RUNS.items()}, "chat": _CHAT}
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, default=str),
                               encoding="utf-8")
    except Exception:                         # noqa: BLE001
        pass


def _load_state() -> None:
    """Восстановить состояние из файла при старте процесса."""
    try:
        if not _STATE_FILE.is_file():
            return
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        for k, v in (data.get("runs") or {}).items():
            try:
                _RUNS[k] = RunRecord(**v)
            except Exception:                 # noqa: BLE001
                continue
        _CHAT.extend(data.get("chat") or [])
    except Exception:                         # noqa: BLE001
        pass


_load_state()

# -- решения по гейтам (режим ask: пауза + решение из интерфейса) --------------
for _rec in _RUNS.values():                 # после рестарта сервиса ожиданий нет
    _rec.pending_gate = ""


def _on_gate_request(run_id: str, gate_id: str, _context: dict) -> None:
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is not None:
            rec.pending_gate = gate_id
            rec.add(f"гейт {gate_id}: ожидается решение (best|skip|halt|waiver)")
    _save_state(force=True)


_DECISIONS = DecisionBroker(
    timeout_sec=float(_CFG.get("ui.decision_timeout_sec", 0) or 0),
    on_request=_on_gate_request)


def _coordinator() -> Coordinator:
    return Coordinator(_CFG)


def _llm() -> LLMGateway:
    return LLMGateway(_CFG)


def _context(field: str) -> str:
    """Контекст для LLM: онтология + пайплайн построения модели."""
    coord = _coordinator()
    stats = coord.ontology.stats()
    plan = coord.plan(field)
    stages = [f"  {n['group']}: {', '.join(n['functions'])}" for n in plan["nodes"]]
    return (f"Онтология ГГДМ v4: операций={stats['operations']}, этапов={stats['stages']}, "
            f"функций тНава={stats['tnav_functions']}, QA/QC={stats['qa_rules']}.\n"
            f"Поле: {field}.\n"
            f"Пайплайн 3D ГМ ({plan['nodes_total']} узлов / {plan['functions_total']} функций):\n"
            + "\n".join(stages))


def _suggest(field: str, report: dict, gateway: LLMGateway) -> list[str]:
    """Предложения по итогу: детерминированные (из отчёта) + LLM-нарратив."""
    tips: list[str] = []
    st = report.get("steps", {}) or {}
    if st.get("pending_template"):
        tips.append(f"Добавить шаблоны для {st['pending_template']} шагов (сейчас без реализации)")
    if st.get("error"):
        tips.append(f"Разобрать {st['error']} шагов с ошибкой")
    if not gateway.configured:
        return tips
    system = ("Ты — эксперт по геолого-гидродинамическому моделированию. "
              "Дай 3–5 коротких предложений по улучшению построенной 3D геологической модели. "
              "Формат вывода строго: КАЖДОЕ предложение с новой строки, начиная с «- ». "
              "Без вступлений и нумерации.")
    user = (f"Поле: {field}. "
            f"Шаги: {json.dumps(st, ensure_ascii=False)}. "
            f"Вердикт QA/QC: {(report.get('critic') or {}).get('verdict')}. "
            f"Объектов: {len(report.get('objects', []))}. "
            f"Вариаций: {(report.get('project') or {}).get('variants_total')}.")
    try:
        content, _cot = gateway._chat(system, user)
        for line in content.splitlines():
            line = line.strip().lstrip("0123456789.)-•* \t")
            if line:
                tips.append(line)
    except Exception:                         # noqa: BLE001 — предложения не критичны
        pass
    return tips[:8]



def _collect_maps(run_dir: str | None) -> list[dict]:
    """Карты прогона (PNG стадии «Экспорт карт») для панели «Карты» в интерфейсе."""
    if not run_dir:
        return []
    root = Path(str(run_dir)) / "maps"
    if not root.is_dir():
        return []
    return [{"name": p.stem, "file": p.name, "size": p.stat().st_size}
            for p in sorted(root.glob("*.png"))]


def _map_kind(name: str, kinds: dict) -> str:
    """Вид карты по данным `checks.map_kinds` (structural/facies); прочее — other."""
    for kind, names in (kinds or {}).items():
        if name in (names or []):
            return str(kind)
    return "other"


def _version_maps_dir(run_dir: str | None, result: dict, version: str) -> Path | None:
    """Каталог PNG-карт версии: база — ``runs/<id>/maps``, ветка — ``models/<vid>/maps``.

    Карты пишутся ``create_screenshot(filename="maps/<name>")`` относительно ПАПКИ
    проекта, поэтому у ветки с проектом ``models/<vid>/<field>.snp`` они лежат рядом.
    """
    if not run_dir:
        return None
    if version in ("", "base"):
        return Path(str(run_dir)) / "maps"
    branches = ((result or {}).get("ensemble") or {}).get("branches") or []
    for b in branches:
        if str((b or {}).get("id")) == str(version):
            path = (b or {}).get("path")
            if path:
                return Path(str(path)).resolve().parent / "maps"
    return None


def _collect_version_maps(run_dir: str | None, result: dict | None) -> dict:
    """Карты по ВЕРСИЯМ модели (base + ветки S001…) с разбивкой по видам.

    Виды — данные `checks.map_kinds` (``structural``/``facies``); прочие PNG — ``other``.
    Версии без карт не включаются. Список версий повторяет структуру ансамбля.
    """
    kinds = dict(_CFG.get("checks.map_kinds") or {})
    ens = (result or {}).get("ensemble") or {}
    ids = [("base", "базовая модель")] + [
        (str((b or {}).get("id") or ""), str((b or {}).get("label") or ""))
        for b in (ens.get("branches") or [])]
    versions: list[dict] = []
    for vid, label in ids:
        if not vid:
            continue
        root = _version_maps_dir(run_dir, result or {}, vid)
        if not root or not root.is_dir():
            continue
        maps = [{"name": p.stem, "file": p.name, "kind": _map_kind(p.stem, kinds)}
                for p in sorted(root.glob("*.png"))]
        if maps:
            versions.append({"id": vid, "label": label, "maps": maps})
    return {"kinds": kinds, "versions": versions}


def _submit(field: str, message: str, execute: bool, *,
            reasoning: str = "", reply: str = "", llm_source: str = "",
            ensemble_size: int = 0) -> RunRecord:
    run_id = uuid.uuid4().hex[:12]
    rec = RunRecord(run_id=run_id, field=field, message=message, execute=execute,
                    reasoning=reasoning, reply=reply, llm_source=llm_source,
                    ensemble_size=ensemble_size)
    with _LOCK:
        _RUNS[run_id] = rec

    def worker() -> None:
        rec.status = "running"
        rec.set_phase("plan", f"поле={field}, ансамбль={ensemble_size or 'из проекта'}")
        rec.add(f"старт: поле={field}, execute={execute}, ансамбль={ensemble_size or 'из проекта'}")

        def on_event(ev) -> None:
            with _LOCK:
                rec.upsert_step(ev.to_dict())
            _save_state()

        def on_log(text: str) -> None:
            rec.add(text)
            _save_state()

        def on_phase(name: str, detail: str = "", extra: dict | None = None) -> None:
            rec.set_phase(name, detail, **(extra or {}))
            _save_state()

        try:
            coord = _coordinator()
            plan = coord.plan(field)
            rec.add(f"план: узлов={plan['nodes_total']}, функций={plan['functions_total']}")
            result = coord.run(field, execute=execute, on_event=on_event,
                               ensemble_size=ensemble_size, on_log=on_log,
                               decisions=_DECISIONS, run_id=rec.run_id,
                               on_phase=on_phase)
            rec.result = result
            for obj in result.get("objects", []):
                if obj not in rec.objects:
                    rec.objects.append(obj)
            rec.maps = _collect_maps(result.get("run_dir"))
            rec.add(f"шагов: {result.get('steps', {}).get('done', '?')} выполнено")
            rec.add(f"вердикт QA/QC: {result['critic']['verdict']}")
            rec.set_phase("qa", f"вердикт QA/QC: {result['critic']['verdict']}")
            if result.get("ensemble"):
                rec.add("ансамбль: " + ", ".join(
                    f"{b.get('id')}={b.get('metric')}"
                    for b in (result["ensemble"].get("branches") or [])))
            rec.add("формирую предложения (LLM)…")
            rec.suggestions = _suggest(field, result, _llm())
            rec.set_phase("done", "прогон завершён")
            rec.status = "done"
            _save_state(force=True)
        except Exception as exc:                       # noqa: BLE001
            rec.status = "error"
            rec.error = str(exc)
            rec.add(f"ОШИБКА: {exc}")
            rec.set_phase("error", str(exc))
            _save_state(force=True)

    threading.Thread(target=worker, name=f"webrun-{run_id}", daemon=True).start()
    return rec


app = FastAPI(title="orchestrator-v5", version="0.1.0")


# -- REST --------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "orchestrator-v5"}


@app.get("/api/ontology")
def ontology() -> dict:
    return _coordinator().ontology.stats()


@app.get("/api/plan")
def plan(field: str | None = None) -> dict:
    return _coordinator().plan(field)


@app.get("/api/gates")
def gates_policy() -> dict:
    """Текущие политики гейтов (панель «Гейты и байпас»)."""
    return policies(_CFG)


@app.put("/api/gates")
def gates_policy_update(req: GatePolicyRequest) -> dict:
    """Переключение байпаса и режимов гейтов из интерфейса (config.local.yaml)."""
    return update_policies(_CFG, req.model_dump(), save=True)


@app.post("/api/runs/{run_id}/gates/{gate_id}/resolve")
def gate_resolve(run_id: str, gate_id: str, req: GateResolveRequest) -> dict:
    """Решение оператора по гейту в режиме ask (аудит: автор/комментарий/время)."""
    action = (req.action or "").strip().lower()
    if action not in DECISION_ACTIONS:
        raise HTTPException(400, f"недопустимое действие: {req.action!r}")
    if not _DECISIONS.resolve(run_id, gate_id, action,
                              author=req.author or "operator", comment=req.comment or ""):
        raise HTTPException(409, "гейт не ожидает решения")
    with _LOCK:
        rec = _RUNS.get(run_id)
        if rec is not None:
            rec.pending_gate = ""
            rec.gate_decisions.append({"gate": gate_id, "action": action,
                                       "author": req.author or "operator",
                                       "comment": req.comment or "", "ts": utc_now()})
            rec.add(f"гейт {gate_id}: решение оператора — {action}")
    _save_state(force=True)
    return {"ok": True, "run_id": run_id, "gate": gate_id, "action": action}


@app.get("/api/tnav")
def tnav_preflight() -> dict:
    return _coordinator().tnav().preflight()


@app.get("/api/chat")
def chat_history() -> list:
    return list(_CHAT)


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    message = (req.message or "").strip()
    field = req.field or str(_CFG.get("project.default_field", ""))
    _append("user", message, field=field)
    gateway = _llm()

    # продолжение уточнения: ждём число реализаций
    if _PENDING.get("await_ensemble"):
        nums = re.findall(r"\d+", message)
        if nums:
            n = max(1, min(int(nums[0]), 32))
            _PENDING.clear()
            rec = _submit(field, f"ансамбль: {n} реализаций", bool(req.execute),
                          reasoning="", reply=f"Строю ансамбль из {n} реализаций.",
                          llm_source="user", ensemble_size=n)
            _append("assistant", f"Строю ансамбль из {n} реализаций.",
                    run_id=rec.run_id, mode="build")
            return {"mode": "build", "run_id": rec.run_id, "field": field,
                    "reasoning": "", "reply": f"Строю ансамбль из {n} реализаций.",
                    "source": "user"}

    decision = converse(
        gateway, message, context=_context(field),
        default_ensemble=int(_CFG.get("execution.ensemble_size", 3) or 3),
        default_exclude=list(_CFG.get("execution.exclude_operations", []) or []),
        field=field)
    mode, reasoning, reply = decision.mode, decision.reasoning, decision.reply

    # ансамбль без указания числа → уточняющий вопрос (LLM или детерминированно)
    wants_ens = any(w in message.lower() for w in _ENSEMBLE_WORDS)
    n = parse_ensemble_from_text(message)
    if mode == "clarify" or (mode == "build" and wants_ens and not n):
        # Вопрос показываем ДЕТЕРМИНИРОВАННО: LLM мог ответить «Принято: собираю…»,
        # хотя прогон НЕ создан — иначе у пользователя ложное впечатление запуска.
        if wants_ens:
            q = ENSEMBLE_QUESTION
            _PENDING["await_ensemble"] = True
        else:
            q = reply or "Уточните запрос: какое месторождение и что строим?"
        _append("assistant", q, reasoning=reasoning, mode="clarify")
        return {"mode": "clarify", "field": field, "reasoning": reasoning, "reply": q,
                "source": decision.source}

    if mode == "build" or req.execute:
        rec = _submit(field, message, bool(req.execute), reasoning=reasoning, reply=reply,
                      llm_source=decision.source, ensemble_size=(n or 0))
        _append("assistant", reply or "Собираю модель…", reasoning=reasoning,
                run_id=rec.run_id, mode="build")
        return {"mode": "build", "run_id": rec.run_id, "field": field,
                "reasoning": reasoning, "reply": reply, "source": decision.source}
    _append("assistant", reply, reasoning=reasoning, mode="answer")
    return {"mode": "answer", "field": field, "reasoning": reasoning,
            "reply": reply, "source": decision.source}


@app.post("/api/reset")
def reset_all() -> dict:
    """Полный запуск с нуля: очистить историю сообщений и реестр прогонов."""
    with _LOCK:
        _CHAT.clear()
        _RUNS.clear()
        _PENDING.clear()
        _save_state(force=True)
    return {"ok": True, "runs": 0, "chat": 0}


@app.post("/api/runs")
def run_create(req: RunRequest) -> dict:
    """Детерминированный запуск прогона (кнопка «Запустить прогон»; без участия LLM)."""
    field = req.field or str(_CFG.get("project.default_field", "") or "")
    n = max(0, min(int(req.ensemble_size or 0), 32))
    label = req.message or f"прогон: {field}" + (f", ансамбль {n}" if n else "")
    rec = _submit(field, label, bool(req.execute), reasoning="", reply="",
                  llm_source="user", ensemble_size=n)
    note = (f"Запущен прогон {rec.run_id} "
            f"({'реальный тНав' if req.execute else 'dry-run'}"
            + (f", ансамбль {n}" if n else "") + ").")
    _append("assistant", note, run_id=rec.run_id, mode="build")
    return {"mode": "build", "run_id": rec.run_id, "field": field,
            "execute": bool(req.execute), "ensemble_size": n, "reply": note}


@app.get("/api/runs")
def runs() -> list:
    with _LOCK:
        items = [r.to_dict() for r in _RUNS.values()]
    items.sort(key=lambda r: r["created_at"], reverse=True)
    return items


@app.get("/api/runs/{run_id}")
def run_state(run_id: str) -> dict:
    with _LOCK:
        rec = _RUNS.get(run_id)
    if rec is None:
        raise HTTPException(404, "прогон не найден")
    return rec.to_dict()


@app.get("/api/runs/{run_id}/maps")
def run_maps(run_id: str) -> dict:
    """Список карт прогона (PNG из тНава/фолбэка) для панели «Карты»."""
    with _LOCK:
        rec = _RUNS.get(run_id)
    if rec is None:
        raise HTTPException(404, "прогон не найден")
    run_dir = (rec.result or {}).get("run_dir") or ""
    return {"run_id": run_id, "run_dir": run_dir, "maps": _collect_maps(run_dir)}


@app.get("/api/runs/{run_id}/maps/{file_name}")
def run_map_file(run_id: str, file_name: str) -> FileResponse:
    """Отдать PNG-карту прогона (только файлы из каталога maps, без выхода по пути)."""
    with _LOCK:
        rec = _RUNS.get(run_id)
    if rec is None:
        raise HTTPException(404, "прогон не найден")
    run_dir = (rec.result or {}).get("run_dir") or ""
    root = (Path(str(run_dir)) / "maps").resolve() if run_dir else None
    target = (root / Path(file_name).name).resolve() if root else None
    if not root or not target or root not in target.parents or not target.is_file():
        raise HTTPException(404, "карта не найдена")
    return FileResponse(str(target), media_type="image/png")


@app.get("/api/runs/{run_id}/mapset")
def run_mapset(run_id: str) -> dict:
    """Карты по ВЕРСИЯМ модели (base + ветки) с разбивкой на структурные/фаций."""
    with _LOCK:
        rec = _RUNS.get(run_id)
    if rec is None:
        raise HTTPException(404, "прогон не найден")
    run_dir = (rec.result or {}).get("run_dir") or ""
    return {"run_id": run_id, "run_dir": run_dir,
            **_collect_version_maps(run_dir, rec.result or {})}


@app.get("/api/runs/{run_id}/mapset/{version}/{file_name}")
def run_mapset_file(run_id: str, version: str, file_name: str) -> FileResponse:
    """Отдать PNG карты версии (только файлы из каталога maps, без выхода по пути)."""
    with _LOCK:
        rec = _RUNS.get(run_id)
    if rec is None:
        raise HTTPException(404, "прогон не найден")
    run_dir = (rec.result or {}).get("run_dir") or ""
    root = _version_maps_dir(run_dir, rec.result or {}, version)
    root = root.resolve() if root else None
    target = (root / Path(file_name).name).resolve() if root else None
    if not root or not target or root not in target.parents or not target.is_file():
        raise HTTPException(404, "карта не найдена")
    return FileResponse(str(target), media_type="image/png")


@app.delete("/api/runs/{run_id}")
def run_delete(run_id: str) -> dict:
    with _LOCK:
        rec = _RUNS.pop(run_id, None)
    removed = ""
    if rec and rec.result.get("run_dir"):
        import shutil
        target = Path(rec.result["run_dir"])
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed = str(target)
    return {"deleted": rec is not None, "run_id": run_id, "dir": removed}


@app.post("/api/runs/{run_id}/open")
def run_open(run_id: str, which: str = "base") -> dict:
    """Открыть проект ветки в GUI тНава (tNavigator.exe). which='base'|'<vid>'."""
    with _LOCK:
        rec = _RUNS.get(run_id)
    if rec is None:
        raise HTTPException(404, "прогон не найден")
    proj = rec.result.get("project", {}) or {}
    path = proj.get("snp", "")
    if which and which != "base":
        for b in (proj.get("ensemble", {}) or {}).get("branches", []):
            if b.get("id") == which:
                path = b.get("path", path)
                break
    if not path or not Path(path).exists():
        return {"opened": False, "reason": "проект не создан (нужен реальный прогон)", "path": path}
    ok = _coordinator().tnav().open_gui(Path(path))
    return {"opened": ok, "path": path}


# -- WebSocket: стрим статуса прогона ----------------------------------------
@app.websocket("/api/runs/{run_id}/events")
async def run_events(ws: WebSocket, run_id: str) -> None:
    await ws.accept()
    last_len = -1
    try:
        while True:
            with _LOCK:
                rec = _RUNS.get(run_id)
            if rec is None:
                await ws.send_text(json.dumps({"error": "прогон не найден"}))
                break
            payload = rec.to_dict()
            # heartbeat: кадр отправляется ВСЕГДА (раз в 0.5 с), а не только при
            # изменении лога — иначе UI «замерзает» на долгом вызове тНава.
            await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            last_len = len(rec.log)
            if rec.status in ("done", "error"):
                break
            import asyncio
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await ws.close()
        except Exception:                              # noqa: BLE001
            pass


# -- SPA (frontend/) ---------------------------------------------------------
_FRONT = _ROOT / "frontend"
if _FRONT.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONT)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(_FRONT / "index.html"))

