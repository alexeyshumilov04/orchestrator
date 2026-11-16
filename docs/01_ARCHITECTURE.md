# 01. Архитектура `orchestrator_v8` — агенты 3D-ГГДМ в tNavigator

> **Схемы архитектуры (Mermaid)** — в отдельном документе: [18_АРХИТЕКТУРА_схемы.md](18_АРХИТЕКТУРА_схемы.md):
> слои системы, сборка воркфлоу из онтологии, последовательность прогона, QA/QC-гейты,
> ансамбль и сохранение моделей, веб-слой с графом моделирования, добавление нового поля.
> Ниже — текстовое описание тех же слоёв и ответственностей.

Документ описывает целевую архитектуру прототипа: слои, потоки данных, контракты,
роли агентов и место QA/QC-гейтов. Жёсткие правила — `docs/AGENT_RULES.md`,
план работ — `docs/PLAN_AGENTS_v2.md`.

---

## 1. Принцип: домен только в данных

```
ДАННЫЕ                    ЯДРО (core/)                ДОМЕН (domain/)            АГЕНТЫ (agents/)
ontology/*.csv|rdf  ──►  coordinator, planner   ──►  assembler, function_rules  ──► BaseAgent v2
ontology_project/*.yaml   pipeline, ensemble          workflow_renderer             ├ Structural
domain/templates/*.txt    rollup, metrics             tnav_client, trajectories     ├ Grid
domain/ontology_rules/*   node_contract               welltops, geostat, irap       ├ Facies
config.yaml               system_model                map_render, tnav_probes       ├ Petrophysics
                                                     qaqc/ (пакет проверок)        ├ Saturation
                                                                                   ├ Volumetrics
                                                                                   ├ Maps
                                                                                   └ QA-Remediation
```

Правило зависимостей: **только вниз** (`agents → core → domain → данные`).
`.py` не содержит имён объектов/маркеров/кубов/порогов/путей/координат — только **ключи** данных.
Контроль — `tests/test_no_domain_in_code.py` (токены собираются из данных, код разбирается `ast`).

## 2. Слои и ответственность

| Слой | Модули | Ответственность |
|---|---|---|
| **Оркестрация** | `core/coordinator.py`, `planner.py`, `pipeline.py`, `execution.py`, `runner.py` | маршрутизация прогона, сборка спеки и воркфлоу, чтение модели, отчёты |
| **Знание** | `core/ontology.py`, `ontology/**`, `agents/knowledge.py`, `agents/registry.py` | каталоги процессов/функций/параметров/QA-правил, онтология BDI v4.1, база знаний опыта |
| **Предмет** | `domain/tnav_client.py`, `assembler.py`, `function_rules.py`, `workflow_renderer.py`, `trajectories.py`, `welltops.py`, `geostat.py`, `irap.py`, `map_render.py`, `tnav_probes.py` | всё, что знает про tNavigator и данные поля |
| **QA/QC** | `domain/qaqc/**` (пакет проверок), `domain/qaqc_adapter.py`, `domain/metacritic.py`, `domain/qc/**` (значения и карты), `agents/checks/**` | оцифрованные проверки, адаптер значений, метакритик, реестр проверок гейтов |
| **Агенты** | `agents/base_agent.py`, `agents/knowledge.py`, `agents/*_policy.py` / `agents/<domain>.py`, `agents/gates.py`, `agents/stage_map.py`, `agents/contracts.py`, `agents/evidence.py`, `agents/decisions.py`, `agents/advisor.py` | решения по этапам, гейты передачи, меморандумы, опыт |
| **Свёртка** | `core/ensemble.py`, `rollup.py`, `metrics.py`, `system_model.py` | ветви ансамбля, метрики, p10/p50/p90, системная модель |
| **Интерфейсы** | `main.py` (CLI), `api.py` (HTTP), `frontend/` | входные точки |

## 3. Поток прогона

