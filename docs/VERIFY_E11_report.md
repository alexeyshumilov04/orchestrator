# VERIFY E11 — независимая верификация `orchestrator_v8/`

**Верификатор:** teammate `verifier` (task-6). Код прототипа не писал, чужой код не правил
(зона записи: `tests/test_verify_*.py`, `docs/VERIFY_*.md`).
**Замороженный прогон (приёмка dry-run):** 2026-10-09, 18:54 (после него файлы
`agents/ core/ domain/ tests/ ontology/ ontology_project/ config.yaml main.py` не менялись до
снятия заморозки).
**Реальный прогон `--execute`:** выполнен Lead-ом 18:59; артефакты дополнительно проверены в
19:02–19:04 (раздел 11). Итог: **частичное подтверждение с точной причиной** —
E7 и E10 не подтверждены, E9 с замечанием; на текущем дереве дополнительно падает
`tests/test_agents.py` (F-16).

Эталон проверки — `orchestrator_v8/docs/AGENT_RULES.md` (правила 1–8) и
`orchestrator_v8/docs/PLAN_AGENTS_v2.md`. Машинный эталон — `domain/ontology_rules/reference_workflow.py`.

---

## 0. Инструменты верификатора (моя зона: `tests/test_verify_*.py`, `docs/VERIFY_*.md`)

| Файл | Что делает |
|---|---|
| [test_verify_chain.py](../tests/test_verify_chain.py) | Прогон обязательных тестов и тестов участников, pytest-пересчёт, `main.py preflight`, dry-run и инварианты отчёта, чужые токены в рендере, аудит артефактов `--execute` (`--from-artifacts`) |
| [test_verify_triads.py](../tests/test_verify_triads.py) | Правило 2 (template + rdf + блок YAML), правило 8 (источник шаблона: AST-разбор эталона, корпус v7/v8 + воркфлоу-туториалы тНава + отчёты проб, «новый шаблон без источника» = FAIL, ложная ссылка на эталон, сверка аргументов), правило 4 (bottom-first) |
| [test_verify_hardcode.py](../tests/test_verify_hardcode.py) | Правило 1 независимо от `test_no_domain_in_code.py`: токены из ВСЕХ значений проектного YAML + `domain_tokens` + `foreign_tokens`; скан `agents/ core/ domain/` (включая `domain/qaqc/`), мёртвый долг, рост `known_debt`, пороги в коде, ключи данных, которые никто не читает |
| [test_verify_rule6.py](../tests/test_verify_rule6.py) | Правило 6: `except: pass/continue`, подстановка нуля, `evaluate({})` и `CheckRegistry` на пустых данных, ABSTAIN агентов |
| [test_verify_qaqc_checklist.py](../tests/test_verify_qaqc_checklist.py) | Сверка оцифрованных проверок с `QAQC/QA_QC_чеклист.xlsx` (ID + числовые пороги), обязательный набор `QC_*`, исполняемость пакета (`CHECKS`), аудит `runs/<id>/qaqc_coverage.json` (per-block и per-item) |
| [test_verify_manual_citations.py](../tests/test_verify_manual_citations.py) | Правило 8: независимая сверка цитат мануала Дизайнера 26.2 (4093 стр.) с самим PDF (`pymupdf`) |

Доказательства: [VERIFY_baseline_manifest.md](VERIFY_baseline_manifest.md) (SHA256 базового
состояния — git-истории для `orchestrator_v8/` нет), [VERIFY_chain_run.md](VERIFY_chain_run.md)
(сырой прогон цепочки), [VERIFY_tool_outputs.md](VERIFY_tool_outputs.md) (сырые выводы всех
аудитов), [VERIFY_run_stdout.md](VERIFY_run_stdout.md) (хвост dry-run).

## 1. Что проверено и ПОДТВЕРЖДЕНО (замороженный прогон 18:54)

| Проверка | Команда | Результат |
|---|---|---|
| База v5 | `python -X utf8 tests/test_v5.py` | `пройдено: 32 | провалено: 0` |
| Агенты | `python -X utf8 tests/test_agents.py` | `всего: 223 | провалено: 0` |
| BaseAgent | `python -X utf8 tests/test_base_agent.py` | `всего: 39 | провалено: 0` (база была 37 — Lead расширил контракт facies-агента) |
| Аудит хардкода (офиц.) | `python -X utf8 tests/test_no_domain_in_code.py` | `пройдено: 4 | провалено: 0` |
| Тесты участников | 5 файлов | `test_contracts` 90/0, `test_qaqc_checks` 55/0, `test_structural_agent` 69/0, `test_facies_agent` 44/0, `test_petro_agent` 48/0 |
| pytest-пересчёт | `python -m pytest -q tests/test_v5.py tests/test_agents.py` | `42 passed in 54.65s`, скрытых ошибок импорта нет |
| preflight | `python -X utf8 main.py preflight` | `preflight: OK` |
| dry-run | `python -X utf8 main.py run --field Герасимовское` | `total=49, done=48, error=0, pending_template=0, skipped_by_policy=1, render_warnings=[]` |
| инварианты | отчёт | `done = total − skipped_by_policy` (48 = 49 − 1); `begin_wf_item=48` = done; чужых токенов обучения в рендере нет |
| QA/QC в отчёте | `report.json → qaqc` | `total=712, passed=0, failed=0, not_applicable=705, unknown=7, kq=0.0, kc=0.0, physical=null` |
| Покрытие чеклиста | `runs/run_Герасимовское/qaqc_coverage.json` | `checklist_items=6065`; `points.by_status={implemented:288, not_applicable:417, unknown:5360}`; 195 вне-блочных пунктов — построчно `unknown`, причина R4 |
| Гейты (dry-run) | `runs/<id>/agents/gates/*.json` | `physical=null` во всех; `passed`: G-DATA, G-FACIES, G-PETRO; `pending_execution`: G-STRUCT, G-GRID, G-SAT, G-VOL, G-MAPS |

Регресса против базовой линии нет: `error=0`, `render_warnings=[]`, `pending_template=0`,
`done = total − skipped`. Рост `steps.total` (36 → 49) — это E5/E7/E9 (новые шаги с
шаблонами и правилами), а не дефект: `pending_template=0`.

## 2. Что НЕ подтверждено

1. **Реальный прогон `--execute`** — не выполнялся на момент отчёта. Поэтому НЕ подтверждены:
   статусы стадий реального прогона, фактическое создание кубов `FACIES`/`PORO`/`PERM`,
   ≥8 PNG в `runs/<id>/maps/`, `grid.geometry/quality`, сходимость с отбивками, qaqc с
   реальными значениями, невырожденность свёртки p10/p50/p90. Статус: **не проверено**
   (после запуска Lead-ом аудит выполняется командой
   `python -X utf8 tests/test_verify_chain.py --from-artifacts` — прогон не запускает,
   проверяет `tnav.ok` по ветвям, наличие `models/<vid>/Герасимовское.snp`, карт и qaqc ветвей).
2. Транзиентные состояния во время работы участников (см. F-15) — сняты на замороженном срезе.

## 3. Реестр находок (все проверены повторно на замороженном срезе)

