"""LLM-советник агента: пояснение находок гейта (гибридный контур).

LLM НЕ принимает решений и НЕ отменяет детерминированные проверки: он только
поясняет находки и предлагает следующие шаги для отчёта. Без ключа/сети советник
молчит (пустая строка) — прогон не зависит от LLM.

Системный промпт — файл-данные `agents/prompts/verify.md`.
"""
from __future__ import annotations

from pathlib import Path

from core.llm_gateway import LLMGateway

PROMPT_NAME = "verify.md"
_DEFAULT_PROMPT = ("Ты — консультант по геологическому моделированию (tNavigator). "
                   "Кратко поясни находки гейта и предложи конкретные следующие шаги.")


def _load_prompt(name: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return _DEFAULT_PROMPT


class StageAdvisor:
    """Пояснения LLM по вердиктам гейтов (опционально; fail-safe)."""

    def __init__(self, cfg, gateway: LLMGateway | None = None) -> None:
        self.cfg = cfg
        self.gateway = gateway if gateway is not None else LLMGateway(cfg)

    @property
    def enabled(self) -> bool:
        return (bool(self.cfg.get("execution.agent_llm", True))
                and bool(getattr(self.gateway, "configured", False)))

    def explain(self, *, agent_id: str, stage_key: str, gate_id: str, status: str,
                findings: list, limit: int = 1200) -> str:
        """Пояснение проваленных находок (пустая строка — LLM выключен/нет находок)."""
        if not self.enabled:
            return ""
        problems = [f for f in findings if not getattr(f, "passed", True)]
        if not problems:
            return ""
        lines = [f"- [{getattr(f, 'severity', '?')}] {getattr(f, 'id', '')}: "
                 f"{getattr(f, 'message', '')}" for f in problems[:15]]
        user = (f"Агент: {agent_id}. Этап: {stage_key}. Гейт: {gate_id}. "
                f"Вердикт (детерминированный, не обсуждается): {status}.\n"
                f"Проваленные проверки:\n" + "\n".join(lines) +
                "\nОбъясни причины и предложи 2–4 конкретных следующих шага для инженера.")
        try:
            content, _cot = self.gateway._chat(_load_prompt(PROMPT_NAME), user)
            return (content or "").strip()[:limit]
        except Exception:                 # noqa: BLE001 — советник не роняет прогон
            return ""
