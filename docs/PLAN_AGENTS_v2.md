# ПЛАН v2 (согласован): агенты структурных и фациальных построений для 3D-ГГДМ в `orchestrator_v8/`

Согласованные решения заказчика:
1. **Целевой модуль — новый `orchestrator_v8/`** (копия `orchestrator/` v5, без `models/`, `runs/`).
2. **QA/QC — блоки чеклиста 06, 07, 08, 13 + 09, 10** (плюс 05 `QC_GS_*` — фации, ядро задачи).
3. **Приёмка — полный `--execute` с ансамблем 5 ветвей.**
4. **Документация — MD (docs/) + сводный DOCX + PPTX.**
5. **Команда — 6 участников** (foundation, structural, facies, petro, qaqc, verifier).

Жёсткие правила 1–8 — в `docs/AGENT_RULES.md` (обязательны к исполнению).

---

## 1. Базовая линия (проверено на `orchestrator_v8/`)

| Проверка | Результат |
|---|---|
| `tests/test_v5.py` | 32/32 |
| `tests/test_agents.py` | 223/223 |
| `tests/test_base_agent.py` (новый) | 37/37 |
| `tests/test_no_domain_in_code.py` (новый) | зелёный; известный долг 33 позиции (см. `hardcode_audit.known_debt`) |
| `main.py preflight` | `preflight: OK` (тНав 26.2, 1272 операции / 18 стадий / 3257 функций / 6117 QA-правил) |
| `main.py run --field Герасимовское` | `steps.total = 36` (done 35, `skipped_by_policy` 1), `error = 0`, `render_warnings = []`, `pending_template = 0` |

> **Критерий приёмки по шагам.** `steps.total` — НЕ инвариант: он растёт с каждой новой
> триадой (36 → ~41 после E5, плюс шаги карт и фаций). Инварианты: `steps.error = 0`,
> `render_warnings = []`, `steps.pending_template = 0`,
> `steps.done = steps.total − skipped_by_policy` (штатный skip ровно один — шаг вреза).
> Историческая линия «36/35» служит точкой отсчёта для отчёта о дельте.

## 2. Что уже сделано (фундамент, Lead)

* `agents/base_agent.py` — **BaseAgent v2**: BDI-цикл `bind → observe → coverage → decide →
  plan → validate → verify → remember → recall/suggest/reconsider → capabilities`;
  режимы `SYMBOLIC | HYBRID | GENERATIVE | ABSTAIN` (пороги — данные),
  `CoverageReport`, `AgentDecision`, `Capability`; обратная совместимость с v5 сохранена
  (`decide()` возвращает слияние ключей наследника и метаданных цикла).
* `agents/knowledge.py` — **БЗ**: `KnowledgeBase` (журнал опыта JSONL: накопительный
  `knowledge/agents/ledger.jsonl` + внутрипрогонный `runs/<id>/agents/kb/*.jsonl`),
  детерминированные `recall`/`suggest` (медиана удачных наблюдений)/`promote`
  (`candidate → repeatable → approved`); `StaticKnowledge` — онтология BDI v4.1
  (1796 правил решений, 83 правила литературы, схема убеждений).
* `config.yaml` — секции `agents` (policy/kb_dir/required_inputs/recall), `checks.properties`,
  расширенный `checks.package_blocks` (появились G-SAT/G-VOL/G-MAPS), `hardcode_audit`.
* `tests/test_base_agent.py`, `tests/test_no_domain_in_code.py`, `docs/AGENT_RULES.md`, `docs/PLAN_AGENTS_v2.md`.

## 3. Установленные факты (вход для всех этапов)

**QA/QC.** `QAQC/QA_QC_чеклист.xlsx` = 6065 пунктов (23 колонки, 13 блоков).
Оцифровано в `domain/qaqc/` **652** проверки (блоки 02→438, 04→148, 05→40, 13→10, 03→7, 06→7, 14→2).
Реально вычисляемых (не `direct`/`bool` со слагами) — **234**; `fitness_function='да'` — 37.
`kq/kc` формируют только применимые проверки; **418 проверок всегда `not_applicable`**.
Гейты `G-SAT`, `G-VOL`, `G-MAPS` не имели ни одной проверки пакета; `min_kq/min_kc` не заданы;
в отчёт верхнего уровня `qaqc` не попадал никогда (в v5 ветви имели `qaqc = null`, т.к. вызов
стоит внутри `if execute`).

**Блоки чеклиста и объём работы (согласован):**