| # | Правило | Файл:строка | Суть | Итоговый статус |
|---|---|---|---|---|
| F-01 | 1 | `agents/checks/builtin.py`, `agents/runner.py`, `core/coordinator.py`, `core/ensemble.py` | Доменные литералы в коде (`PORO/PERM/STOIIP/Welltop.txt/main_grid/S001/«базовая»`) | **закрыто**: незадекларированных литералов 0; метрика/варианты/пути читаются из данных (`project.stoiip_candidates`, `ensemble.metric`, `ensemble.default_variant`); остаток 14 совпадений — в `known_debt` |
| F-02 | 1 | `config.yaml hardcode_audit.known_debt` | Долг вырос 26 → 36 позиций в ходе работы | **закрыто**: финально **24 позиции < 26 (базовой линии)**, мёртвых позиций 0 |
| F-03 | 1 | `agents/gates.py:201` | Код читал несуществующий ключ `checks.min_applicable_checks` → предохранитель применимости был мёртв (`applicable_requirement()==1`) | **закрыто**: ключ данных согласован с кодом, рантайм-проба → `5` для всех гейтов |
| F-04 | 6 | `agents/gates.py:240` | `bool(metrics.get("physical", True))` — «физично» без данных | **закрыто по существу**: `core/coordinator.py:483` → `if qaqc.physical is False:`; `qaqc.physical=null`, у всех гейтов `physical=null`. **Замечание:** сама строка `gates.py:240` осталась (дефолт в `GateVerdict`) |
| F-05 | 6 | `domain/qaqc_adapter.py` | `physical=True` при нуле применимых проверок | **закрыто**: `evaluate({}) → physical=None` |
| F-06 | 2 | `ontology_project/gerasimovskoe.yaml` | Неполная триада `polygon_create_by_map_2d_boundary` | **закрыто**: шаблон + правило + блок созданы |
| F-07 | 8 | `domain/templates/` | Функции эталона без триады | **закрыто для 5 из 6** (см. раздел 4); остался `marker_create_by_horizon` — WARN, не требование задания |
| F-08 | 2 | `runs/<id>/qaqc_coverage.json` | Блоки 07/08/09/10: `not_implemented` при `implemented>0` | **закрыто**: `partial` + причина «оцифровано N из M пунктов» |
| F-09 | 2 | `runs/<id>/qaqc_coverage.json` | 195 пунктов вне блоков без построчного статуса | **закрыто**: `meta.items_outside_blocks_detail` — 195 записей (ID, `unknown`, R4) |
| F-10 | 6 | `domain/qaqc/checks_table.csv` / `domain.qaqc.CHECKS` | 714 строк CSV / 707 исполняемых | **закрыто как обоснованное**: 7 — `DESCRIBED_ONLY` (качественный критерий), `unknown` с причиной, не `passed` |
| F-11 | — | `tests/test_qaqc_checks.py` | Промежуточный провал 18:44 | **закрыто**: 55/55 |
| F-12 | 1 | `config.yaml: workflow.transitions` | Ключ данных не читается ни одним модулем | **принято как известное ограничение** (наследие: ДАННЫЕ для генератора спеки, в staged-контуре не используется) |
| F-13 | — | `domain/qaqc/parameters.py` | Наследованный сгенерированный файл (идентичен в `orchestrator/` и v7); 5 доменных токенов не выводятся из CSV пакета; исходная книга/генератор отсутствуют | **пробел наследия**, не дефект нового кода |
| F-14 | — | `runs/<id>/agents/kb/*.jsonl` | Запись опыта агентов | **закрыто**: 6 файлов по агентам + `knowledge/agents/ledger.jsonl` (1092 записи); поля `verdict/outcome/functions/parameters/metrics/evidence_hash/plan_hash/provenance` есть |
| F-15 | 3 | `render_warnings` | Транзиентные `render_warnings` на `grid_property_facies_modeling` во время правок | **снято на замороженном срезе**: `render_warnings=[]` |
| F-16 | 3 + DoD | `agents/runner.py:167` + `tests/test_agents.py` (FakeTnav) | `client.project_path()` — у `FakeTnav` метода нет → `tests/test_agents.py` падал исключением (pytest `1 failed, 41 passed`); DoD «test_agents 223/223» и правило 3 были нарушены | **закрыто 19:05**: добавлен guard `getattr(client, "project_path", None)` (`agents/runner.py:167-176`); проверено мной в 19:09 — `test_agents` **223/0**, pytest по `test_v5+test_agents` — **42 passed** |
| F-17 | — (процесс) | `runs/run_Герасимовское/report.json` | Первичный артефакт реального прогона (18:59) перезаписан dry-run'ами 19:01:26 и 19:03:22 → `tnav.ok=False`, текст ошибки и агрегат qaqc реального прогона в артефактах не сохранились | **ОТКРЫТО**: снимать копию `report.json` сразу после `--execute` (или писать execute-отчёт отдельно) |
| F-18 | — (E9) | `runs/run_Герасимовское/maps/STOIIP.txt` | Экспорт STOIIP **пустой: 0 из 77 500 ячеек**, `STOIIP.png` нет; при этом свойство посчитано (`vol.stoiip` = 2.039e+08) → дефект выгрузки STOIIP. Остальные 7 карт содержат реальные данные (53 % ячеек: φ 0.09–0.11, k 1.5–1.9 мД, толщина ≈26 м) | **ОТКРЫТО** (уточнено: волюметрия считается, пуста именно карта STOIIP) |
| F-19 | 6 | `config.yaml gates`, `runs/<id>/agents/gates/G-FACIES.json`, `G-MAPS.json`, `G-SAT.json` | **Гейт неполон**: `G-FACIES` = passed при `applicable=0` и отсутствии куба (в данных у G-FACIES/G-DATA/G-SAT `evidence` пусто); `G-MAPS` = passed, хотя его major-чек `maps.files` = False (гейт проверен в 19:11:18, PNG появились 19:11:21–34); `G-SAT` = passed без findings | **закрыто в коде (19:2x), подтверждено независимо**: в данных `ontology/qa_gate_map.yaml → result_checks` объявлены 7 проверок результата, все зарегистрированы в реестре, собранном ИЗ ДАННЫХ (742 проверки); пустое свидетельство → `state=unverified` и **гейт `pending_execution`** (не `passed`), `unverified` перечислен; «куба нет в `grid_properties`» → `facies.cube_exists` failed; «куб есть, но пуст» → `facies.cube_nonempty` failed; все места учёта unverified обработаны явно (`base.py:773`, `report.py:183`, `contracts.py:75`). Остаётся подтвердить на `--execute` №3 (ожидание: `G-FACIES` не `passed` без куба) |
| F-20 | 8/2 | `ontology_project/gerasimovskoe.yaml` (стадия 6), `domain/ontology_rules/grid_property_facies_modeling.rdf` | Неподтверждённый шаг включён в пайплайн и роняет весь воркфлоу (база — item 1, ветви — item 29 `Parameter "Grid" … is not specified!`) вместо `skipped_by_policy`; правило честно фиксирует «полного подтверждения прогоном НЕТ» | **закрыто**: шаг 29 → `skipped_by_policy` с причиной «сигнатура не подтверждена пробой (workflow.unconfirmed_steps, правило 8)», база `tnav.ok=True` |
| F-21 | 3 | `runs/<id>/steps.json` | Неподтверждённый facies-шаг имел статус `done` и исполнялся, роняя прогон; `begin_wf_item` ≠ `done` | **закрыто** (прогон №4: база `ok=True`, `begin_wf_item = done = 46`) |
| F-22 | 3 | `core/coordinator._build_ensemble` | Skip-решения staged-ветки не применялись в ансамбле: ветка рендерила 48 блоков и падала на `geobody` («cannot find object Property "FACIES"») → `scored=0` | **закрыто**: ветви получают `available_objects` базового прогона и пропускают шаги так же; в прогоне №5 все 5 ветвей `ok=true`, `scored=5`, `best=S004` |
| F-23 | 3 | `runs/<id>/steps.json` (шаг 29) | Причина пропуска шага 29 дублировала текст вреза (несоответствие сообщения шагу) | **закрыто**: причина стала собственной и корректной |
| F-24 | 8 (E10) | `ontology_project/gerasimovskoe.yaml variations.S005` | Вариация S005 адресует `map_2d_interpolate`, **которой нет в пайплайне** → ветка S005 бит-в-бит равна S001 (одинаковый SHA воркфлоу и метрика до последнего знака) → из 5 ветвей различимы 4 | **ОТКРЫТО**: либо включить функцию в пайплайн, либо перенацелить вариацию; независимая проверка добавлена в `tests/test_verify_triads.py` (раздел H) |

Нарушений правил 1–8 на замороженном срезе **не обнаружено**; остаются два замечания
(F-04 `gates.py:240`, F-12 `workflow.transitions`) и один пробел наследия (F-13).

## 4. Аудит триад (правило 2), источников (правило 8) и правила 4

Замороженный срез: шаблонов **42**, правил **42**, объявленных в YAML функций **30**,
из них **НОВЫХ шаблонов 10**. `python -X utf8 tests/test_verify_triads.py` →
**FAIL 0, WARN 6**; вложенный рендер тем же кодом, что у координатора: **49 шагов,
`builder.warnings == 0`**.

* **Триады** полные у всех объявленных функций; обратных сирот (шаблон без правила /
  правило без шаблона) нет.
