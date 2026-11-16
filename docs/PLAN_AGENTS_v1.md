# ПЛАН: агенты структурных и фациальных построений (до петрофизики) для 3D-ГГДМ

Версия 1 (на согласование). Дата: см. коммит/сессию.
Целевой прототип: `orchestrator/` (актуальная сборка v5). Источники-референсы (read-only):
`orchestrator_v7/orchestrator/` (снимок 08.10), `orchestrator_v7/Эволюция/` (критерии критика),
`QAQC/QA_QC_чеклист.xlsx` (реестр 6065 пунктов).

---

## 0. Зафиксированная базовая линия (факты, не предположения)

| Проверка | Команда | Результат |
|---|---|---|
| Тесты | `python -X utf8 tests/test_v5.py` | **32/32** (0 провалов) |
| Preflight | `python -X utf8 main.py preflight` | **preflight: OK**; tNav `v26.2-3743`, `api_available: true`, `FEAT_GEOLOGY_DESIGNER`; онтология 1272 операции / 18 стадий / 3257 функций / 6117 QA-правил / 403 параметра |
| Dry-run | `python -X utf8 main.py run --field Герасимовское` | **steps.total = 36**, done **35**, `skipped_by_policy` 1 (врез), `render_warnings = []` |
| QA/QC в отчёте | `runs/run_Герасимовское/report.json` | ключа `qaqc` **НЕТ**; `critic.verdict = unknown` (6117/6117 unknown) |
| Интерпретатор | — | рабочий Python — **`C:\ProgramData\anaconda3\python.exe` (3.11.5)**; `C:\Python314` без PyYAML/numpy/fastapi |

Расхождения с текстом жёстких правил (правило 8 — проверяем по факту):
* ожидалось «33/33 шага» — фактически **36 шагов** (35 done + 1 skipped_by_policy);
* `test_v5.py` — 32/32 ✔;
* установлен **только тНав 26.2** (26.1 на машине нет); `config.local.yaml` уже указывает на 26.2.

### Что уже есть в прототипе (не переделывать)

* **Пайплайн (данные)**: `ontology_project/gerasimovskoe.yaml` — стадии 0…10, 36 шагов, 5 вариаций.
* **Триада функций**: 33 шаблона `domain/templates/*.txt` + 33 правила `domain/ontology_rules/*.rdf` + блоки в YAML.
* **Агенты-политики**: `agents/base_agent.py` (54 строки!), `structure_policy`, `grid_policy`,
  `facies_policy`, `petrophysics_policy` + 5 обёрток `decide_*`.
* **Гейты**: `agents/gates.py` (8 гейтов в `config.yaml` → стадии 0…10), `FALLBACK_GATES`,
  политики `best|skip|halt|ask`, байпас, waiver, `DecisionBroker`.
* **Проверки**: `agents/checks/` — 16 builtin + 5 контрактных, `CheckRegistry`, реестр с `runtime`-флагом.
* **Контракты**: `agents/contracts.py` — `Finding`, `StageContext`, `StagePlan`, `GateVerdict`,
  `StageResult`, `HandoffMemo` (ревизии, lineage, units/CRS, QA, evidence_hash).
* **Свидетельства**: `agents/evidence.py` — static (отбивки, бланк/extent карт, бокс, траектории) +
  runtime-пробники в `runner._attach_runtime_evidence` (well_tie / grid / stoiip / property_mean / maps).
* **QA/QC-пакет как данные**: `domain/qaqc/` — `checks_table.csv` **652 проверки** →
  `checks.py` (CHECKS) → `engine.py` (35 примитивов) → `qaqc_adapter.evaluate(values, blocks)` → `kq/kc/physical/fitness`.
