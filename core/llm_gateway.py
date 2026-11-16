"""LLM-шлюз (advisory). Языковая модель ПРЕДЛАГАЕТ, но не владеет фактами и вердиктом.

OpenAI-совместимый API через stdlib urllib (без внешних SDK). При недоступности
модели включается детерминированный fallback — прогон не останавливается.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import Config


class LLMUnavailable(RuntimeError):
    pass


_ENSEMBLE_IN_TEXT = re.compile(
    r"(\d{1,2})\s*(?:модел\w*|реализац\w*|вариант\w*|ветв\w*|реализ\w*)", re.IGNORECASE)


def parse_ensemble_from_text(text: str) -> int | None:
    """Сколько реализаций ЯВНО просят в тексте («сделай 8 моделей»)."""
    match = _ENSEMBLE_IN_TEXT.search(text or "")
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 32 else None


@dataclass
class Intent:
    goal: str = "ggdm"                     # "gm" | "gdm" | "ggdm"
    field_name: str | None = None
    adaptation: bool = False
    ensemble_size: int = 1
    exclude_operations: list[str] = field(default_factory=list)
    notes: str = ""
    source: str = "fallback"               # "llm" | "fallback"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"goal": self.goal, "field": self.field_name, "adaptation": self.adaptation,
                "ensemble_size": self.ensemble_size,
                "exclude_operations": list(self.exclude_operations),
                "notes": self.notes, "source": self.source}


@dataclass
class ChatDecision:
    mode: str = "answer"                   # "answer" | "build"
    reply: str = ""
    reasoning: str = ""
    intent: Intent | None = None
    source: str = "fallback"

    def to_dict(self) -> dict:
        return {"mode": self.mode, "reply": self.reply, "reasoning": self.reasoning,
                "intent": self.intent.to_dict() if self.intent else None,
                "source": self.source}


CONV_SYSTEM = (
    "Ты — консультант и планировщик оркестратора геолого-гидродинамического моделирования (ГГДМ). "
    "Отвечай СТРОГО валидным JSON без пояснений вне JSON.\n"
    "Поля JSON:\n"
    '  "mode": "build" — если пользователь просит ПОСТРОИТЬ/СОБРАТЬ модель и данных достаточно; '
    '"answer" — если это вопрос (об онтологии, данных, методе); '
    '"clarify" — если запрос на построение, но НЕ хватает числа реализаций ансамбля '
    "(тогда в reply задай один короткий уточняющий вопрос на русском);\n"
    '  "reply": ответ/вопрос пользователю на русском;\n'
    '  "reasoning": краткое рассуждение на русском;\n'
    '  "goal": "gm" (только ГМ) | "gdm" (ГМ→ГДМ) | "ggdm" (+ ансамбль);\n'
    '  "field": имя набора данных из списка (или null);\n'
    '  "adaptation": true/false;\n'
    '  "ensemble_size": целое — сколько реализаций ГМ строить (0, если не указано);\n'
    '  "exclude_operations": список id операций к исключению.\n'
    "Правило: если пользователь просит НЕСКОЛЬКО моделей/ансамбль, но не назвал число — "
    'верни mode="clarify" и спроси «Сколько реализаций (1–32)?».\n'
)


class LLMGateway:
    def __init__(self, cfg: Config) -> None:
        sec = cfg.section("llm")
        self.enabled = bool(sec.get("enabled", True))
        self.base_url = str(sec.get("base_url", "")).rstrip("/")
        # Ключ не храним в config.yaml: пусто -> env ORCH_LLM_API_KEY (или config.local.yaml).
        self.api_key = str(sec.get("api_key", "") or "").strip()
        if not self.api_key:
            self.api_key = os.environ.get("ORCH_LLM_API_KEY", "").strip()
        self.model = str(sec.get("model", ""))
        self.temperature = float(sec.get("temperature", 0.1))
        self.timeout = int(sec.get("timeout_seconds", 120))
        self.max_tokens = int(sec.get("max_tokens", 2000))

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.api_key)

    def _chat(self, system: str, user: str) -> tuple[str, str]:
        """Вернуть (content, reasoning_content). У reasoner CoT — в reasoning_content."""
        if not self.configured:
            raise LLMUnavailable("LLM не сконфигурирована (проверьте llm в config.yaml)")
        body = json.dumps({
            "model": self.model, "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"неожиданный ответ LLM: {exc}") from exc
        content = str(message.get("content") or "")
        reasoning = str(message.get("reasoning_content") or "")
        if not content and not reasoning:
            raise LLMUnavailable("пустой ответ модели")
        return content, reasoning


def _extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMUnavailable("в ответе модели нет JSON")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"JSON модели невалиден: {exc}") from exc


def _fallback_intent(text: str, *, default_ensemble: int, default_exclude: list[str],
                     field: str | None) -> Intent:
    low = (text or "").lower()
    if "гидродинамич" in low and "геологическ" not in low:
        goal = "gdm"
    elif "геологическ" in low and "гидродинамич" not in low:
        goal = "gm"
    else:
        goal = "ggdm"
    adaptation = ("адаптац" in low and "без адаптац" not in low)
    ensemble = parse_ensemble_from_text(text) or default_ensemble
    exclude = [] if adaptation else list(default_exclude)
    return Intent(goal=goal, field_name=field, adaptation=adaptation,
                  ensemble_size=max(1, ensemble), exclude_operations=exclude,
                  notes="детерминированный fallback (LLM недоступна)", source="fallback")


def converse(gateway: LLMGateway, message: str, *, context: str,
             default_ensemble: int = 1, default_exclude: list[str] | None = None,
             field: str | None = None) -> ChatDecision:
    """Ответить по онтологии/данным ИЛИ подготовить сборку (build)."""
    default_exclude = list(default_exclude or [])
    if not gateway.configured:
        intent = _fallback_intent(message, default_ensemble=default_ensemble,
                                  default_exclude=default_exclude, field=field)
        asks = any(w in (message or "").lower() for w in
                   ("что ", "какие", "какой", "перечисли", "расскажи", "почему", "?"))
        mode = "answer" if asks else "build"
        reply = ("LLM не сконфигурирована — работаю детерминированно."
                 if asks else "Собираю модель детерминированно (LLM недоступна).")
        return ChatDecision(mode=mode, reply=reply,
                            reasoning="LLM недоступна; включён fallback.",
                            intent=intent, source="fallback")
    user = (f"Сообщение пользователя: {message!r}\n\n"
            f"Контекст (онтология и данные):\n{context}\n\nВерни JSON.")
    try:
        content, cot = gateway._chat(CONV_SYSTEM, user)
        payload = _extract_json(content)
    except LLMUnavailable as exc:
        intent = _fallback_intent(message, default_ensemble=default_ensemble,
                                  default_exclude=default_exclude, field=field)
        return ChatDecision(mode="answer", reply="Не удалось получить ответ модели.",
                            reasoning=f"Ошибка LLM: {exc}", intent=intent, source="fallback")

    mode = str(payload.get("mode", "answer")).lower().strip()
    if mode not in {"answer", "build", "clarify"}:
        mode = "answer"
    goal = str(payload.get("goal", "ggdm")).lower().strip()
    if goal not in {"gm", "gdm", "ggdm"}:
        goal = "ggdm"
    adaptation = bool(payload.get("adaptation", False))
    try:
        ensemble = max(1, min(int(payload.get("ensemble_size", default_ensemble)), 32))
    except (TypeError, ValueError):
        ensemble = default_ensemble
    exclude = payload.get("exclude_operations") or []
    if not isinstance(exclude, list):
        exclude = []
    exclude = [str(x) for x in exclude]
    if not adaptation:
        for cand in default_exclude:
            if cand not in exclude:
                exclude.append(cand)
    intent = Intent(goal=goal, field_name=(payload.get("field") or field),
                    adaptation=adaptation, ensemble_size=ensemble,
                    exclude_operations=exclude,
                    notes=str(payload.get("reasoning", ""))[:500], source="llm")
    reasoning = str(cot or payload.get("reasoning", ""))[:8000]
    return ChatDecision(mode=mode, reply=str(payload.get("reply", ""))[:4000],
                        reasoning=reasoning, intent=intent, source="llm")