* **Правило 4 (bottom-first)** проверено через данные: по `structural.interval_top_marker=BAJ`
  и `interval_base_marker=J2` определены `U1_top`/`U1_bot`, затем `horizons_table` шаблона
  с применением `replace` шага → `['Top','Bot'] → ['U1_bot','U1_top']` — **снизу вверх, OK**.
* **Аргументы vs машинный эталон (AST)**: у функций эталона пропущенных аргументов нет;
  «лишние» — вложенные `obj_name/obj_type`, `well_filter_*` (разные конструкторы объекта)
  и осознанные добавления в НОВЫХ шаблонах (`marker`, `use`, `attribute_name`).
* **Источники 10 новых шаблонов подтверждены**, в т.ч.:
  * `map_2d_create_by_grid_property` — воркфлоу, сгенерированный самим тНавом 26.2
    (`C:\Program Files\tNavigator\26.2\tutorials\GM1.1_...\Geomechanics_workflow.py` — файл
    существует, функция найдена);
  * `map_2d_export_ascii_format` / `_cps_format` — отчёты живых проб `_probe_maps4/5.txt`;
  * `grid_property_create_by_zones/_values/_facies_modeling` — мануал Дизайнера 26.2
    (цитаты сверены с PDF, см. 4.1).
* **Ложных ссылок на машинный эталон нет**: где функции нет в `reference_workflow.py`,
  комментарий содержит честную оговорку «сигнатура НЕ из машинного эталона».

### 4.1. Независимая сверка цитат мануала с PDF (`pymupdf`, 4093 стр.)

`python -X utf8 tests/test_verify_manual_citations.py` → проверено 5 цитат, **FAIL 0**
(1 не найдена — это цитата отчёта пробы, а не мануала; помечена WARN).

| Шаблон/правило | Цитата | Найдено в PDF | Заявлено | Вывод |
|---|---|---|---|---|
| `grid_property_create_by_zones` | «Создать свойство по таблице зон», «позволяет создать зоны по Z» | стр. 2733 (и 42/2564/2731) | 2733–2734 | подтверждено |
| `grid_property_create_by_values` | «Создать свойство по таблице значений» | стр. 2734 (и 42/2564/2731) | 2734 | подтверждено |
| `grid_property_facies_modeling` | «Фациальное моделирование (Зоны, Регионы)», «позволяет создать ДИСКРЕТНОЕ свойство по объекту» | стр. 2580/2581 (и 41/2563) | 2581 | подтверждено |
| `map_2d_create_by_grid_property` | «41.3.6 2D-Карта по кубу свойств» | стр. 1812–1814 | 1812 | подтверждено |

## 5. Аудит QA/QC (правило 6, блоки 05–13)

`python -X utf8 tests/test_verify_qaqc_checklist.py` → **FAIL 0, WARN 0**.

* Оцифровано по блокам: **05 — 6, 06 — 11, 07 — 10, 08 — 8, 09 — 12, 10 — 10, 13 — 5**
  (все обязательные `QC_*` из задания есть и все найдены в чеклисте ГПН).
* **Пороги**: сверено 46 проверок (числа из колонки «Критерий прохождения» чеклиста против
  «Порог»/«Критерий» CSV) — **расхождений 0**.
* **Исполняемость**: 707 из 714 проверок каталога; 7 — `DESCRIBED_ONLY` (качественный
  критерий, исполнимой метрики нет) → `unknown` с причиной, **не `passed`**.
* **Покрытие**: 6065 пунктов; `points.by_status = implemented 288 / not_applicable 417 /
  unknown 5360`; `items_outside_blocks_detail` — 195 записей с ID, статусом `unknown` и
  причиной R4; `by_type` сходится (33+100+3+5+54=195); 5870+195=6065.
* **Ничего не помечено пройденным без данных**: `checks_passed=0`, `checks_failed=0`.

## 6. Аудит «неизвестное ≠ ложь» (правило 6)

`python -X utf8 tests/test_verify_rule6.py` → **FAIL 0** (36 WARN — легитимные
прогресс/колбэк-обёртки).

* Молчаливое глушение: 36 мест `except → pass/continue`; **ни одно не является последним
  оператором функции** (результат не теряется без фолбэка).
* `evaluate({})`: `total=593, passed=0, failed=0, not_applicable=593, physical=None` — верно.
* `CheckRegistry.run(gate, {})` по всем 8 гейтам: **ни одного вердикта без данных**.
* Агенты без входов → `ABSTAIN` (`StructuralAgent`: `mode=abstain`,
  `missing=['structural','welltops']`).
* Гейты dry-run: «не проверялось» отличается от «пройдено» (`pending_execution` + `physical=null`).

## 7. Аудит хардкода (правило 1)

`python -X utf8 tests/test_verify_hardcode.py` → **FAIL 0**.

* Независимый (более широкий, чем официальный) набор токенов: незадекларированных доменных
  литералов в `agents/core/domain` — **0**; `known_debt` — **24 позиции (ниже базовых 26)**;
  мёртвых позиций долга — 0.
* `domain/qaqc/**` (официальным тестом исключён целиком): 38 совпадений домена, из них
  **33/38 (87 %) дословно присутствуют в исходных CSV пакета** — производные данные;
  остаток — наследованный `parameters.py` (F-13).
* Мёртвых ключей данных: `workflow.transitions` (F-12, известное ограничение).
* Проверка «ключи данных, которые никто не читает» нашла F-03 (исправлено).

## 8. Вердикты по этапам E2…E10 (предварительные, по dry-run-срезу 18:54)

> **Итоговые вердикты — в разделе 11.3** (после реального прогона): E7 и E10 не подтверждены,
> E9 — с замечанием (STOIIP пуст, карт 7 при требовании ≥8). Таблица ниже показывает, что
> дал dry-run-срез.

| Этап | Содержание | Вердикт | Обоснование |
|---|---|---|---|
| **E2** | реестр проверок из данных, `qaqc` в отчёте, пороги гейтов | **принято с замечаниями** | `report.json → qaqc` заполнен (712/0/0/705/7, kq/kc/fitness, `physical=null`); `qaqc_coverage.json` есть; `test_contracts` 90/90. Замечания: `min_kq/min_kc` в данных **осознанно не заданы** (эффект нулевой; при задании деградировали бы гейты из-за неполноты QA/QC) — предохранитель `checks.min_applicable_checks=5` проверен рантайм-пробой; остаётся дефолт `physical=True` в `agents/gates.py:240` |
| **E3** | слой значений и пробников `domain/qc/` | **принято с замечаниями** | `domain/qc/values.py`, `probes.py`, `maps.py` есть; «нет данных → not_applicable» соблюдено (705). Замечание: применимость проверок блоков 07/08/13 на реальных значениях доказывается только `--execute` |
| **E4** | оцифровка проверок + `qaqc_coverage.json` | **принято** | 62 `QC_*` оцифрованы (55 исполняемых + 7 `DESCRIBED_ONLY` с причиной); пороги — 0 расхождений на 46 проверках; покрытие 6065 полное, per-block и per-item, причины у `unknown`/`not_applicable` |
| **E5** | структурный агент, триады экспорта | **принято** | `agents/structural.py` + `grid.py`; 5 триад из эталона (шаблон+правило+блок); триады FAIL 0; правило 4 (bottom-first) подтверждено; `test_structural_agent` 69/69 |
| **E6** | агент сетки/апскейлинга | **принято с замечаниями** | `agents/grid.py` + политика, решение по боксу/шагу/слоям/разломам из данных; в dry-run G-GRID `pending_execution` — QC сетки (geometry/quality) подтверждается только реальным прогоном |
| **E7** | фациальный агент, куб `FACIES` | **принято с замечаниями** | `agents/facies.py` + `facies_policy.py`; карта «метод → функция» в данных (`ontology/facies_methods.yaml`); триады `grid_property_facies_modeling`/`create_by_zones`/`create_by_values` + палитра/геотела; рендер без warnings; `test_facies_agent` 44/44. Замечание: создание дискретного куба `FACIES` не подтверждено реальным прогоном |
| **E8** | петрофизика `PORO/PERM` | **принято с замечаниями** | `agents/petrophysics.py`, `saturation.py`, `maps.py`; кубы/диапазоны/метод — из данных; `test_petro_agent` 48/48. Замечание: наличие кубов `PORO`/`PERM` в проекте — только после `--execute` |
| **E9** | карты свойств и фаций (≥8 PNG) | **принято с замечаниями** | console-safe путь документирован и подтверждён источниками (туториал-воркфлоу тНава 26.2 + отчёты проб + мануал 41.3.6 стр. 1812 — цитата сверена с PDF); в dry-run построен 1 PNG (matplotlib-фолбэк). Замечание: ≥8 карт в `runs/<id>/maps/` — только после `--execute` |
| **E10** | насыщение/волюметрия/ансамбль | **не подтверждено (ожидает `--execute`)** | В отчёте 5 ветвей, но в dry-run метрика/qaqc ветвей = `null` (это корректно: нет модели). Свёртка p10/p50/p90 и гейты G-SAT/G-VOL в `pending_execution` — подтверждаются только реальным прогоном |