| Блок | Пунктов | В коде | Что добавляем |
|---|---:|---:|---|
| 05 Куб фаций | 1481 | 40 | `QC_GS_001…006` (вариограмма/анизотропия/число реализаций) + доля коллекторов/NTG |
| 06 Куб литологии | 528 | 7 | `QC_LITH_001…011` (scaleup R², NTG, расчленённость, вариограмма, связанность) |
| 07 Куб пористости | 61 | 0 | `QC_POR_001…010` (осреднение, среднее, гистограммы, min/max, вариограмма, тренд) |
| 08 Куб проницаемости | 69 | 0 | `QC_PERM_001…008` (K-φ, Козени-Карман, Dykstra-Parsons, анизотропия) |
| 13 Петрофизика | 873 | 10 | `QC_PHYS_001/002/005/006` (диапазоны φ, k, Арчи, Козени-Кармана) + сверка с керном/ГИС |
| 09 Куб насыщения | 737 | 0 | `QC_SAT_001…012` (средние, кросс-плот, ВНК, Арчи, переходная зона, S_or) |
| 10 Подсчёт запасов | 86 | 0 | `QC_RES_001…010` (V, PV, S, H, φ, S_w, категории, RF) |

**tNavigator.** Машинный эталон — `reference_workflow.py` (v26.1): 24 элемента, 12 функций.
Из них **без шаблона**: `map_2d_export_cps_format`, `horizon_export_cps_format`,
`marker_export_well_marker_table_format`, `wells_attribute_export`,
`polygon_create_by_map_2d_boundary` — аргументы есть в эталоне (можно писать триады по правилу 8).
**Отсутствует вся ветка «свойство модели → карта → экспорт»** (для карт петрофизики и фаций):
`map_2d_create_by_grid_property` (мануал Designer стр. 1812), `map_2d_create_volumetric_maps`,
`map_2d_statistic`, `map_2d_export_ascii_format`/`_cps_format`, `grid_property_export_gridecl_format`.
Функции фаций, падавшие ранее: `grid_property_facies_by_wells_log_3d` (нужен готовый дискретный
куб `FACIES`; внутри туториала он уже есть) — заменяется на **`grid_property_facies_modeling`**
(сама создаёт куб, сигнатура из `tools/probe_facies_modeling.py`, прогоном **не подтверждена**)
или на `grid_property_create_by_zones` (создаёт свойство сразу с дискретным шаблоном;
схема `zones_table` **не закрыта** — открытый вопрос).
Петрофизика: `grid_property_interpolate_by_wells_log_3d` в «беззонной» форме
(`ZoneRegionFilter(zone=None)`, `ZoneRegionParameters(use=True, zone=None)`) — **проверена**
(README v7), но с `use_zone=True, zone=FACIES` PORO не создавался.

## 4. Архитектура (кратко)

```
ДАННЫЕ: ontology/ (+qa_checks/*.csv, qa_gate_map.yaml) · ontology_project/*.yaml
        domain/templates/*.txt · domain/ontology_rules/*.rdf · config.yaml
   │ читается как данные
ДОМЕН:  tnav_client · assembler · function_rules · workflow_renderer · trajectories · welltops
        geostat · irap · map_render · tnav_probes · qaqc/ (пакет проверок)
        qc/ НОВОЕ: probes (снять значения с проекта) · values (DataContext) · maps (экспорт карт)
ЯДРО:   coordinator · planner · pipeline · ensemble · rollup · metrics · llm_gateway
АГЕНТЫ: BaseAgent v2 + knowledge.py + capabilities + registry + stage_map + gates + checks/
        Structural · Grid · Facies · Petrophysics · Saturation · Volumetrics · Maps · QA-Remediation
АРТЕФАКТЫ: runs/<id>/{agents/{stages,gates,handoffs,kb},qaqc.json,qaqc_coverage.json,maps/*.png,report.json}
```
Зависимости только вниз: `agents → core → domain → данные`.

## 5. Этапы (E) и владельцы

