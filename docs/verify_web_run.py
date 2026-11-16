"""Проверка веб-запуска прогона (task-13): ДО и ПОСЛЕ правки api.py.

Запуск (из каталога orchestrator_v8):
    python -X utf8 docs/verify_web_run.py

Что проверяется (без сети, без тНава — LLM и converse мокаются):
  1. БАЗОВАЯ версия api.py (копия `orchestrator/api.py`, sha256 3c2d737d…) на
     сообщение «построй ансамбль по Герасимовскому» БЕЗ числа реализаций задаёт
     вопрос и НЕ создаёт прогон — воспроизведение «ничего не произошло»;
  2. ИСПРАВЛЕННАЯ версия на то же сообщение СОЗДАЁТ прогон (ансамбль из данных
     проекта), а уточнение (mode=clarify) фиксируется в состоянии;
  3. RunRecord.to_dict() отдаёт `phase`; журнал попыток пишется в состояние
     (`_web_state.json` → `attempts`);
  4. намерение «построить» не теряется, когда LLM недоступна (fallback → build).

Скрипт ничего не пишет в рабочие каталоги: состояние обоих модулей
перенаправляется во временный каталог; доменные имена берутся из данных
(поле — из config.yaml `project.default_field`).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
BASELINE_SRC = ROOT.parent / "orchestrator" / "api.py"   # v5-копия = базовый api.py
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILED = 0
PASSED = 0


def check(title: str, ok: bool, detail: str = "") -> None:
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"[OK  ] {title}")
    else:
        FAILED += 1
        print(f"[FAIL] {title} — {detail}")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mock_chat_decision(mod, *, mode: str, source: str, reply: str) -> None:
    """Подменить LLM и разбор намерения: сеть не нужна."""
    mod._llm = lambda: SimpleNamespace(configured=False)
    mod._context = lambda field: "контекст (заглушка)"
    mod.converse = lambda *a, **k: SimpleNamespace(
        mode=mode, reasoning="заглушка разбора намерения", reply=reply,
        source=source, intent=SimpleNamespace(goal="ggdm"))


def _stub_submit(mod) -> None:
    """Заглушить запуск конвейера: проверяем ВЕТКУ принятия решения, не прогон.

    Сам конвейер (plan→render→qa→done) проверяется отдельно через реальный
    HTTP-запуск; здесь важно лишь: создан ли прогон, с каким ансамблем и что
    записано в журнал попыток.
    """
    def fake_submit(field, message, execute, *, reasoning="", reply="",
                    llm_source="", ensemble_size=0):
        rec = mod.RunRecord(run_id=f"stub{uuid_hex()}", field=field, message=message,
                            execute=execute, reasoning=reasoning, reply=reply,
                            llm_source=llm_source, ensemble_size=ensemble_size)
        rec.status = "running"
        rec.set_phase("plan", f"поле={field}, ансамбль={ensemble_size or 'из проекта'}")
        rec.add("заглушка запуска конвейера (ветка решения проверяется без тНава)")
        with mod._LOCK:
            mod._RUNS[rec.run_id] = rec
        return rec

    mod._submit = fake_submit


def uuid_hex() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="verify_web_run_"))
    field = "поле-из-данных"
    message = "построй ансамбль по <поле> без указания числа"   # домен только в данных

    print("=" * 78)
    print("ЧАСТЬ 1. Базовая версия api.py (ДО правки)")
    print("=" * 78)
    baseline = None
    if BASELINE_SRC.is_file():
        sha = hashlib.sha256(BASELINE_SRC.read_bytes()).hexdigest()
        print(f"источник: {BASELINE_SRC}\nsha256:   {sha}")
        dst = tmp / "api_baseline.py"
        shutil.copy2(BASELINE_SRC, dst)
        baseline = _load_module(dst, "api_baseline")
        baseline._STATE_FILE = tmp / "baseline" / "_web_state.json"
        _stub_submit(baseline)
        _mock_chat_decision(baseline, mode="build", source="llm",
                            reply="Принято: собираю ансамбль.")
        before_runs = len(baseline._RUNS)
        out = baseline.chat(baseline.ChatRequest(message=message, field=field, execute=False))
        check("baseline: намерение build + «ансамбль» без числа → вопрос (clarify)",
              out.get("mode") == "clarify", str(out.get("mode")))
        check("baseline: прогон НЕ создан (воспроизведение «ничего не произошло»)",
              len(baseline._RUNS) == before_runs, f"runs={len(baseline._RUNS)}")
        check("baseline: в записи прогона нет поля phase (UI не видит стадию)",
              "phase" not in baseline.RunRecord(run_id="r", field=field).to_dict(),
              str(sorted(baseline.RunRecord(run_id="r", field=field).to_dict())))
    else:
        check("baseline: найден базовый api.py для сравнения", False, str(BASELINE_SRC))

    print()
    print("=" * 78)
    print("ЧАСТЬ 2. Исправленная версия api.py (ПОСЛЕ правки)")
    print("=" * 78)
    import api as fixed                                            # noqa: PLC0415
    fixed._STATE_FILE = tmp / "fixed" / "_web_state.json"
    _stub_submit(fixed)
    fixed._ATTEMPTS.clear()
    fixed._RUNS.clear()
    fixed._CHAT.clear()
    fixed._PENDING.clear()

    _mock_chat_decision(fixed, mode="build", source="llm",
                        reply="Принято: собираю ансамбль.")
    runs_before = len(fixed._RUNS)
    out = fixed.chat(fixed.ChatRequest(message=message, field=field, execute=False))
    check("fixed: намерение build + «ансамбль» без числа → ПРОГОН создан",
          out.get("mode") == "build" and bool(out.get("run_id")),
          json.dumps(out, ensure_ascii=False, default=str))
    check("fixed: ровно один новый прогон",
          len(fixed._RUNS) == runs_before + 1, f"runs={len(fixed._RUNS)}")
    check("fixed: ансамбль взят из данных проекта (execution.ensemble_size)",
          "execution.ensemble_size" in (out.get("reply") or "")
          or "данных проекта" in (out.get("reply") or ""),
          str(out.get("reply")))
    attempt = (fixed._ATTEMPTS or [{}])[-1]
    check("fixed: попытка записана в состояние (mode/run_id/reason)",
          attempt.get("mode") == "build" and attempt.get("run_id") == out.get("run_id")
          and bool(attempt.get("reason")),
          json.dumps(attempt, ensure_ascii=False))

    # уточнение (LLM реально просит уточнить) — прогона нет, но запись ЕСТЬ
    fixed._PENDING.clear()
    _mock_chat_decision(fixed, mode="clarify", source="llm",
                        reply="Уточните, пожалуйста, задачу.")
    # ГЛАВНЫЙ случай жалобы пользователя: LLM сама просит уточнить число реализаций,
    # хотя число ЕСТЬ в данных проекта и поле известно → прогон обязан стартовать.
    fixed._PENDING.clear()
    _mock_chat_decision(fixed, mode="clarify", source="llm",
                        reply="Сколько реализаций собрать в ансамбль?")
    runs_before = len(fixed._RUNS)
    out_clar = fixed.chat(fixed.ChatRequest(message="построй ансамбль по <поле>",
                                            field=field, execute=False))
    clar = (fixed._ATTEMPTS or [{}])[-1]
    check("fixed: LLM просит число, но оно есть в данных проекта → прогон СОЗДАН",
          out_clar.get("mode") == "build" and len(fixed._RUNS) == runs_before + 1
          and clar.get("mode") == "build" and bool(clar.get("run_id")),
          json.dumps(out_clar, ensure_ascii=False, default=str))

    # а вот уточнение, когда данных правда нет, обязано быть записано в состоянии
    fixed._PENDING.clear()
    _mock_chat_decision(fixed, mode="clarify", source="llm",
                        reply="Уточните, пожалуйста, задачу.")
    runs_before = len(fixed._RUNS)
    out_q_clar = fixed.chat(fixed.ChatRequest(message="построй модель", field=field,
                                              execute=False))
    clar2 = (fixed._ATTEMPTS or [{}])[-1]
    check("fixed: вынужденное уточнение → прогона нет, но попытка записана (run_id=null)",
          out_q_clar.get("mode") == "clarify" and len(fixed._RUNS) == runs_before
          and clar2.get("mode") == "clarify" and clar2.get("run_id") is None
          and bool(clar2.get("reason")),
          json.dumps(clar2, ensure_ascii=False))

    # LLM недоступна: команда на построение не должна превращаться в «ответ без прогона»
    fixed._PENDING.clear()
    _mock_chat_decision(fixed, mode="answer", source="fallback",
                        reply="Не удалось получить ответ модели.")
    runs_before = len(fixed._RUNS)
    out_fb = fixed.chat(fixed.ChatRequest(message="построй геологическую модель поля",
                                          field=field, execute=False))
    check("fixed: LLM недоступна + команда «построй» → прогон создан (не «просто ответ»)",
          out_fb.get("mode") == "build" and len(fixed._RUNS) == runs_before + 1,
          json.dumps(out_fb, ensure_ascii=False, default=str))

    # вопрос при недоступной LLM остаётся ответом
    runs_before = len(fixed._RUNS)
    out_q = fixed.chat(fixed.ChatRequest(message="какие методы фаций доступны?",
                                         field=field, execute=False))
    check("fixed: LLM недоступна + вопрос → ответ без прогона",
          out_q.get("mode") == "answer" and len(fixed._RUNS) == runs_before,
          json.dumps(out_q, ensure_ascii=False, default=str))

    # phase в сериализации
    rec = fixed.RunRecord(run_id="r1", field=field)
    rec.set_phase("stage", "2/9", stage="2. Горизонты", index=2, total=9)
    d = rec.to_dict()
    check("fixed: phase попадает в to_dict() (UI видит стадию)",
          d.get("phase") == "stage" and d["progress"]["percent"] == 22, str(d.get("phase")))

    # состояние на диске: прогоны + attempts + phase
    fixed._save_state(force=True)
    state = json.loads(fixed._STATE_FILE.read_text(encoding="utf-8"))
    check("fixed: _web_state.json содержит runs/chat/attempts",
          set(state) >= {"runs", "chat", "attempts"}, str(sorted(state)))
    check("fixed: каждая попытка в состоянии имеет mode/field/run_id/причина",
          bool(state["attempts"]) and all(
              {"mode", "field", "run_id", "reason"} <= set(a) for a in state["attempts"]),
          json.dumps(state["attempts"][:2], ensure_ascii=False))
    any_phase = [r.get("phase") for r in state["runs"].values() if r.get("phase")]
    check("fixed: фаза прогона сохранена в состоянии (есть непустой phase)",
          bool(any_phase), str(any_phase))

    print()
    print(f"итог: пройдено {PASSED}, провалено {FAILED}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