## 9. Сырые выводы команд

* [VERIFY_chain_run.md](VERIFY_chain_run.md) — полный вывод `tests/test_verify_chain.py`
  на замороженном срезе (тесты, pytest, preflight, dry-run, инварианты).
* [VERIFY_tool_outputs.md](VERIFY_tool_outputs.md) — полные выводы `test_verify_triads`,
  `test_verify_hardcode`, `test_verify_rule6`, `test_verify_qaqc_checklist`,
  `test_verify_manual_citations` (все exit=0).
* [VERIFY_baseline_manifest.md](VERIFY_baseline_manifest.md) — базовые SHA256.

## 10. Итог приёмки (замороженный dry-run-срез 18:54)

**Правила 1–8 на срезе 18:54: нарушений не найдено.** Подтверждено:
правило 1 (0 незадекларированных литералов, долг 24 < 26, мёртвых 0), правило 2 (триады
полные), правило 3 (`error=0`, `render_warnings=[]`, `pending_template=0`,
`done=total−skipped`, тесты зелёные), правило 4 (bottom-first), правило 6
(`physical=null`, `not_applicable` вместо `failed`, ABSTAIN), правило 7 (чужих токенов в
рендере нет; беззонная форма `ZoneRegionFilter(zone=None)`/`ZoneRegionParameters(use=True)`
есть в шаблонах интерполяции и фаций), правило 8 (источники 10 новых шаблонов подтверждены,
цитаты мануала сверены с PDF).

**Правило 5** (прогон с чистого проекта) подтверждено по коду:
`core/coordinator.py:302-307` удаляет старый `<field>.snp`/`.snf` перед реальным прогоном,
ветки ансамбля пересоздаются (`coordinator.py:455`).

## 11. Реальный прогон `--execute`: что удалось проверить независимо

После снятия заморозки Lead выполнил `--execute` (18:59), затем дерево продолжало меняться
(правки шаблонов экспорта 18:59:59/19:00:08, правки `agents/runner.py`, повторные dry-run'ы
19:01:26 и 19:03:22). Поэтому ниже — разделение на **проверенное мной по артефактам** и
**сообщённое Lead-ом** (первичный `report.json` реального прогона перезаписан, см. F-17).

### 11.1. Проверено мной по сохранившимся артефактам

| Факт | Доказательство |
|---|---|
| **Консольный путь карт работает на живой лицензии**: 7 PNG построены реальными данными | `runs/run_Герасимовское/maps/` (19:02–19:03): `PORO.png`, `PERM.png`, `HCPV.png`, `PoreVolume.png`, `NetVolume.png`, `Tl_thick.png`, `U1_top.png` + одноимённые `.txt`/`.cps` (irap CPS/ASCII, ~1 МБ); PORO.png проверен визуально — карта пористости φ 0.00–0.12 с изолиниями и контуром модели |
| Экспортированные карты содержат РЕАЛЬНЫЕ значения (не бланк) | PORO: 53.1 % ячеек непустые (0.093…0.108); PERM 53.1 % (1.5…1.9 мД); HCPV/PoreVolume/NetVolume 52.9–53.1 %; Tl_thick 53.3 % (≈26 м) |
| **STOIIP пуст** | `maps/STOIIP.txt`: 0 из 77 500 ячеек непустых; `STOIIP.png` отсутствует → из 8 ожидаемых (`checks.map_files`) построено 7 (F-18) |
| Реальные QA/QC-метрики стадий записаны в БЗ | `knowledge/agents/ledger.jsonl` (UTC 15:56–16:03): стадии 1–3 `applicable=17, kc=0.1875, kq=0.0, fitness=0.09375, not_applicable=131, physical=0.0, physical_known=1.0`; исходы: стадии 1–3 `degraded`, остальные `passed` |
| Ветки ансамбля реально создавались | `models/S001/Герасимовское.snp` + `.snf`, `models/S002/…snp` + `.snf` существуют |
| Дефект `import` в шаблоне устранён | В `domain/templates/map_2d_export_cps_format.txt` и `_ascii_format.txt` (18:59:59/19:00:08) инструкции `import` больше нет; в отрендеренных `models/S00x/Structure_modeling.py` (19:00:42) **0 импортов** внутри `begin_wf_item`; комментарий шаблона теперь: каталог `Maps` создаёт ОРКЕСТРАТОР |

### 11.2. Сообщено Lead-ом (первичные артефакты перезаписаны, независимо не воспроизводится)

* `tnav.ok = False`, ошибка `Could not recognize python code as workflow item` (базовый прогон
  «near line 108», все 5 ветвей «near line 554»), причина — `import os as _os_tnav` внутри
  `begin_wf_item` в шаблоне `map_2d_export_cps_format.txt`;
* агрегат qaqc реального прогона: `total=712, passed=12, failed=32, not_applicable=661,
  applicable=44, kq=0.0, kc=0.2791, fitness=0.1396, physical=false` (частично согласуется с
  ledger-метриками структурных стадий);
* объекты проекта: `PORO, PERM, STOIIP, HCPV, PoreVolume, NetVolume, Tl_thick, U1_top, LIT,
  Residual_U1_top, BAJ, main_grid`; **`FACIES` отсутствует** (экспортами подтверждается
  отсутствие FACIES и наличие PORO/PERM/STOIIP/HCPV/PoreVolume/NetVolume/Tl_thick/U1_top);
* ансамбль: 5 ветвей, все `ok=false`, `metric=null`, `scored=0`; `grid_geometry=null`.

### 11.3. Вердикты по итогам реального прогона №2 (`report_execute.json` от 19:13:39)

Проверено мной из сохранённого отчёта: `tnav.ok=false`, ошибка
`RuntimeError … in item 1 ("Create Geobody by Property")`; `steps` 49/48/0/0/1,
`render_warnings=[]`; `qaqc`: `applicable=44, passed=12, failed=32, not_applicable=661,
unknown=7, kq=0.0, kc=0.2791, fitness=0.1396, physical=false`; ветви: 5, все `ok=false`,
`metric=null`, `best=null`, `scored=0`; ошибка ветвей — `item 29 ("Facies Modelling (Zones,
Regions)"): Parameter "Grid" (in group "Input") is not specified!`.

