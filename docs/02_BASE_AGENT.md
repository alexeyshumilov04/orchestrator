# 02. Базовый класс агента `BaseAgent` v2 и база знаний

Файлы: `agents/base_agent.py`, `agents/knowledge.py`.
Тесты: `tests/test_base_agent.py` (37 проверок).

---

## 1. Зачем базовый класс

Прототип v5 имел `BaseAgent` из 54 строк: два статических помощника и абстрактный `decision()`.
Это давало детерминированные решения, но не давало трёх вещей, без которых агент не является
агентом: (1) понимания, **чем он располагает** и чего ему не хватает; (2) **памяти** о прошлых
прогонах; (3) формального плана, который можно проверить до исполнения.

`BaseAgent` v2 добавляет ровно это — и ничего сверх: числа по-прежнему считает детерминированный
код, LLM (`agents/advisor.py`) только поясняет находки и не может отменить вердикт.

## 2. Жизненный цикл (BDI-цикл)

```
StageContext
   │ bind(ctx)                 привязка этапа: поле, индекс, гейт, агент, проектный граф
   ▼
observe(evidence)              убеждения: что реально пришло с этапа (ключи — данные)
   ▼
coverage() → CoverageReport    known / unknown / missing + ratio
   ▼
mode                           SYMBOLIC | HYBRID | GENERATIVE | ABSTAIN  (пороги — данные)
   ▼
decide() → AgentDecision       план, патчи параметров, обоснование, unknown/missing, confidence
   ▼
plan() → StagePlan (PlanIR)    функции/параметры + предупреждения режима
   ▼
validate(plan) → [Finding]     формальные находки ДО исполнения
   ▼
[исполнение: рендер и запуск делает StageRunner — агент не владеет tNavigator]
   ▼
verify(findings, metrics)      вердикт гейта (через GateEngine, если он подключён)
   ▼
remember(memo) → KB            запись опыта: план, свидетельства, метрики, вердикт
   ▼
reconsider(findings)           правка после провала: опыт БЗ → variations проекта → эскалация
```

Режимы решения (пороги `agents.policy.symbolic_threshold` / `hybrid_threshold`, данные):

| Режим | Когда | Что означает |
|---|---|---|
| `SYMBOLIC` | покрытие ≥ symbolic (1.0) | план целиком из утверждённых правил/данных |
| `HYBRID` | покрытие ≥ hybrid (0.6) | детерминированный каркас; LLM может синтезировать только найденный пробел, результат проходит гейт |
| `GENERATIVE` | покрытие ниже hybrid, но есть известные входы | черновики плана; исполнение только после гейта человека |
| `ABSTAIN` | нет ни одного известного входа | решать не на чем: план не выдумывается, фиксируются `missing` |

## 3. Публичный контракт

| Метод | Вход → выход | Смысл |
|---|---|---|
| `bind(ctx)` | `StageContext \| dict` → self | привязать этап |
| `policy()` | — → dict | пороги режима из данных |
| `observe(ev)` | dict → beliefs | обновить убеждения фактами |
| `requirements()` | — → [str] | обязательные входы агента (`agents.required_inputs.<agent_id>`) |
| `coverage()` | — → `CoverageReport` | полнота входов: `known/unknown/missing/ratio/mode` |
| `capabilities()` | — → [`Capability`] | способности из данных, с флагом `verified` |
| `decision(project, ev)` | — → dict | **точка расширения** наследника (абстрактная) |
| `decide(project, ev)` | — → dict | полное решение: слияние ключей наследника (`enabled/reason/coverage/parameters/…`) и метаданных цикла (`mode/plan/coverage_report/unknown/missing/coverage_report/…`) |
| `plan()` | — → `StagePlan` | PlanIR последнего решения |
| `validate(plan=None)` | → [`Finding`] | пустой план у включённого этапа, нечисловые параметры, глубокая вложенность |
| `verify(findings, metrics)` | → dict | вердикт: `GateVerdict` через движок гейтов либо детерминированная сводка |
| `remember(memo, metrics)` | → ts | запись опыта в БЗ |
| `recall(...)` / `suggest(...)` | → [...] / dict | похожий опыт / рекомендация параметров |
| `reconsider(findings)` | → dict | `rework` (из БЗ) \| `escalate` \| `none` |
| `state()` | → dict | снимок агента для отчёта |
| `_num`, `_section` | — | утилиты без домена (совместимость с v5) |

Обратная совместимость: `decide()` возвращает **слияние** — прежние ключи решений
(`enabled`, `reason`, `coverage`, `parameters`, доменные поля агента) сохраняются, сверху
добавляются метаданные цикла. Поэтому обёртки `decide_erosion/decide_grid/decide_facies/
decide_petrophysics` и `StageRunner` продолжают работать без правок (223 теста).

