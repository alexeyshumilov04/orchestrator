# 03. Агенты: состав, контракты, решения

Базовый класс и БЗ — `docs/02_BASE_AGENT.md`. Здесь — что делает каждый агент,
чем он управляет по данным и какой гейт его закрывает. Все агенты наследуют
`BaseAgent` (`agents/base_agent.py`), объявляют `agent_id` (профиль BDI v4.1) и
реализуют `decision(project, evidence) -> dict`; ни одного доменного значения в коде.

---

## 1. `StructureAgent` — `AG_STRUCTURAL` (`agents/structural.py`)

| Что решает | Откуда данные |
|---|---|
| Рабочий интервал (маркер кровли/подошвы) | `structural.interval_top_marker`, `interval_base_marker` |
| Нужен ли врез/эрозия | покрытие кровли отбивками vs порог `structural.erosion_when_top_coverage_lt`; принудительно `erosion: on/off` |
| План правок (`edits`) и настраиваемые функции (`tunable_functions`) | те же данные + опыт БЗ (`recall/suggest`) |
| Честные пробелы | `unknown`/`missing` из `CoverageReport` |

Решение: `auto` → `coverage < порога` ⇒ врез строится, иначе шаги вреза (`erosion_steps`)
пропускаются как `skipped_by_policy`. Нет отбивок/маркера → врез НЕ строится
(«неизвестное ≠ ложь»). Гейт `G-STRUCT` (стадии 1–3), проверки — блок 04 + `struct.well_tie`,
`struct.well_tie_rmse` (runtime).

Совместимость: `agents/structure_policy.py` — тонкая обёртка (`decide_erosion(project, evidence,
*, cfg=None, kb=None, registry=None, gate_engine=None)`).

## 2. `GridAgent` — `AG_GRID_VOLUMETRICS` (`agents/grid.py`)

| Что решает | Откуда данные |
|---|---|
| Бокс сетки (`min_x/min_y/length_x/length_y`) | extent структурной карты (свидетельство `maps` = статистика irap) |
| Шаг (`step_x/step_y`) | параметры шага сетки в проектном графе |
| Ожидаемые `nx/ny` (+`nz`, если число слоёв объявлено в данных) | бокс/шаг; для `nz` — `grid_expectations.nz` либо `counts_step` шага; иначе `unknown` |
| Включать ли разломы | наличие `inputs.faults` + объекта `Faults`; по умолчанию ВЫКЛ (базовый прогон не меняется) |
| QC-сводка для гейта | соотношения сторон, число ячеек, ожидаемые размеры |

Гейт `G-GRID` (стадии 4–5): `grid.geometry` (critical, runtime), `grid.quality` (major, runtime) + блок 04.
Совместимость: `agents/grid_policy.py` → `decide_grid(...)`.

## 3. `FaciesAgent` — `AG_FACIES` (`agents/facies.py`)

| Что решает | Откуда данные |
|---|---|
| Метод фациального моделирования и **функция тНава** | `geostat.facies_method` + карта «метод → функция» в `ontology/facies_methods.yaml` |
| Число классов, пропорции | `geostat.n_facies`, пропорции по скважинам из отбивок/логов |
| Вариограмма (range/nugget/анизотропия) и согласованность с сеткой | `geostat.*` + `grid_policy.step` |
| Палитра дискретного куба, геотела | `ontology/facies_methods.yaml` (палитра, `geobody`) |

Триады: `grid_property_facies_modeling` (шаг 6.2), `grid_property_create_by_zones`,
`grid_property_create_by_values` (шаблон+правило; в пайплайн НЕ включены — схема `zones_table`
не закрыта), палитра `create_object_template` + `object_template_mapping` (шаги 6.1/6.3),
`geobody_create_by_property` (6.1).
Гейт `G-FACIES` (стадия 6), политика `skip`, проверки — блоки 05/06 + `facies.policy`,
`facies.structure`.