```
main.py run ─► Coordinator.run()
  1. _stage_data()              копия data/<поле>/Source рядом с будущим .snp
  2. project_graph()            спека (JSON из YAML-шаблона + данных)
  3. function_rules()/assembler()/builder()   чтение .rdf и шаблонов
  4. stage_mode == staged ─► StageRunner.run_staged()
       для каждого этапа:
         agents/base_agent.BaseAgent.decide()   ← решение агента (данные + БЗ)
         _render_stage() → NN_<gate>.py         ← рендер блока тНава
         client.run_workflow(save=True)         ← исполнение (только при --execute)
         _attach_runtime_evidence()             ← пробники (well_tie/grid/stoiip/property/maps)
         checks.run() + package_evaluate()       ← проверки гейта + пакет QA/QC
         GateEngine.evaluate() → passed|rework|bypassed|skipped|halted|awaiting
         HandoffMemo + KB.remember()             ← передача и опыт
  5. снятие значений модели с ОТКРЫТОГО проекта (до close)
  6. metacritic.evaluate()      диапазоны каталога параметров
  7. ensemble + rollup          ветви, метрики, свёртка
  8. report.json / qaqc.json / qaqc_coverage.json / steps.json / maps/*.png
```

## 4. QA/QC в форме гейтов

Три источника проверок, все — данные:

| Источник | Где | Объём |
|---|---|---|
| Встроенные проверки этапа | `agents/checks/builtin.py`, `contract.py` | геометрия сетки, сшивка скважин, диапазоны, полнота карт, контракт меморандума |
| Оцифрованный пакет | `domain/qaqc/` + `ontology/qa_checks/*.csv` | проверки по блокам чеклиста (02…13) |
| Диапазоны каталога параметров | `domain/metacritic.py` + `data_parameter_catalog.csv` | физические диапазоны значений |

Вердикт гейта детерминированный: `critical`-провал, превышение порогов `min_kq/min_kc`
или `physical == false` → `failed`; политика исчерпания (`best|skip|halt|ask`) решает, как продолжить.
LLM (`agents/advisor.py`) только поясняет находки и не отменяет вердикт.

Три исхода проверки: `passed` / `failed` / `not_applicable` (нет данных) + `unknown`
(правило не формализовано). «Неизвестное ≠ ложь» — отсутствие данных не штрафует модель,
но и не считается успехом.

## 5. Артефакты прогона

```
runs/run_<поле>/
├── report.json            полный отчёт: steps, objects, critics, agents, qaqc, ensemble
├── steps.json             шина шагов (этап → операция → функция → объект → статус)
├── project.json           спека проекта
├── qaqc.json              свёртка QA/QC (kq/kc/fitness/physical/by_block)
├── qaqc_coverage.json     покрытие чеклиста (реализовано / not_applicable+причина / unknown+причина)
├── Structure_modeling.py  воркфлоу целиком
├── agents/
│   ├── stages/NN_<gate>.py     пофайловые этапы
│   ├── gates/<gate>.json       вердикты гейтов
│   ├── handoffs/<NN>.json      меморандумы передачи
│   ├── progress.json           сводка агентного контура
│   └── kb/<agent>.jsonl        опыт агентов этого прогона
└── maps/*.png             карты (нативные объекты Map2d + matplotlib-рендер)
```

Накопительная база знаний — `knowledge/agents/ledger.jsonl` (вне прогонов).

## 6. Расширяемость

* **Новая функция тНава** — триада: `domain/templates/<fn>.txt` + `domain/ontology_rules/<fn>.rdf`
  + блок шага в `ontology_project/<поле>.yaml`. Нет шаблона → шаг `pending_template`, прогон не падает.
* **Новый агент** — наследник `BaseAgent` с `agent_id` (профиль BDI) и `decision()`;
  подключается данными: `agents.required_inputs`, `gates:` (stage → agent → gate),
  `checks.package_blocks` (блок чеклиста → гейт).
* **Новая проверка** — строка в `ontology/qa_checks/*.csv` (ID;Блок;Название;Способ;Порог;
  Входные ключи;Значимость;Формула;Критерий;Фитнес) либо `CheckSpec` в коде — без домена.
* **Новое поле** — `ontology_project/<поле>.yaml` + `data/<поле>/Source/**`; код не меняется.