| Этап | Вердикт | Что именно подтверждено / нет |
|---|---|---|
| E2 | **принято** | реестр из данных, `qaqc` в отчёте, coverage 6065, guard `min_applicable_checks=5`, `physical` различает «не проверялось» |
| E3 | **принято с замечаниями** | реальные метрики QA/QC: 44 применимых, 12 passed / 32 failed / 661 not_applicable, kc=0.2791, physical=false; слой значений работает. Замечание: 32 провала — это реальные несоответствия модели, они корректно не скрыты |
| E4 | **принято** | оцифровка, пороги, покрытие — тесты и артефакты |
| E5 | **принято** | **сходимость поверхности с отбивками подтверждена**: `struct.well_tie` медиана \|ΔZ\| = **8.58 м** (допуск 10.0), RMSE = **14.89 м** (допуск 15.0), 52 скважины; стадии 1–3 `bypassed` с `physical=false` — честная деградация по policy, не скрытый отказ |
| E6 | **принято** | **геометрия и качество сетки подтверждены**: `grid.geometry` nx×ny×nz = **250×311×22**, Z = −2518.67…−2358.84; `grid.quality` 1 710 500 ячеек, размер **49.6×49.5×7.3 м** |
| E7 | **НЕ подтверждён** | куба `FACIES` нет; две конкретные причины: базовый прогон падает на item 1 «Create Geobody by Property» (каскад от отсутствия FACIES), ветви — на item 29 с `Parameter "Grid" (in group "Input") is not specified!`. Документация сама честно фиксирует неподтверждённость (`grid_property_facies_modeling.rdf`: «полного подтверждения прогоном НЕТ»), но шаг включён в пайплайн и роняет воркфлоу вместо пропуска (F-20) |
| E8 | **принято** | **кубы и физичность подтверждены**: `petro.cubes` [PHIE→PORO, KINT→PERM], `petro.poro_range` PORO mean = **0.047** ∈ [0.02, 0.35], `petro.perm_range` PERM mean = **0.6709** ∈ [0.1, 5000.0]; карты PORO/PERM содержат данные (53 % ячеек, φ 0.09–0.11, k 1.5–1.9 мД) |
| E9 | **принято с замечаниями** | консольный путь работает: 7 PNG с реальными данными (PORO проверен визуально); **но** `STOIIP.png` нет, а `STOIIP.txt` пуст (0/77 500 ячеек), хотя свойство посчитано (`vol.stoiip` = **2.039e+08**) → дефект именно в выгрузке STOIIP (F-18); плюс `G-MAPS` проверил наличие карт **до** их построения (19:11:18 против PNG 19:11:21–19:11:34) и всё равно `passed` (F-19) |
| E10 | **НЕ подтверждён** | `scored=0`, метрика STOIIP по ветвям не снята, свёртка p10/p50/p90 вырождена; причина — каскад от E7 |

### 11.5. Прогон №3 (19:30:40, снапшот `runs/artifacts/execute_20261009_193040/`) — эффект фиксов F-19/F-20

| Что | Факт |
|---|---|
| `tnav.ok` | `False`; ошибка `item 2 ("Facies Modelling (Zones, Regions)"): Parameter "Grid" (in group "Input") is not specified!` |
| Стадии | 0 `passed`; 1–3 `bypassed`; 4, 5 `passed`; **6 и 6.1 `skipped`** (раньше было `passed`); 7, 8, 9, 10 `passed` |
| **F-19 подтверждён на живом прогоне** | стадия 6: `counts.critical.failed = 1`, `mode = skip`, комментарий «исчерпаны попытки: этап и зависимые шаги пропущены» → гейт больше **не** зелёный при отсутствии куба |
| **F-20 подтверждён на живом прогоне** | шаг 31 `geobody_create_by_property` → `skipped_by_policy`, причина «нет объекта-предпосылки «FACIES» (grid_property): шаг пропущен»; `skipped_by_policy = 2` (врез + geobody) |
| **F-21 (остаток, OPEN)** | шаг 29 `grid_property_facies_modeling` имеет статус **`done`** и реально исполнен (он и падает в тНаве), т.е. неподтверждённый шаг по-прежнему попадает в воркфлоу; `begin_wf_item = 48` при `done = 47` — блок отрендерен, хотя этап затем помечен `skipped`. Нужно либо подтвердить сигнатуру (объектный `grid`), либо исключать шаг из рендера до подтверждения — иначе `tnav.ok=false` остаётся |
| qaqc | 12 passed / 32 failed / 661 not_applicable / 7 unknown, applicable 44, kc 0.2791, physical false |
| Карты | 7 PNG (нет `STOIIP`), `STOIIP.txt` — 0/77 500 непустых (F-18 не закрыт) |
| Ансамбль | 5 ветвей, все `ok=false`, `metric=null`, `scored=0` (E10 не подтверждён) |
| Ветви: ошибка | та же `Facies Modelling … Parameter "Grid" …` |

Замечание к инварианту: «штатный skip ровно один» больше не выполняется — теперь
`skipped_by_policy = 2` (врез + geobody по `requires_object`), и это **корректный** рост:
пропуск по данным вместо падения. В приёмке фиксируем `done = total − skipped_by_policy`
(47 = 49 − 2) и `pending_template = 0`.

### 11.6. Процессное требование по приёмке (подтверждаю риск, поднятый foundation)