| Этап | Содержание | Владелец | Приёмка |
|---|---|---|---|
| **E0** | правила + аудит хардкода | Lead | сделано (долг 33 → цель 0) |
| **E1** | BaseAgent v2 + БЗ + тесты | Lead | сделано (37/37) |
| **E2** | реестр проверок ИЗ ДАННЫХ: `ontology/qa_gate_map.yaml`, `CheckRegistry` из CSV, `qaqc` в отчёт + kq/kc + `min_kq/min_kc` по гейтам (не ломая dry-run) | `foundation` | `report.json → qaqc` заполнен; `test_agents` 223/223 |
| **E3** | слой значений и пробников `domain/qc/` (свойства, статистики, пропорции фаций, контакты, объёмы) | `qaqc` + `petro` | проверки блоков 07/08/13 применимы на реальном прогоне |
| **E4** | оцифровка проверок 05/06/07/08/13 + 09/10 в `ontology/qa_checks/*.csv`; `qaqc_coverage.json` по 6065 пунктам | `qaqc` | применимых проверок ↑, `unknown` сохраняется |
| **E5** | структурный агент v2: интервал, врез, горизонты, толщины, разломы; триады экспорта из эталона | `structural` | dry-run без регресса; `struct.*` не деградирует |
| **E6** | агент сетки/апскейлинга: бокс, шаг, слои, QC ячеек, апскейлинг ГИС | `structural` | `grid.geometry/quality` = passed |
| **E7** | фациальный агент: куб `FACIES` (дискретный шаблон!), пропорции, вариограммы, геотела | `facies` | на `--execute` куб `FACIES` создан |
| **E8** | петрофизический агент: кубы `PORO`/`PERM` по фациям, диапазоны, связь K-φ | `petro` | кубы созданы, `petro.*` passed |
| **E9** | агент карт: `map_2d_create_by_grid_property` + console-safe экспорт + matplotlib PNG; карты структуры/толщин/фаций/петрофизики | `petro` (maps) | ≥8 карт в `runs/<id>/maps/` |
| **E10** | насыщение/волюметрия/ансамбль: гейты G-SAT/G-VOL, блоки 09/10 | `qaqc` + Lead | свёртка p10/p50/p90 невырождена |
| **E11** | независимая верификация: тесты, dry-run, `--execute` 5 ветвей, аудит хардкода, соответствие чеклисту | `verifier` | отчёт `docs/VERIFY_*.md` |
| **E12** | документация: архитектура, каждый агент, онтология, QA/QC, результаты | Lead + все | `docs/*.md` + DOCX + PPTX |

## 6. Области записи (не пересекаются)

| Участник | Пишет только в |
|---|---|
| `foundation` | `agents/contracts.py`, `registry.py`, `stage_map.py`, `gates.py`, `checks/**`, `tests/test_contracts.py`, `ontology/qa_gate_map.yaml` |
| `structural` | `agents/structural.py`, `agents/grid.py`, `tests/test_structural_agent.py`, `domain/templates/{horizon_*,map_2d_thickness_map,wells_attribute_*,marker_export_*,polygon_create_by_map_2d_boundary,fault_*}.txt`, одноимённые `domain/ontology_rules/*.rdf` |
| `facies` | `agents/facies.py`, `tests/test_facies_agent.py`, `domain/templates/{grid_property_facies_*,grid_property_create_by_zones,grid_property_calculator,geobody_create_by_property,blocked_well_log_change_type,create_blocked_well_log}.txt` + их `.rdf` |
| `petro` | `agents/petrophysics.py`, `agents/saturation.py`, `agents/maps.py`, `domain/qc/probes.py`, `domain/qc/maps.py`, `tests/test_petro_agent.py`, `domain/templates/{grid_property_interpolate_by_wells_log_3d,grid_property_change_type,map_2d_create_by_grid_property,map_2d_export_*,grid_property_export_*,map_2d_statistic,contact_create_by_horizon}.txt` + их `.rdf` |
| `qaqc` | `ontology/qa_checks/**`, `domain/qaqc/**` (данные+генератор), `domain/qc/values.py`, `agents/checks/adapters.py`, `tests/test_qaqc_checks.py` |
| `verifier` | `tests/test_verify_*.py`, `docs/VERIFY_*.md` (только своё) |
| **Lead (общий писатель, один за раз)** | `agents/base_agent.py`, `agents/knowledge.py`, `core/**`, `agents/runner.py`, `config.yaml`, `ontology_project/gerasimovskoe.yaml`, `main.py`, `README.md`, `docs/*` (кроме VERIFY/qa_checks) |

## 7. Открытые вопросы (решаются по правилу 8, не догадкой)

1. Схема `zones_table` для `grid_property_create_by_zones` — не найдена (быстрый путь: один раз
   в GUI тНава «Создать свойство по зонам» → скопировать вызов).
2. Сигнатура `grid_property_facies_modeling` — из проб, прогоном не подтверждена (противоречие
   README v7 ↔ `B4_facies.md`).
3. `use_zone=True, zone=<куб зон>` для петрофизики по фациям: в v7 PORO не создавался —
   подтвердить или откатить на беззонную форму.
4. Console-safe карты: нативный `create_screenshot` в консоли недоступен → путь
   `map_2d_create_by_grid_property` + `map_2d_export_*` + matplotlib; требуется проба на лицензии.
5. Состояние API тНава («Задача уже завершена») при зависших `tNavigator*.exe` — перед
   `--execute` проверять отсутствие зависших процессов.