## 4. База знаний

Два слоя, оба — данные.

### 4.1 Статическая БЗ (`StaticKnowledge`)

Онтология BDI v4.1 из `agents.bdi_dir` (`ontology/bdi_knowledge/neurosymbolic_agents/`):

| Файл | Содержимое | Использование |
|---|---|---|
| `decision_tables_v4_1.csv` | таблицы решений: правило, приоритет, формальный guard, намерение, требуемое подтверждение человека | источник правил для решений агентов |
| `literature_and_architecture_rules.csv` | 83 правила, выведенные из литературы и архитектуры (выбор метода фаций, режим покрытия, право исполнения, handoff, reconsideration, …) | обоснование выбора метода |
| `belief_schema_v4_1.csv` | типизированная схема убеждений агента | какие belief-и допустимы |
| `agent_profiles.csv` / `handoff_contracts.csv` | 22 профиля агентов, 17 контрактов передачи | назначение агентов и меморандумы (`agents/registry.py`) |

### 4.2 Динамическая БЗ (`KnowledgeBase`) — опыт прогонов

Формат — append-only JSONL, два адреса:

* накопительный: `agents.kb_dir` → `knowledge/agents/ledger.jsonl`;
* внутрипрогонный: `runs/<id>/agents/kb/<agent>.jsonl` (трассируемость конкретного прогона).

Запись `ExperienceRecord`:

```json
{"agent": "AG_FACIES", "stage": "6. Фации (SIS)", "gate": "G-FACIES", "field_name": "Герасимовское",
 "mode": "symbolic", "verdict": "passed", "attempts": 1, "degraded": false, "outcome": "passed",
 "functions": ["grid_property_facies_modeling"],
 "parameters": {"grid_property_facies_modeling": {"range_main": 3500.0, "nugget": 0.15}},
 "plan_hash": "<sha256>", "evidence_hash": "<sha256>",
 "metrics": {"kq": 1.0, "kc": 0.714, "fitness": 0.857},
 "status": "candidate", "provenance": "G-FACIES:5", "ts": "2026-…Z"}
```

Извлечение — **детерминированное**:

* `recall(agent, stage, functions, parameters, k)` — фильтр по агенту/этапу, близость по
  нормированному вектору числовых параметров (`agents.recall.numeric_tolerance`), нечисловые —
  на равенство; сортировка «пересечение функций → близость → свежесть»; по умолчанию берутся
  только удачные записи (`passed`/`degraded`);
* `suggest(...)` — **медиана** числовых наблюдений по каждому коду параметра (устойчива к
  единичному выбросу); нет опыта — пустой словарь (план остаётся на данных проекта);
* `promote()` — продвижение знания `candidate → repeatable → approved` по числу удачных
  наблюдений одного ключа (агент + этап + набор функций), пороги — данные
  (`agents.policy.promotion`). Провальные записи остаются `candidate`: отрицательный опыт
  сохраняется, но плана по умолчанию не задаёт.

## 5. Как подключается агент (данные, без кода)

```yaml
agents:
  policy:   {symbolic_threshold: 1.0, hybrid_threshold: 0.6,
             promotion: {repeatable_runs: 2, approved_runs: 3},
             verified_capabilities: []}
  required_inputs:                 # чем агент обязан располагать
    AG_STRUCTURAL:  ["structural", "welltops"]
    AG_FACIES:      ["geostat"]
    AG_PETROPHYSICS:["petrophysics"]
  recall:   {k: 5, min_status: "candidate", numeric_tolerance: 0.25}
gates:                             # этап → агент → гейт → блоки чеклиста → политика
checks:
  package_blocks: {G-FACIES: ["05","06"], G-PETRO: ["07","08","13"], …}
```

Наследник объявляет только `agent_id` (профиль BDI) и `label`, и реализует `decision()`.
Ни одного доменного значения в классе-наследнике быть не должно — это проверяет
`tests/test_no_domain_in_code.py`.

## 6. Гарантии

1. **Решение воспроизводимо**: один и тот же проектный граф + свидетельства → одно решение
   (в `recall` нет случайности, LLM не участвует в числах).
2. **Неизвестное ≠ ложь**: нет входов → `ABSTAIN` + `missing`; нет опыта → `suggest() == {}`;
   нет предмета проверки → `validate() == []` (а не «провал»).
3. **Провал не скрывается**: `verify()` при `critical`-находке даёт `failed`; `reconsider()`
   без опыта возвращает `escalate`, а не выдуманную правку.
4. **Опыт отделён от фактов**: БЗ хранит только то, что реально произошло в прогонах
   (вердикт, метрики, параметры, хэши артефактов); «знание» продвигается по числу наблюдений.