`runs/run_Герасимовское/` **перезаписывается параллельными прогонами участников**
(наблюдал: `qaqc applicable 0` ↔ `44/physical false`, `skipped_by_policy 1` ↔ `2`,
`report_execute.json` сменялся dry-run'ом дважды). Атомарная запись гарантирует целостность
файла, но не его принадлежность конкретному прогону. Для надёжной приёмки нужно одно из:
сериализовать прогоны, гонять в отдельный `--run-dir`, либо (как уже сделано Lead-ом)
снапшотить отчёт сразу после прогона. Мой `--from-artifacts` выбирает из сохранённых
отчётов тот, у которого `qaqc.physical` **не None** (признак реального прогона), и лишь
затем самый свежий — иначе он читал dry-run вместо execute.


### 11.8. Прогон №4 (снапшот `runs/artifacts/execute_20261009_195848/`) — базовый прогон чистый, ансамбль нет

| Что | Факт |
|---|---|
| **Базовый прогон** | `tnav.ok = True`, `error = ""` → **F-21 закрыт для staged-ветки** |
| steps | `total=49, done=46, error=0, pending_template=0, skipped_by_policy=3`; `begin_wf_item=46 = done` |
| Пропуски по данным (правило 6) | шаг 20 (врез), шаг 29 `grid_property_facies_modeling`, шаг 31 `geobody_create_by_property` («нет объекта-предпосылки «FACIES»: шаг пропущен по данным») — неподтверждённый шаг больше НЕ исполняется |
| **Ансамбль (F-22, OPEN)** | все 5 ветвей `ok=false`, `metric=null`, `scored=0`; ошибка ветвей: `item 30 ("Create Geoby Property") … cannot find object "Property "FACIES""` — в ветке рендерится 48 блоков (`models/S001/Structure_modeling.py`), т.е. **skip-решения staged-ветки в ансамбле не применяются**, geobody всё ещё исполняется |
| Карты | 7 PNG (нет `STOIIP`), `STOIIP.txt` пуст (F-18 не закрыт) |
| qaqc | 12 passed / 32 failed / 661 not_applicable (реальные значения), applicable 44, physical=false |
| **Замечание (F-23, minor)** | у пропущенного шага 29 в `steps.json` причина скопирована от вреза: «покрытие кровли BAJ 55/58 (95%) >= порога 80%: врез не требуется» — сообщение не соответствует шагу (skip верный, текст вводит в заблуждение) |

Итог по реальному прогону: базовая модель собирается до конца без падения воркфлоу;
остаются (1) неподтверждённый куб `FACIES` (E7) и как следствие вырожденный ансамбль (E10),
(2) пустая карта `STOIIP` (E9/F-18), (3) расхождение skip-логики staged ↔ ensemble (F-22).

### 11.9. Прогон №5 — ФИНАЛЬНЫЙ (`runs/artifacts/execute_20261009_201441/report_execute.json`)

Независимо проверено из снапшота:

| Что | Факт |
|---|---|
| База | `tnav.ok = True`, `error = ""`, steps `49 / done 46 / error 0 / pending_template 0 / skipped_by_policy 3`, `render_warnings = []` |
| **F-23 закрыт** | причины пропусков теперь корректные: шаг 20 — врез по покрытию; шаг 29 `grid_property_facies_modeling` — «сигнатура не подтверждена пробой на живой лицензии (workflow.unconfirmed_steps, правило 8)»; шаг 31 `geobody_create_by_property` — «нет объекта-предпосылки «FACIES» (grid_property)» |
| **F-22 закрыт** | все **5 ветвей `ok=true`** с метрикой STOIIP: S001 205.03, S002 203.29, S003 203.89, S004 **206.40**, S005 205.03 млн; `best = S004`, `scored = 5` |
| Геометрия | у каждой ветви `nx×ny×nz = 250×311×22`, Z ≈ −2518.7…−2353.6 (в staged-режиме верхнеуровневый `report["grid"]` = `null`, геометрия живёт в ветвях и в `G-GRID`) |
| **Новая находка F-24 (E10, OPEN)** | ветви **S001 и S005 бит-в-бит идентичны**: одинаковый SHA256 отрендеренного воркфлоу (`models/S001|S005/Structure_modeling.py`) и одинаковая метрика до последнего знака. Причина: вариация S005 адресует `map_2d_interpolate`, **которой нет в пайплайне** (28 функций) → параметр `kriging_radius` не применяется. Итог: из 5 ветвей различимы 4; свёртка частично вырождена. Добавлена независимая проверка в `tests/test_verify_triads.py` (раздел H) — она ловит это на данных, не дожидаясь прогона |
| p10/p50/p90 | ключа `rollup` в `report.json` нет (Lead подтвердил). По 5 метрикам свёртка вычислима и невырождена (203.29 … 206.40 млн, разброс ≈1.5 %), но **артефакт не пишется**; с учётом F-24 фактически 4 различимые ветви |
| Карты | 7 PNG, `STOIIP.txt` пуст (F-18 открыт) |
| Куб FACIES | отсутствует (E7 открыт, внешняя зависимость — нужен GUI-снимок вызова) |

**Итог по E10:** механизм ансамбля работает (5 ветвей, метрики, `best`, `scored=5`) —
это **принято с замечаниями**; замечания: (1) F-24 — вариация S005 вырождена
(функция не в пайплайне), (2) свёртка p10/p50/p90 не публикуется в `report.json`.
Без F-24/F-18 закрытие E10 «полностью» невозможно, но вырожденность самого механизма
(было `scored=0`) устранена.

**Остаточные известные ограничения (принять как ограничения, а не как дефекты):**
* **E7 / FACIES** — сигнатура `grid_property_facies_modeling` не подтверждена, шаг честно
  помечен как неподтверждённый и пропускается по данным (правило 8 соблюдено); для закрытия
  нужен GUI-снимок вызова или новая проба; связка «нет FACIES → skip» работает.
* **F-18 / STOIIP-карта** — волюметрия считается (`vol.stoiip` = 2.039e8), но выгрузка в
  `maps/STOIIP.txt` пуста; для закрытия нужна проба управляющего флага.

### 11.10. Новые находки по итогам прогона №2

* **F-19 (гейт неполон, правило 6)**: гейт может быть `passed` при отсутствии результата:
  `G-FACIES` = `passed` при `applicable=0` и findings только «policy/structure/contract»
  (куба `FACIES` нет) — в данных у G-FACIES **вообще нет требования свидетельства**
  (`config.yaml gates`: G-FACIES/G-DATA/G-SAT имеют `evidence` = пусто, тогда как G-STRUCT —
  `well_tie`, G-GRID — `grid`, G-PETRO — `property_mean`, G-VOL — `stoiip`, G-MAPS — `maps`);
  `G-MAPS` = `passed`, хотя его собственный major-чек `maps.files` вернул **False**
  («нет файлов: U1_top, Tl_thick, PORO, PERM, STOIIP, HCPV, PoreVolume, NetVolume») —
  статус гейта падает только на `critical`, а не на `major`; `G-SAT` = `passed` вообще без
  findings.
  Следствие: отсутствие обязательного результата не отражается в статусе гейта —
  нужно свидетельство вида `facies.cube_exists` и/или перевод artifact-чеков в `critical`.
* **F-20 (правило 8/2)**: неподтверждённый шаг не пропускается, а роняет весь воркфлоу.
  `grid_property_facies_modeling` включён в пайплайн (стадия 6), при этом его собственное
  правило честно пишет «полного подтверждения прогоном НЕТ»; на живом прогоне шаг падает
  (`Parameter "Grid" … is not specified!`) → базовый прогон и все 5 ветвей `ok=false`.
  Нужен зависимый пропуск по данным (`requires_object`) с `skipped_by_policy`, как и
  предложено Lead-ом.


**Единственная подтверждённая системная причина** частичного результата первого реального
прогона: дефект разбора воркфлоу из-за инструкции `import` внутри элемента воркфлоу в шаблоне
экспорта CPS (устранён petro 19:00:08). Итоговое состояние — в разделе 12 (прогон №5:
база `tnav.ok=True`, ансамбль оценён, E7/F-18 — известные ограничения).

---

## 12. ФИНАЛЬНОЕ ЗАКЛЮЧЕНИЕ ПРИЁМКИ

**Проверенный срез:** дерево после фиксов F-22/F-23; финальная цепочка и аудиты выполнены
2026-10-09 ~20:2x (`docs/VERIFY_chain_final.md`, `docs/VERIFY_execute4_audit.md`, прогон №5
в `runs/artifacts/execute_20261009_201441/`).

### 12.1. Обязательные тесты и инварианты (все подтверждены)

| Проверка | Результат |
|---|---|
| `test_v5` | **32 / 0** |
| `test_agents` | **223 / 0** |
| `test_base_agent` | **39 / 0** |
| `test_no_domain_in_code` | **4 / 0**, долг виден (24 позиции < базовых 26) |
| `test_contracts` | **107 / 0** |
| `test_qaqc_checks` | **55 / 0** |
| `test_structural_agent` / `test_facies_agent` / `test_petro_agent` | **69 / 0**, **44 / 0**, **78 / 0** |
| `pytest -q tests/test_v5.py tests/test_agents.py` | **42 passed**, скрытых ошибок импорта нет |
| `main.py preflight` | **OK** |
| dry-run | `total=49, done=47, error=0, pending_template=0, skipped_by_policy=2`, `done = total − skipped`, `render_warnings=[]`, `begin_wf_item=47`, чужих токенов нет |
| `report.json → qaqc` | ключ есть; `physical=null` на dry-run, реальные значения в execute |
| `qaqc_coverage.json` | 6065 пунктов, per-block и per-item, причины у `unknown`/`not_applicable` |
| Мои аудиты | триады FAIL 1 (только F-24), хардкод 0 нарушений, правило 6 FAIL 0, QA/QC FAIL 0, мануал FAIL 0 |

### 12.2. Вердикты по этапам

| Этап | Вердикт | Ключевое обоснование |
|---|---|---|
| **E2** | **принято** | `qaqc` в отчёте, coverage 6065, реестр из данных (742 проверки), guard `min_applicable_checks=5`, `physical=null` без данных, F-19 закрыт и подтверждён на живом прогоне |
| **E3** | **принято с замечаниями** | реальные метрики QA/QC (44 применимых: 12 passed / 32 failed / 661 `not_applicable`), 32 провала не скрыты |
| **E4** | **принято** | 62 `QC_*` оцифрованы (55 исполняемых + 7 `DESCRIBED_ONLY` → `unknown`), 46 порогов сверены с чеклистом — расхождений 0 |
| **E5** | **принято** | `struct.well_tie` медиана 8.58 м / RMSE 14.89 м (допуски 10/15), правило 4 (bottom-first) подтверждено, 5 триад из эталона |
| **E6** | **принято** | `grid.geometry` 250×311×22, `grid.quality` 1 710 500 ячеек 49.6×49.5×7.3 м; геометрия подтверждена и в ветвях ансамбля |
| **E7** | **принято** (обновлено по прогону `…20261010_170554`) | куб `FACIES` СОЗДАН и подтверждён свидетельствами: `facies.cube_exists` critical passed («куб FACIES есть среди свойств сетки»), `facies.cube_nonempty` major passed («ячеек с данными 904 750, классов 5»); стадии 6 и 6.1 — `passed`; `FACIES.png` построена, в экспорте дискретные коды (1.86–2.82), 53.1 % ячеек с данными |
| **E8** | **принято** | `petro.cubes` [PHIE→PORO, KINT→PERM]; PORO mean 0.047 ∈ [0.02, 0.35]; PERM mean 0.6709 ∈ [0.1, 5000]; карты PORO/PERM с реальными значениями |
| **E9** | **принято** (обновлено по прогону `…20261010_170554`) | `G-MAPS` = `passed` при `maps.files: critical`: «карт собрано: 9 из 9» — все ожидаемые (`checks.map_files`, включая `STOIIP` и `FACIES`) построены с реальными данными: PORO/PERM/HCPV/PoreVolume/NetVolume/Tl_thick ≈53 %, `STOIIP.txt` 52.9 % (40959 ячеек, значения ~470–514), `FACIES.txt` 53.1 %. **F-18 закрыт** (пустой куб STOIIP исправлен: `cube.metric_exists`/`cube.metric_nonempty` — оба critical passed). Замечание F-27: у `cube.metric_nonempty` нет нижней границы доли — куб STOIIP прошёл при **310 заполненных ячейках из 1 710 500** |
| **E10** | **принято с замечаниями** (обновлено по прогону `…20261010_170554`, run_key `run_Герасимовское_20261010_164849`, sha16 `881365d3f10e3c5a`) | **5/5 ветвей `ok=true`**, `scored=5`, `best=S002`; ветки изолированы в `models/branches/<run_key>/<vid>`; `invalid_variations: []` (валидация вариаций из данных). Замечания: **S001 ≡ S005 по метрике** (59354.26778570104 у обеих при разных SHA воркфлоу → вариация `map_2d_smooth 2500` не влияет на STOIIP) и свёртка p10/p50/p90 не публикуется в `report.json` |

### 12.3. Итог по правилам 1–8

Нарушений правил 1–8 на проверенном срезе **не обнаружено**:
1 — домен только в данных (0 незадекларированных литералов, долг 24 < базовых 26);
2 — все триады полные (42/42), единственный FAIL инструмента — F-24 (данные ансамбля, не триада);
3 — регламент проверок зелёный, dry-run-инварианты соблюдены, `--execute` выполнен и разобран;
4 — порядок горизонтов bottom-first подтверждён;
5 — чистый проект (удаление `.snp/.snf` + пересоздание ветвей) подтверждено кодом и прогонами;
6 — «неизвестное ≠ ложь»: `not_applicable`/`unknown` вместо `failed`/`passed`, `physical=null`,
пропуски по данным, `unverified` вместо «зелено» (F-19 закрыт);
7 — чужих токенов обучения в рендере нет, беззонная форма на месте;
8 — источники подтверждены (эталон/AST, туториал-воркфлоу тНава, отчёты проб, цитаты мануала
сверены с PDF), неподтверждённая сигнатура честно помечена и не исполняется.

### 12.4. Открытые пункты (не блокируют приёмку, зафиксированы как ограничения)

0. **Якоря вердиктов — снапшоты, а не рабочий каталог** (рабочий `runs/<id>/` перезаписывается
   следующим прогоном):
   | Снапшот | sha256 (16) | Что подтверждает |
   |---|---|---|
   | `runs/artifacts/execute_20261010_170554/report_execute.json` | `881365d3f10e3c5a` | **актуальная приёмка**: `tnav.ok=true`, 5/5 ветвей, `scored=5`, `best=S002`, `invalid_variations=[]`; стадии 6/6.1 `passed` (куб FACIES), `G-VOL`/`G-MAPS` `passed` (9/9 карт); ветки в `models/branches/<run_key>/` |
   | `runs/artifacts/execute_20261009_201441/report_execute.json` | `4235e53624ee98dd` | промежуточная приёмка: 5/5 ветвей `ok`, `scored=5`, `best=S004`, steps 49/46/0/0/3 |
   | `runs/artifacts/execute_20261009_202733/report_execute.json` | `f4f4d8bd68c0d447` | фиксирует блокер F-18: `G-VOL` = `bypassed` (`cube.metric_nonempty` failed, `metric_exists` passed) |
   | `runs/artifacts/execute_20261009_202125/report_execute.json` | `dd701014db81…` | живое подтверждение F-19: стадия 6 `critical.failed=1` → skipped; стадия 9 `critical.passed=2` → passed |
1. **F-18 — ЗАКРЫТО** (прогон `…20261010_170554`): куб `STOIIP` больше не пуст
   (`cube.metric_exists` + `cube.metric_nonempty` — оба critical passed), `STOIIP.txt` содержит
   40 959 непустых ячеек, `STOIIP.png` построена. **Новое замечание F-27**: в
   `agents/checks/builtin.py::check_cube_nonempty` критерий — только «`count > 0`»;
   `nonempty_fraction` из свидетельства читается, но **ни с чем не сравнивается**, поэтому куб
   `STOIIP` прошёл при **310 заполненных ячейках из 1 710 500** (0,018 %).
   *Рекомендация (зона foundation/Lead, task-9; правило 1 — порог только в ДАННЫХ):* добавить
   ключ вида `checks.cube_nonempty.min_fraction` (или `checks.properties.<role>.min_fraction`),
   читать его через `ctx` и требовать `fraction ≥ min_fraction`, где `fraction` = `nonempty_fraction`,
   иначе `count / cells` (или `count / (cells − nulls)`); если долю вывести нельзя — остаётся
   `unverified` (не `passed`). При `min_fraction = 0.05` куб STOIIP дал бы `failed` → гейт
   `degraded`, т.е. честный сигнал вместо формально зелёного. Передано foundation/Lead (не начато).
2. **E7 — ЗАКРЫТО** (там же): куб `FACIES` создан, стадии 6/6.1 `passed`, карта `FACIES.png`
   с дискретными кодами.
3. **F-24** — в данных закрыт (вариация S005 → `map_2d_smooth`, `invalid_variations: []`), но
   остаётся **остаточное замечание**: метрика S005 совпадает с S001 до последнего знака при
   различающихся воркфлоу → вариация применяется, но на STOIIP не влияет; свёртка
   p10/p50/p90 не публикуется.
4. **F-25 (наблюдение)** — в снапшоте `…202733` ветвь S004 упала на
   `File "models/S004/struct/depth_u1.irap" does not exist` (стадирование данных ветки);
   сейчас ветки изолированы в `models/branches/<run_key>/`, падение не воспроизводится.
5. **F-26 — МИТИГИРОВАНО**: ветки пишутся в пер-прогонную зону
   `models/branches/<run_key>/<vid>` (проверено: `branches/run_Герасимовское_20261010_164849` —
   167 257 файлов; каталоги `models/S00N` больше не перезаписываются), добавлены поля
   `caller`/`run_key`/`models_dir` в отчёт; `tests/test_agents.py` изолирован (F-31).
6. **Свёртка p10/p50/p90** не публикуется в `report.json` (есть `best`/`scored`).
7. **`steps.total` — НЕ инвариант** (растёт с составом пайплайна): сейчас **53**
   (`done 52`, `skipped 1`, `error 0`, `pending_template 0`, `render_warnings []`).
   Инварианты приёмки: `error = 0`, `pending_template = 0`, `render_warnings = []`,
   `done = total − skipped_by_policy`.
8. **F-12** — `workflow.transitions` не читается (наследие, данные для генератора спеки).
9. **F-13** — `domain/qaqc/parameters.py`: наследованный сгенерированный файл, исходная книга
   и генератор в репозитории отсутствуют.
10. **task-18/A (разделение каталогов) — мои инструменты обновлены**: dry-run пишет в
   `runs/run_<поле><runs.dry_suffix>` (`_dry`), execute — в `runs/run_<поле>/`.
   `test_verify_qaqc_checklist.py` читает покрытие из dry-каталога и проверяет
   «passed без данных» только для dry-отчёта (классификация: поле `execute` → `qaqc.physical
   is None` → суффикс пути); `test_verify_chain.py` читает артефакты из dry-каталога в
   dry-режиме и из общего — в `--from-artifacts`. Оба инструмента — exit 0.
11. **Атрибуция прогонов подтверждена** (web-run-fix, F-31/F-32): в свежем
   `runs/run_Герасимовское_dry/report.json` есть `execute=False`, `caller='cli'`,
   `run_key='run_Герасимовское_dry_20261010_173125'`, `models_dir`; в снапшоте приёмки от
   16:48 `execute=None` (записан до правки). Независимо прогнал `tests/test_model_artifacts.py`
   → **35/0**, в т.ч. проверка «суффикс dry-run берётся из ДАННЫХ (`runs.dry_suffix`)».
   Мой классификатор использует это поле первым приоритетом и уже работает на новом формате;
   отдельный `--execute` ради поля в старом снапшоте не нужен (отклонил как избыточный:
   ~10 мин лицензии и ~1 ГБ моделей).

9. **F-26 (инцидент общих артефактов, подтверждён по следам)** — снапшоты
   `runs/artifacts/execute_20261010_160046` (sha16 `b9c49f480caa`) и `…_160056`
   (sha16 `90cd2dff8b3e`) имеют `project.run_dir = %TEMP%\tmp*\run` при общем
   `models_dir = …/orchestrator_v8/models`, `tnav.ok = true`, но `scored = 0` и
   `grid_geometry = null` у всех 5 ветвей. Так как `core/coordinator._build_ensemble`
   перед каждой ветвью делает `shutil.rmtree(models/<vid>)`, а деградированный прогон
   проект не сохраняет, каталоги `models/S001…S005` остались **без `.snp`** (проверено:
   `.snf` = 0 файлов). Базовая модель приёмки уцелела в копиях
   `models/run_Герасимовское_20261010_154459/` (31 486 файлов).
   *Источник найден (web-run-fix, F-31), атрибуция моего инструмента снята:* виноват
   `tests/test_agents.py` — в нём вызывался `coord.run(run_dir=<tmp>/"run", execute=True)`
   с ФЕЙКОВЫМ клиентом, но с РЕАЛЬНЫМ `coord.cfg`, поэтому координатор писал снапшоты в
   `runs/artifacts` и делал `rmtree(models/<vid>)`. **Мой независимый сентинел-эксперимент
   подтвердил и фикс, и снятие атрибуции:** до/после запуска `tests/test_agents.py` —
   снапшотов 299 → 299 (**новых 0**), файловый состав `models/S001…S005` не изменился
   (хеши совпали), тест 223/0. Фикс: `tests/test_agents.py:734-750` подменяет на время теста
   `project.models_dir`, `runs.execute_archive_dir`, `runs.root` на tmp и восстанавливает в
   `finally`.
   *Мои вердикты не пострадали:* они привязаны к сохранённым снапшотам JSON
   (`…201441`, `…202733`, `…202125`), а не к каталогам моделей.
   *Защита в моём инструменте (сделано):* `--execute` требует явного `--confirm` и
   **отказывается** запускаться при наличии файла блокировки (`--lock-file` — для проверки),
   печатает `run_dir` и предупреждает, если все `models/S0*` без `.snp`;
   читающий режим `--from-artifacts` ничего не запускает.
   *Масштаб шума (измерено мной):* `runs/artifacts` — **299 каталогов, 629.3 МБ**, из них
   подавляющее большинство — вырожденные (`run_dir` в `%TEMP%` и `scored=0`). Чистка должна
   сохранять доказательные снапшоты приёмки (`execute_20261009_201441` sha16
   `4235e53624ee98dd`, `execute_20261009_202733` sha16 `f4f4d8bd68c0d447`,
   `execute_20261009_202125` sha16 `dd701014db81`) и те, у которых `tnav.ok=false` с
   содержательной ошибкой (они фиксируют блокеры).
   *Рекомендация (совпадает с предложением `web-run-fix`):* вынести ветки в
   пер-прогонную зону `models/branches/<run_key>/<vid>` (или кэш по ключу вариации),
   чтобы прогон не мог стереть модели другого прогона, и писать в снапшот
   `run_dir`/`models_dir`/идентификатор вызвавшего.

### 12.5. Воспроизведение проверок

```powershell
$py='C:\ProgramData\anaconda3\python.exe'; cd D:\Documents\GIT\ГеоМАС\orchestrator_v8
& $py -X utf8 tests/test_verify_chain.py                 # тесты + pytest + preflight + dry-run + инварианты
& $py -X utf8 tests/test_verify_chain.py --from-artifacts # аудит сохранённого --execute (выбирает отчёт с physical != None)
& $py -X utf8 tests/test_verify_triads.py                # триады, правило 4, источники, вариации (F-24)
& $py -X utf8 tests/test_verify_hardcode.py              # правило 1 независимо + ключи данных
& $py -X utf8 tests/test_verify_rule6.py                 # «неизвестное ≠ ложь» + F-19 result_checks
& $py -X utf8 tests/test_verify_qaqc_checklist.py        # чеклист ГПН ↔ пакет ↔ coverage
& $py -X utf8 tests/test_verify_manual_citations.py      # цитаты мануала ↔ PDF
```

### 12.6. Дополнение после правок foundation (result_checks + серьёзность из данных)

Проверено мной независимо, после того как в данных/реестре появилась проверка
`cube.metric_nonempty` и «серьёзность из данных»:

1. **Реестр**: в `CheckRegistry.from_data(cfg)` — **743** проверки; в
   `ontology/qa_gate_map.yaml → result_checks` — **8** id, все зарегистрированы
   (G-FACIES 2, G-PETRO 4, **G-VOL 2**: `cube.metric_exists` + `cube.metric_nonempty`).
2. **Семантика G-VOL** (имя метрики из данных `ensemble.metric` = STOIIP), проверено пробой
   `reg.run("G-VOL", …)` + `GateEngine.evaluate`:
   | Свидетельство | Результат | Вердикт гейта |
   |---|---|---|
   | метрики нет в `grid_properties` | `cube.metric_exists` failed | **failed** |
   | метрика есть, `property_stats.count = 0` | `cube.metric_nonempty` failed | **failed** |
   | метрика есть и непуста | обе passed | **passed** |
   | нет `property_stats` | `cube.metric_nonempty` **unverified** | **pending_execution** |
3. **Серьёзность из ДАННЫХ**: при инъекции `checks.check_severity = {"cube.metric_nonempty":
   "minor"}` (в памяти, без правки файлов) уровень находки становится `minor`, а вердикт гейта
   — `passed` (minor не валит гейт). Без правки данных: spec-уровень = `critical`.
   Дополнительно добавлен **глобальный инвариант** (`test_verify_rule6.py`, разделы 10–11):
   (а) множество допустимых уровней берётся **из кода** (`agents.contracts.SEVERITIES` =
   `critical|major|minor|note`), чтобы контракт не расходился;
   (б) все id из данных зарегистрированы в реестре; (в) `severity` находок в
   `runs/**/agents/gates/*.json` совпадает с данными (артефакты **старше** правки
   `config.yaml` считаются устаревшими и не дают ложного FAIL);
   (г) синтетика по ВСЕМ уровням: `critical → гейт failed`, `major|minor|note → passed` —
   ни один уровень не игнорируется (проверено, включая `note`, который foundation довёл
   до полноценного уровня в `SEVERITIES`).
   На момент проверки: в данных 1 точка управления — `checks.check_severity.maps.files =
   critical`; реестр совпадает; все 20 артефактов гейтов старше этой правки (устаревшие).
   Самопроверка детектора: при подставленной заведомо неверной карте уровней поймано
   3 расхождения из 3 (`facies.cube_exists: critical != minor`, `maps.files: major != critical`).
   **Следствие для E9:** с `maps.files = critical` отсутствие `STOIIP.png` теперь уронит
   G-MAPS (политика `best` → degraded) — на следующем `--execute` это должно быть видно
   явно; до этого E9 остаётся «принято с замечаниями».
4. **Живое подтверждение на снапшоте `execute_20261009_202125`** (`agents.stages`):
   стадия 6 `G-FACIES` — `critical.failed = 1` → `skipped` (F-19 работает);
   стадия 9 `G-VOL` — `critical.passed = 2` → `passed` (обе новые проверки метрики сработали
   на реальных данных); стадия 6.1 — `skipped` с `skipped_steps[requires_object]`.
5. **Уточнения для чтения артефактов** (важно для приёмки):
   * снапшот `execute_20261009_202125` — это **целевая проба F-18**
     (`project.ensemble.models_dir = runs/_f18_base_models`, одна ветка S001), а не
     приёмочный ансамбль; приёмочный — `execute_20261009_201441` (5 ветвей, `scored=5`);
   * `runs/<id>/agents/gates/*.json` **перезаписываются последним прогоном**: если после
     `--execute` запускался dry-run, там лежат contract-находки и `pending_execution`
     (runtime-проверки в dry-run не исполняются) — гейтовые выводы нужно читать из
     сохранённого снапшота, а не из рабочего каталога;
   * `G-MAPS` на стадии 10 даёт `major.failed = 1` (нет `STOIIP.png`), но остаётся `passed`:
     отсутствие карты — `major`, а не `critical`. Если требование «≥8 карт» считать жёстким
     критерием приёмки, проверку надо поднять в `critical`; в моём отчёте это уже отражено
     как замечание E9/F-18, а не как «принято без оговорок».