**Статус куба `FACIES` — БЛОКЕР (зафиксирован сырым текстом тНава 26.2):**
```
item 2 ("Facies Modelling (Zones, Regions)")
Error message: Error while launching calculation: Parameter "Grid" (in group "Input") is not specified!
check: FACIES exists = False;  props = zone_id
```
Установлено пробами: `interpolator_type` ∈ {kriging, sgs, grfs} (`sis` отвергнут);
имя аргумента со списком параметров по фациям не найдено (20 кандидатов),
без него задача тНава падает `Fatal error: access violation`; объектные ссылки
`find_object` в элементе воркфлоу тоже роняют задачу. Этап деградирует по политике `skip`,
прогон не рушится. Для снятия блокера нужен GUI-снимок вызова (или точное имя аргумента).

## 4. `PetrophysicsAgent` — `AG_PETROPHYSICS` (`agents/petrophysics.py`)

| Что решает | Откуда данные |
|---|---|
| Метод интерполяции, кубы (LAS → blocked well → куб) | `petrophysics.method`, `petrophysics.cubes` |
| Вариограмма | `petrophysics.variogram` |
| Диапазоны физичности φ/k | `thresholds.poro/perm` |
| Учёт фаций | `ontology/facies_methods.yaml` / `petrophysics` (по данным; беззонная форма интерполяции — проверена) |

Гейт `G-PETRO` (стадия 7), проверки — блоки 07/08/13 + `petro.poro_range`, `petro.perm_range`,
`petro.cubes` (пробники `property_mean`).
Совместимость: `agents/petrophysics_policy.py` → `decide_petrophysics(...)`.

## 5. `SaturationAgent` — `AG_PVT_SCAL` (`agents/saturation.py`)

Контакты (OWC/GOC) из данных: способ задания (по горизонту / по значению), смещение
(`contacts.owc_offset_m`), контроль диапазона `S_w`, суммы насыщенностей, положения контакта
относительно ЗСВ. Гейт `G-SAT` (стадия 8), проверки — блок 09.

## 6. `MapsAgent` — `AG_MAPS` (`agents/maps.py`)

| Что решает | Откуда данные |
|---|---|
| Какие карты строить | `checks.map_files`, `checks.map_kinds` |
| Каким путём: нативный объект `Map2d` + выгрузка / фолбэк matplotlib | маршруты в `domain/qc/maps.py`, источники `checks.map_sources` |
| Чего нет | `missing` с причиной (`checks.map_pending` — вне маршрута) |

Гейт `G-MAPS` (стадия 10), проверка `maps.files` + блоки 07/08.
**Console-safe путь подтверждён пробой** (`tools/probe_maps.py`, tNav 26.2):
`map_2d_create_by_grid_property(grid, continuous_properties=True,
continues_cube_and_map_table=[{use, cube, map_2d, method:"average"}])` → `Map2d`;
`map_2d_export_ascii_format` / `map_2d_export_cps_format` (каталог выгрузки создаётся шагом
через `get_project_folder()`; тНав сам его не создаёт). Ожидаемо 7 нативных PNG
(PORO, PERM, STOIIP, HCPV, PoreVolume, NetVolume, Tl_thick) + фолбэк `U1_top` = 8.
`map_2d_statistic` — схема `maps_table` не подтверждена, триады нет (правило 8).

## 7. `QaRemediationAgent` и `UncertaintyAgent`

* `AG_QA_REMEDIATION` — разбор находок гейтов и маршрутизация исправлений; **не может отменить
  fatal finding** (вердикт детерминированный).
* `AG_UNCERTAINTY` — оси вариаций ансамбля (`variations:` проектного графа), свёртка
  `p10/p50/p90|best` (`core/rollup.py`), выбор ветвей; блок 11 вне объёма этой итерации
  (`out_of_scope` в `ontology/qa_gate_map.yaml`).

## 8. Что агент делает всегда

1. `bind(ctx)` → `observe(evidence)` → `coverage()` → режим (`symbolic/hybrid/generative/abstain`);
2. `decide()` → план и патчи параметров; `validate()` → формальные находки до исполнения;
3. передача — `HandoffMemo` (ревизии артефактов, lineage, QA, evidence hash), запись опыта в БЗ;
4. при провале — `reconsider()`: правка из опыта БЗ, иначе `escalate` (правка не выдумывается).
