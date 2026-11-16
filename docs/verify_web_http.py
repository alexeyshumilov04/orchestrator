"""HTTP-проверка веб-запуска прогона (task-13), порт из аргумента.

Запуск:
    python -X utf8 docs/verify_web_http.py [--url http://127.0.0.1:8770]

Проверяет на РАБОТАЮЩЕМ сервере (сервер поднимается отдельно, `main.py serve`):
  1. POST /api/runs в режиме dry-run → прогон создан и доходит до статуса done;
  2. POST /api/chat «построй ансамбль …» без числа реализаций → СТАРТУЕТ прогон;
  3. `phase` видна в ответах /api/runs/{id} и /api/runs;
  4. каждая попытка запуска записана в runs/_web_state.json (attempts);
  5. состояние не теряет прогоны (runs/chat/attempts на диске).

Домен (имя поля) берётся из данных config.yaml (project.default_field).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILED = 0
PASSED = 0
STATE_FILE = ROOT / "runs" / "_web_state.json"


def check(title: str, ok: bool, detail: str = "") -> None:
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"[OK  ] {title}")
    else:
        FAILED += 1
        print(f"[FAIL] {title} — {detail}")


def http(url: str, path: str, payload: dict | None = None, timeout: int = 600):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_done(url: str, run_id: str, limit_sec: int = 900) -> dict:
    """Ждать завершения прогона, печатая смену фазы (индикация прогресса)."""
    deadline = time.time() + limit_sec
    last = ""
    rec: dict = {}
    while time.time() < deadline:
        rec = http(url, f"/api/runs/{run_id}")
        phase = f"{rec.get('phase')}/{rec.get('status')}"
        if phase != last:
            print(f"    фаза: {phase} · {(rec.get('progress') or {}).get('detail', '')}")
            last = phase
        if rec.get("status") in ("done", "error"):
            return rec
        time.sleep(3)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8770")
    args = ap.parse_args()
    url = args.url.rstrip("/")

    from core.config import load_config                     # noqa: PLC0415
    cfg = load_config()
    field = str(cfg.get("project.default_field", "") or "")
    print(f"URL: {url}\nполе (из данных config.yaml): {field}")

    health = http(url, "/health")
    check("сервер отвечает /health", bool(health.get("ok")), str(health))

    # 1) детерминированный dry-run через кнопку «Запустить прогон»
    print("\n1) POST /api/runs (dry-run)")
    res = http(url, "/api/runs", {"field": field, "execute": False, "ensemble_size": 0})
    run_id = res.get("run_id") or ""
    check("POST /api/runs: прогон создан (есть run_id)", bool(run_id), json.dumps(res, ensure_ascii=False))
    rec = wait_done(url, run_id) if run_id else {}
    check("dry-run дошёл до статуса done", rec.get("status") == "done",
          f"status={rec.get('status')} error={rec.get('error')}")
    check("у прогона видна фаза (phase не пустая/не null)", bool(rec.get("phase")),
          f"phase={rec.get('phase')!r}")
    check("фаза завершённого прогона = done", rec.get("phase") == "done", str(rec.get("phase")))
    steps = rec.get("steps") or []
    errs = [s for s in steps if s.get("status") == "error"]
    check("шаги прогона без ошибок", bool(steps) and not errs,
          f"steps={len(steps)}, errors={len(errs)}")

    # 2) чат: «построй ансамбль» без числа реализаций ДОЛЖЕН стартовать прогон
    print("\n2) POST /api/chat «построй ансамбль …» (число реализаций не указано)")
    msg = f"построй ансамбль по {field}"
    out = http(url, "/api/chat", {"message": msg, "field": field, "execute": False},
               timeout=400)
    print("    ответ: " + json.dumps({k: out.get(k) for k in
                                      ("mode", "run_id", "source", "reply")},
                                     ensure_ascii=False))
    check("chat: прогон СОЗДАН (режим build + run_id), а не «ничего не произошло»",
          out.get("mode") == "build" and bool(out.get("run_id")),
          json.dumps(out, ensure_ascii=False))
    chat_run = out.get("run_id") or ""
    if chat_run:
        rec2 = wait_done(url, chat_run)
        check("chat-прогон дошёл до done", rec2.get("status") == "done",
              f"status={rec2.get('status')} error={rec2.get('error')}")

    # 3) phase в списке прогонов
    print("\n3) GET /api/runs — фазы и попытки")
    runs = http(url, "/api/runs")
    check("GET /api/runs: все прогоны имеют поле phase",
          bool(runs) and all("phase" in r for r in runs),
          str([sorted(r)[:3] for r in runs[:1]]))
    atts = http(url, "/api/attempts")
    check("GET /api/attempts: попытки записаны с mode/run_id/причиной",
          bool(atts) and all({"mode", "field", "run_id", "reason"} <= set(a) for a in atts),
          json.dumps(atts[-2:], ensure_ascii=False))

    # 4) состояние на диске
    print("\n4) runs/_web_state.json")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    check("состояние содержит runs/chat/attempts",
          set(state) >= {"runs", "chat", "attempts"}, str(sorted(state)))
    made = {r for r in (run_id, chat_run) if r}
    check("прогоны этой проверки сохранены со статусом done и фазой done",
          bool(made) and all(
              (state.get("runs") or {}).get(r, {}).get("status") == "done"
              and (state.get("runs") or {}).get(r, {}).get("phase") == "done"
              for r in made),
          json.dumps({r: (state["runs"].get(r) or {}).get("status") for r in made},
                     ensure_ascii=False))
    stuck = [k for k, r in (state.get("runs") or {}).items()
             if r.get("status") == "running" and not (r.get("steps") or [])]
    check("в состоянии нет «вечно running» прогонов без прогресса (прерванные помечены)",
          not stuck, str(stuck))
    print("    runs:", json.dumps({k: {"phase": v.get("phase"), "status": v.get("status"),
                                       "steps": len(v.get("steps") or []),
                                       "ensemble_size": v.get("ensemble_size")}
                                   for k, v in (state.get("runs") or {}).items()},
                                  ensure_ascii=False))
    print("    attempts:", json.dumps(state.get("attempts") or [], ensure_ascii=False)[:800])

    print(f"\nитог: пройдено {PASSED}, провалено {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