* **Онтология агентов (уже есть!)**: `ontology/bdi_knowledge/neurosymbolic_agents/` —
  `agent_profiles.csv` (**22 профиля BDI**), `handoff_contracts.csv` (17), `decision_tables_v4_1.csv`
  (1796 формальных guard'ов), `belief_schema_v4_1.csv`, `literature_and_architecture_rules.csv` (83 правила),
  `assessment_uncertainty_registers.csv`, RDF-базы знаний.

### Установленные пробелы (gap)

| # | Пробел | Факт | Последствие |
|---|---|---|---|
| G1 | `qaqc` не попадает в отчёт v5 | в `coordinator.run` нет свёртки `QaqcReport` | нет kq/kc/фитнеса в отчёте, гейты не используют пакет целиком |
| G2 | Пакет покрывает 652 из 6065 пунктов чеклиста | блоки: 02→438, 04→148, 05→40, 13→10, 03→7, 06→7, 14→2 | блоки **07, 08, 09, 10, 11, 12 не оцифрованы вообще** |
| G3 | `critic` = unknown 6117/6117 | нет значений модели в `_qaqc_values` | вердикт неинформативен |
| G4 | Гейтов 8, стадии 6.1/7/9/10 не имеют своих гейтов | 6.1 слита с G-FACIES, карты — с G-MAPS | нет гейта на кубы PORO/PERM по отдельности, на фациальные карты, на геотела |
| G5 | Карты свойств/фаций не строятся как объекты | нативный `create_screenshot` недоступен в консоли | 4 карты из 8 — только matplotlib-фолбэк из irap |
| G6 | Агент = 54 строки, без БЗ, без CoverageReport, без PlanIR | `BaseAgent.decision()` + 2 утилиты | нет хранения опыта, нет «режима SYMBOLIC/HYBRID/GENERATIVE», нет ответа «чего не хватает» |
| G7 | Нет проверки «домен в данных» автоматически | правило 1 держится вручную | риск регресса хардкода |

---

## 1. Целевая архитектура

```
                         ┌──────────────────────── ДАННЫЕ (только данные) ───────────────────────┐
                         │ ontology/            process_catalog, tnavigator_functions,           │
                         │                      data_parameter_catalog, qaqc_rules,               │
                         │                      software_mappings, RDF                          │
                         │ ontology/bdi_knowledge/  agent_profiles, handoff_contracts,          │
                         │                      decision_tables, belief_schema, literature_rules │
                         │ ontology/qa_gate_map.yaml     ← НОВОЕ: блок чеклиста → гейт → агент   │
                         │ ontology/qa_checks/*.csv      ← НОВОЕ: оцифровка блоков 06…13        │
                         │ ontology_project/<поле>.yaml  стадии, объекты, маркеры, вариации     │
                         │ domain/templates/*.txt        сырые шаблоны функций тНава            │
                         │ domain/ontology_rules/*.rdf   правила функций (роли/параметры)        │
                         │ config.yaml                   гейты, пороги, блоки, ансамбль          │
                         └───────────────────────────────┬───────────────────────────────────────┘
                                                         │ читается как данные
   ┌─────────────────────────────────────────────────────┼──────────────────────────────────────────┐
   │ ДОМЕН  domain/                                      ▼                                          │
   │  tnav_client · assembler · function_rules · workflow_renderer · trajectories · welltops        │
   │  geostat · irap · map_render · tnav_probes                                                     │
   │  qaqc/  (пакет проверок: checks_table.csv → checks → engine → adapter)                         │
   │  qc/    НОВОЕ: probes (снять значения модели), values (сборка DataContext), maps (экспорт карт) │
   └─────────────────────────────────────────────────────┬──────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────────┼──────────────────────────────────────────┐
   │ ЯДРО  core/                                         ▼                                          │
   │  coordinator (фасад) · config · planner · pipeline · node_contract · metrics                    │
   │  ensemble · rollup · system_model · graph_generator · project_generator · llm_gateway           │
   └─────────────────────────────────────────────────────┬──────────────────────────────────────────┘
   ┌─────────────────────────────────────────────────────┼──────────────────────────────────────────┐
   │ АГЕНТЫ  agents/                                     ▼                                          │
   │  ┌───────────────────────── BaseAgent v2 (единый контракт) ──────────────────────────────┐      │
   │  │ bind(StageContext) → observe(evidence) → beliefs → coverage() → decide() → plan()      │      │
   │  │ → validate() → [act: рендер/исполнение делает StageRunner] → verify() → remember(KB)  │      │
   │  └───────┬───────────┬───────────┬───────────┬───────────┬──────────┬──────────┬─────────┘      │
   │   Structural   Grid      Facies    Petrophysics  Saturation  Volumetrics  Maps   QA-Remediation │
   │   AG_STRUCTURAL AG_GRID  AG_FACIES AG_PETROPHYS  AG_PVT_SCAL AG_GRID_VOL  …      AG_QA_REMEDIATION│
   │  knowledge.py (БЗ: журнал опыта + извлечение) · capabilities.py (что агент умеет, из онтологии)  │
   │  registry.py (BDI-профили) · stage_map.py · gates.py (движок) · checks/ (реестр проверок)        │
   │  contracts.py · evidence.py · decisions.py · advisor.py (LLM только советует)                    │
   └──────────────────────────────────────────────────────────────────────────────────────────────────┘
   ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
   │ АРТЕФАКТЫ  runs/run_<поле>/                                                                       │
   │  agents/stages/NN_<gate>.py · agents/gates/<gate>.json · agents/handoffs/*.json                   │
   │  agents/kb/*.jsonl (опыт) · qaqc.json (kq/kc/по блокам) · maps/*.png · report.json                │
   └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Зависимости — строго вниз: `agents → core → domain → данные`. Домен в `.py` не попадает:
имена объектов/маркеров/порогов/путей живут только в `config.yaml`, `ontology*`, `domain/templates`,
`domain/ontology_rules`.

---

## 2. Базовый класс агента (BaseAgent v2) — детально

Файл: `agents/base_agent.py` (+ `agents/knowledge.py`, `agents/capabilities.py`, `agents/beliefs.py`).

Жизненный цикл (BDI-цикл из `BDI_AGENT_DIVISION_AND_AUTONOMY_AUDIT.md`, реализованный детерминированно):

```
StageContext ──► beliefs ──► coverage ──► mode ──► StagePlan(PlanIR) ──► formal validation
                                                    │                        │
                                              (SYMBOLIC|HYBRID|GENERATIVE|ABSTAIN)
                                                    ▼                        ▼
                                        StageRunner (рендер+исполнение) ──► findings
                                                    ▼
                                            GateVerdict ──► HandoffMemo ──► KB.remember()
                                                    │
                                              rework / reconsider
```

Публичный контракт (стабильные имена — на них пишутся тесты):

| Метод | Вход | Выход | Смысл |
|---|---|---|---|
| `bind(ctx)` | `StageContext` | `self` | привязать этап, поле, попытку, проектный граф |
| `observe(evidence)` | dict | `beliefs: dict` | обновить убеждения фактами (без домена в коде) |
| `coverage()` | — | `CoverageReport` | `{known: [...], unknown: [...], missing: [...], ratio}` — «чего не хватает для решения» |
| `decide()` | — | `AgentDecision` | `{mode, plan, patches, rationale, unknown, confidence, evidence_refs}` |
| `plan()` | — | `StagePlan` (PlanIR) | `{functions, parameters, objects, replace, preconditions, postconditions, rollback}` |
| `validate(plan)` | plan | `[Finding]` | формальная проверка: схема, диапазоны из `data_parameter_catalog`, допустимые capability, обязательные объекты |
| `verify(findings, metrics)` | — | `GateVerdict` | вердикт по проверкам (делегируется `GateEngine`) |
| `remember(memo)` | `HandoffMemo` | `record_id` | запись опыта в БЗ |
| `recall(situation)` | dict | `[Experience]` | извлечение похожего опыта из БЗ |
| `reconsider(finding)` | `Finding` | `ReworkProposal` | предложение правки (из БЗ + `variations`, без LLM) |
| `capabilities()` | — | `[Capability]` | что агент умеет (из онтологии/каталога функций) |

Свойства класса (данные, не код): `agent_id` (имя BDI-профиля), `label`, `gate_ids`,
`stage_numbers`, `ontology_slice` (какие блоки QA/QC и какие операции его), `policy` (пороги из YAML).

**Режимы решения** (пороги — данные `policy.symbolic_threshold` / `hybrid_threshold`):
* `SYMBOLIC` — покрытие ≥ symbolic → план целиком из утверждённых правил;
* `HYBRID` — покрытие ≥ hybrid → детерминированный каркас + LLM синтезирует только пробел;
* `GENERATIVE` — иначе → несколько черновиков плана, исполнение в sandbox/после гейта человека;
* `ABSTAIN` — данных нет → «неизвестное ≠ ложь»: этап не отключается молча, а фиксируется
  `unknown` с перечнем недостающих входов.

**Наследники** (каждый — только данные + policy, без домена):
`StructuralAgent`, `GridAgent`, `FaciesAgent`, `PetrophysicsAgent`, `SaturationAgent`,
`VolumetricsAgent`, `MapsAgent`, `QaRemediationAgent` (+ `UncertaintyAgent` для ансамбля).

### База знаний (БЗ) агентов

`agents/knowledge.py`, хранилище — данные:
* **Статическая БЗ** (read-only, из онтологии): `decision_tables_v4_1.csv` (1796 правил),
  `literature_and_architecture_rules.csv` (83 правила), `belief_schema_v4_1.csv`,
  `handoff_contracts.csv`, `agent_profiles.csv`;
* **Динамическая БЗ** (опыт прогонов): `runs/<id>/agents/kb/<agent>.jsonl` + сводный
  `knowledge/agents/ledger.jsonl` (накопительный). Запись `ExperienceRecord`:
  `{agent, field, stage, gate, plan_hash, functions, parameters, evidence_hash, metrics{kq,kc,fitness,stoiip,…}, verdict, attempts, degraded, outcome, ts, provenance}`;
* **Извлечение** — детерминированное: фильтр по (агент, стадия, набор функций), метрика близости по
  нормированному вектору параметров и сигнатуре свидетельств, агрегация «top-k → рекомендация
  параметров» (медиана/лучший). LLM не участвует в числах;
* **Продвижение знания**: `candidate → repeatable → approved` по числу удачных повторений
  (порог — данные); только `approved` влияет на план по умолчанию.

---

## 3. Агенты: состав, обязанности, гейты

| # | Агент (BDI-профиль) | Стадии | Что строит | Гейт | Основные проверки |
|---|---|---|---|---|---|
| 1 | `AG_DATA_STEWARD` | 0 | импорт, траектории, отбивки, карты, разломы | `G-DATA` | блоки 01, 02, 03 |
| 2 | `AG_STRUCTURAL` | 1, 2, 3 | горизонты, толщины, врез/эрозия, разломный каркас | `G-STRUCT` | блок 04 + `struct.well_tie*` |
| 3 | `AG_GRID_VOLUMETRICS` | 4, 5 | corner-point сетка, апскейлинг ГИС | `G-GRID` | блок 04 + `grid.geometry/quality` |
| 4 | `AG_FACIES` | 6 | **куб фаций** (SIS/MPS/объектное), геотела | `G-FACIES` | блоки 05, 06 |
| 5 | `AG_ROCKTYPE` | 6.1 | литотипы/rock-types из фаций и ГИС | `G-LITHO` | блок 06 |
| 6 | `AG_PETROPHYSICS` | 7 | **кубы PORO/PERM** из ГИС (интерполяция по фациям) | `G-PETRO` | блоки 07, 08, 13 |
| 7 | `AG_PVT_SCAL` | 8 | контакты, насыщение, PVT/SCAL | `G-SAT` | блок 09 |
| 8 | `AG_GRID_VOLUMETRICS` | 9 | волюметрия, запасы | `G-VOL` | блок 10 |
| 9 | `AG_GRID_VOLUMETRICS` | 10 | **карты**: структурные, толщин, **фаций**, **петрофизики** | `G-MAPS` | блок 10 + `maps.*` |
| 10 | `AG_QA_REMEDIATION` | сквозной | разбор findings, маршрутизация исправлений (не может отменить fatal) | — | все блоки |
| 11 | `AG_UNCERTAINTY` | ансамбль | оси вариаций, свёртка p10/p50/p90, выбор ветвей | `G-ENSEMBLE` | блок 11 |

Гейты расширяются данными (`config.yaml → gates`, плюс `ontology/qa_gate_map.yaml`):

```yaml
- {id: G-DATA,   agent: AG_DATA_STEWARD,     stages: [0],    blocks: ["01","02","03"], min_kq: …, min_kc: …}
- {id: G-STRUCT, agent: AG_STRUCTURAL,        stages: [1,2,3], blocks: ["04"],  evidence: [{kind: well_tie},{kind: horizon_stats}]}
- {id: G-GRID,   agent: AG_GRID_VOLUMETRICS,  stages: [4,5],  blocks: ["04"],  evidence: [{kind: grid},{kind: upscale_qc}]}
- {id: G-FACIES, agent: AG_FACIES,            stages: [6],    blocks: ["05","06"], evidence: [{kind: facies_stats},{kind: proportions}]}
- {id: G-LITHO,  agent: AG_ROCKTYPE,          stages: [6.1],  blocks: ["06"]}
- {id: G-PETRO,  agent: AG_PETROPHYSICS,      stages: [7],    blocks: ["07","08","13"], evidence: [{kind: property_mean},{kind: property_stats}]}
- {id: G-SAT,    agent: AG_PVT_SCAL,          stages: [8],    blocks: ["09"]}
- {id: G-VOL,    agent: AG_GRID_VOLUMETRICS,  stages: [9],    blocks: ["10"],  evidence: [{kind: stoiip}]}
- {id: G-MAPS,   agent: AG_GRID_VOLUMETRICS,  stages: [10],   blocks: ["10"],  evidence: [{kind: maps},{kind: map_stats}]}
- {id: G-ENSEMBLE, agent: AG_UNCERTAINTY,     stages: ["*"],  blocks: ["11"]}
```
Все значения — данные; в `.py` только чтение ключей.

---

## 4. QA/QC как гейты: что именно реализуем

Источник проверок — `QAQC/QA_QC_чеклист.xlsx` (6065 записей: 5870 «формализованная проверка-кандидат»,
100 «функция QA/QC ТПУ», 54 НИОКР, 33 укрупнённых обязательных, 5 метакритик, 3 проверки цепочки).
Распределение по обязательным блокам ГПН:

| Блок | Пунктов | Оцифровано в `domain/qaqc` | Статус |
|---|---:|---:|---|
| 01 Информация для экспертизы | 8 | 0 | новый |
| 02 Полнота входных данных | 618 | 438 | расширить |
| 03 Стратиграфическое расчленение | 173 | 7 | расширить |
| 04 Структурная модель | 679 | 148 | расширить |
| 05 Куб фаций | 1481 | 40 | расширить (ядро задачи) |
| 06 Куб литологии | 528 | 7 | расширить |
| 07 Куб пористости | 61 | 0 | новый |
| 08 Куб проницаемости | 69 | 0 | новый |
| 09 Куб насыщения | 737 | 0 | новый |
| 10 Подсчёт запасов | 86 | 0 | новый |
| 11 Неопределённости | 399 | 0 | новый |
| 12 ГДМ | 158 | 0 | вне текущего объёма |
| 13 Петрофизика (керн/ГИС) | 873 | 10 | расширить (ядро задачи) |

**Механика (единая, без хардкода):**
1. Новые проверки пишутся в формате уже существующего пакета:
   `ID;Блок;Название;Способ выполнения;Порог;Входные ключи;Значимость;Формула;Критерий;Фитнес` →
   `ontology/qa_checks/b<NN>.csv` → сборка в `domain/qaqc/checks_table.csv` (652 → N).
   Схема `Check/MetricSpec/Threshold` и 35 примитивов уже есть; при нехватке примитива —
   добавить в `primitives.py` (это домен-нейтральная математика, допустимо).
2. Слой значений: `domain/qc/probes.py` снимает с **открытого** проекта всё, что требуют проверки
   (свойства сетки, статистики кубов, коды фаций и пропорции, контакты, зоны, объёмы, гистограммы),
   `domain/qc/values.py` собирает `DataContext`. Ключи берутся из колонки «Входные ключи» самих проверок.
3. `agents/checks/adapters.py` уже умеет прогонять пакет по блокам гейта; добавляется
   разбивка находок по проверкам (id/порог/факт) и агрегация `kq/kc/fitness` в отчёт.
4. Три исхода: `passed` / `failed` / `not_applicable` (нет данных) + `unknown`
   (правило не формализовано — 5870 записей остаются `unknown`, а не `false`).
5. `qaqc` попадает в `report.json` (закрытие G1) и в каждый `GateVerdict`.

Отчёт соответствия чеклисту — обязательный артефакт: `runs/<id>/qaqc_coverage.json`
(по каждому из 6065 пунктов: реализовано / not_applicable+причина / unknown+причина).

---

## 5. tNavigator: триады функций, которые добавляем

Каждая — по правилу 2: `domain/templates/<fn>.txt` + `domain/ontology_rules/<fn>.rdf` + блок в YAML.

| Задача | Функции (найдены в `ontology/tnavigator_functions.csv` и туториалах) | Источник/статус |
|---|---|---|
| Карты **петрофизики и фаций** (2D из 3D) | `map_2d_create_by_grid_property` | tNavUserGuideDesigner p.1812, S15 — **новая триада** |
| Экспорт карт без GUI | `map_2d_export_cps_format`, `map_2d_export_ascii_format` → matplotlib PNG | p.1884 — **новая триада** |
| Вспомогательные карты | `map_2d_thickness_map`, `map_2d_create_volumetric_maps`, `map_2d_statistic` | p.1804/1807/1846 |
| **Куб фаций** | `grid_property_create_by_zones` (дискретный шаблон!) → `grid_property_facies_modeling` (создаёт куб сама) | доказано в `orchestrator_v7/.../docs/tasks/B4_facies.md` |
| Петрофизика по фациям | `grid_property_interpolate_by_wells_log_3d` (беззонная форма), `grid_property_change_type`, `grid_property_calculator` | B3/B4: `ZoneRegionFilter(zone=None)`, `ZoneRegionParameters(use=True)` |
| Сетка с разломами | `grid_3d_create_by_horizons_with_faults` | шаблон+правило уже есть, подключить ступенчато |
| QC-свидетельства | статистики свойств/карт через пробники (`compute_statistics`, `get_all_properties`) | есть канал «py → tmp → разбор» |
| Разломы/структура | `fault_import_sticks_xyz_format` (есть), `fault_export_sticks_xyz_format` | p.2131–2132 |

Правило 8 — каждая новая триада верифицируется на живой лицензии (проба в одной сессии тНава,
как `tools/probe_facies_modeling.py`); до верификации шаг помечается «не проверен», а не «работает».

---

## 6. Этапы работ (WBS)

| Этап | Содержание | Артефакт | Приёмка |
|---|---|---|---|
| **E0** | Фиксация окружения и правил: `docs/AGENT_RULES.md` (жёсткие правила 1–8), реестр хардкода, скрипт-аудит `tests/test_no_domain_in_code.py` | документ + тест | тест ловит домен в `.py` |
| **E1** | **BaseAgent v2 + БЗ + CoverageReport/PlanIR + capabilities + beliefs** | `agents/base_agent.py`, `knowledge.py`, `capabilities.py`, `beliefs.py`, `tests/test_base_agent.py` | тесты; все прежние 4 агента переведены на v2 без регресса |
| **E2** | Реестр проверок из данных: `qa_gate_map.yaml`, блоки в `gates:`, `CheckRegistry` из CSV, `qaqc` в отчёте | данные + `agents/checks/*`, `core/coordinator.py` | `report.json → qaqc` заполнен, kq/kc видны |
| **E3** | Оцифровка блоков **06, 07, 08, 13** (фации/литология/пористость/проницаемость) + слой значений `domain/qc/` | `ontology/qa_checks/*.csv`, `domain/qc/*.py` | проверки применимы на реальном прогоне, отчёт соответствия |
| **E4** | **Структурный агент v2** (горизонты/толщины/врез/разломы) + гейт `G-STRUCT` v2 | `agents/structural.py` | dry-run без регресса; `kq/kc` растут |
| **E5** | **Агент сетки и апскейлинга** (бокс/шаг/слои, QC ячеек) | `agents/grid.py` | `grid.geometry/quality` = passed по факту |
| **E6** | **Фациальный агент**: куб `FACIES` (дискретный шаблон), пропорции, вариограммы, геотела; блоки 05/06 | триады + `agents/facies.py` | на реальном прогоне куб `FACIES` создан |
| **E7** | **Петрофизический агент**: кубы `PORO/PERM` по фациям, блоки 07/08/13 | триады + `agents/petrophysics.py` | кубы созданы, диапазоны в норме |
| **E8** | **Агент карт**: `map_2d_create_by_grid_property` + экспорт + matplotlib PNG; карты структуры/толщин/фаций/петрофизики | триады + `agents/maps.py`, `domain/qc/maps.py` | ≥8 карт в `runs/<id>/maps/`, `maps.files` = passed |
| **E9** | Насыщение/волюметрия/ансамбль: гейты `G-SAT`, `G-VOL`, `G-ENSEMBLE`, блоки 09/10/11 | данные + агенты | свёртка p10/p50/p90 невырождена |
| **E10** | Независимая верификация: тесты, dry-run, реальный прогон, отчёт соответствия чеклисту | отчёт | см. §7 |
| **E11** | Документация: архитектура, каждый агент, онтология, результаты | `docs/*.md` (+ DOCX) | ревью заказчика |

---

## 7. Протокол проверки (после каждой правки, правило 3)

```powershell
$py = "C:\ProgramData\anaconda3\python.exe"     # 3.14 без зависимостей
cd orchestrator
& $py -X utf8 tests/test_v5.py                                   # 32/32 (цель: не ниже)
& $py -X utf8 tests/test_agents.py                               # 223/223 (цель: не ниже)
& $py -X utf8 main.py preflight                                  # preflight: OK
& $py -X utf8 main.py run --field Герасимовское                   # dry-run, render_warnings=[]
& $py -X utf8 main.py run --field Герасимовское --execute         # ~13 мин, лицензия
```
Плюс новые тесты: `test_base_agent.py`, `test_kb.py`, `test_qaqc_gates.py`, `test_maps.py`,
`test_no_domain_in_code.py`.
Приёмка: `steps` без `error`, `render_warnings=[]`, `qaqc.kq/kc` посчитаны, число `not_applicable`
падает, карты ≥8, кубы `FACIES/PORO/PERM` в объектах проекта, `tests` зелёные.

---

## 8. Команда и разделение записи (write scopes)

| Роль | Задача | Пишет только в |
|---|---|---|
| **Lead** (я) | архитектура, BaseAgent v2, сборка, финальная приёмка | `agents/base_agent.py`, `agents/knowledge.py`, `docs/`, `README.md` |
| `foundation` | contracts/registry/stage_map/gates/checks-каркас | `agents/contracts.py`, `registry.py`, `stage_map.py`, `gates.py`, `checks/`, `tests/test_base_agent.py` |
| `structural` | структурный + сеточный агенты, триады поверхности/толщины/разломы | `agents/structural.py`, `agents/grid.py`, `domain/templates/{horizon_*,map_2d_thickness_map,*faults*}.txt`, `domain/ontology_rules/*.rdf` (только эти имена) |
| `facies` | фациальный агент, куб FACIES, геотела, карты фаций | `agents/facies.py`, `domain/templates/{grid_property_facies_*,grid_property_create_by_zones,map_2d_create_by_grid_property}.txt` |
| `petro` | петрофизика, кубы PORO/PERM, насыщение, карты свойств | `agents/petrophysics.py`, `agents/saturation.py`, `domain/templates/{grid_property_interpolate_by_wells_log_3d,grid_property_change_type,map_2d_*}.txt` |
| `qaqc` | оцифровка блоков 06–13, слой значений, отчёт соответствия | `ontology/qa_checks/`, `domain/qaqc/`, `domain/qc/`, `agents/checks/adapters.py` |
| `verifier` | независимая проверка: тесты, dry-run, аудит хардкода, соответствие чеклисту | `tests/` (свои файлы), `docs/VERIFY_*.md` |

Правило: `ontology_project/gerasimovskoe.yaml` и `config.yaml` — **единственный писатель за раз**
(блоки стадий распределяются по этапам E4–E9 последовательно, чтобы не конфликтовать).

---

## 9. Риски и открытые вопросы

| Риск | Митигация |
|---|---|
| Функции фаций исторически падали (`Unable to create operation`) | сначала дешёвая проба в одной сессии тНава (`tools/probe_*.py`), потом триада; гейт `skip` как страховка |
| Недоступность лицензии/зависший API тНава | дружелюбная деградация: dry-run всегда зелёный, `tnav_ok=false` фиксируется, а не скрывается |
| Раздувание времени прогона (36 шагов × 5 ветвей) | `--ensemble-size 1` для итераций, полный ансамбль — на приёмке |
| «Неизвестное ≠ ложь» размывается | `not_applicable/unknown` обязательны и попадают в отчёт с причиной |
| 6065 пунктов чеклиста невозможно закрыть | фиксируем покрытие честно: `qaqc_coverage.json` + явный список «вне объёма» |
| Требование «ни одного доменного имени в .py» | автоматический тест `test_no_domain_in_code.py` |
