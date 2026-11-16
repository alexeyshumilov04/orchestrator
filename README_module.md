# Оркестратор ГГДМ (самодостаточная сборка) — tNavigator Python API

Оркестратор строит **3D геологическую модель** месторождения средствами **Python API
tNavigator (v26.1)**: читает онтологию и данные → собирает план → **рендерит исполняемый
`.py`-воркфлоу** тНава → прогоняет его **headless** → считает **QA/QC** → строит
**ансамбль реализаций** (метрика — STOIIP) → отдаёт проект `.snp` (открывается в GUI).

Главное правило: **в коде нет хардкода домена**. Операции, стадии, функции, QA-правила,
маркеры, пороги, пути к данным и значения — читаются из файлов (`ontology/`,
`ontology_project/`, `domain/templates/`, `domain/ontology_rules/`).

Папка **самодостаточна**: внутри лежат **код + онтология v4 + данные поля**. Внешним
остаётся только сам tNavigator (абсолютный путь в `config.yaml`).

---

## 1. Быстрый старт

```powershell
cd <путь>\orchestrator
pip install -r requirements.txt

python -X utf8 main.py preflight                        # тНав + онтология (модель не строится)
python -X utf8 main.py plan  --field Герасимовское       # план из онтологии (без запуска)
python -X utf8 main.py run   --field Герасимовское       # рендер + dry-run + QA/QC
python -X utf8 main.py run   --field Герасимовское --execute   # РЕАЛЬНЫЙ прогон тНава
python -X utf8 main.py serve --host 127.0.0.1 --port 8770      # веб-сервис (SPA)
python -X utf8 tests/test_v5.py                          # тесты (32 проверки)
```

`-X utf8` обязателен на Windows: в путях и логах кириллица.

Что появляется при `--execute`:

- `runs/run_<поле>/` — воркфлоу `<поле>.py`, отчёт `report.json`, `steps.json`, `Polygons/`, `Wells/`;
  карты с изолиниями — `runs/run_<поле>/maps/*.png` (стадия «10. Экспорт карт»);
- `models/S001…S005/` — по ветке ансамбля: `<поле>.snp` и её воркфлоу (можно открыть в GUI тНава);
- в `report.json`: `ensemble` (ветки, метрика STOIIP, `best`), `qaqc` (kq/kc/физичность), `critic` (вердикт).

Проверенный результат на Герасимовском: сетка **250×311×22**, STOIIP по 5 ветвям, лучшая — `S004`;
`preflight: OK`, тесты `32/32`. Полный прогон ~10–13 мин (импорт + горизонты + сетка + 5 ветвей).

---

## 2. Структура папки

```
orchestrator/
├─ main.py                    CLI: preflight | plan | run | serve
├─ api.py                     веб-слой FastAPI (REST + WebSocket)
├─ config.yaml                КОНФИГ: пути, тНав, ансамбль, исполнение
├─ config.local.yaml          СЕКРЕТЫ (LLM-ключ, лицензия тНава) — не коммитится
├─ requirements.txt           rdflib, PyYAML, fastapi, uvicorn, numpy, matplotlib
├─ README.md                  этот файл
├─ README_legacy.md           прежний README (v5.1) — историческая справка
│
├─ core/                      ЯДРО (движок; домен сюда не проникает)
│   ├─ config.py              чтение config.yaml + config.local.yaml, разрешение путей
│   ├─ coordinator.py         ГЛАВНЫЙ ФАСАД: plan/run/ensemble/QAQC (вся оркестровка)
│   ├─ ontology.py            онтология v4 КАК ДАННЫЕ (process/qa/params/software CSV)
│   ├─ datasets.py            инвентарь набора данных (что реально есть)
│   ├─ data_kinds.py          единое отображение «онтологический класс ↔ тип данных»
│   ├─ planner.py             план «по данным» (нет данных → шаг не бежит)
│   ├─ node_contract.py       контракт узла (requires/produces/engine)
│   ├─ pipeline.py            шина шагов (этап→операция→функция→объект + статус)
│   ├─ ensemble.py            сценарная ось и пул реализаций
│   ├─ rollup.py              свёртка веера (best | pareto | p10_p50_p90)
│   ├─ metrics.py             метрики из RESULTS тНава (КИН/OOIP)
│   ├─ system_model.py        слой значений (объект × сценарий × момент)
│   ├─ llm_gateway.py         LLM-advisory (DeepSeek, OpenAI-совместимый)
│   └─ runner.py              фоновые прогоны, реестр, остановка
│
├─ domain/                    ДОМЕН (tNavigator): шаблоны, рендер, QA/QC
│   ├─ assembler.py           онтология групп операций → гены узлов
│   ├─ function_rules.py      правила функций (<function>.rdf)
│   ├─ workflow_model.py      модель гена/узла/объекта
│   ├─ workflow_renderer.py   рендер .py-воркфлоу тНав v26.1
│   ├─ tnav_client.py         клиент тНава: preflight, проект, воркфлоу, лицензия
│   ├─ trajectories.py        инклинометрия → таблицы Wells/<скв>.txt (MD X Y Z)
│   ├─ welltops.py            отбивки + нормализация имён скважин
│   ├─ qaqc_adapter.py        652 проверки → kq/kc/физичность
│   ├─ qaqc/                  ПАКЕТ проверок (данные: check_<id>(data))
│   ├─ metacritic.py          доказательный вердикт по 6117 правилам онтологии
│   ├─ geostat.py             геостатистика (кригинг/SGS по LAS)
│   ├─ templates/             сырые шаблоны функций тНава (26 шт.)
│   └─ ontology_rules/        <function>.rdf (26), ontology.rdf, transitions.xlsx
│
├─ agents/                    АГЕНТНЫЙ СЛОЙ: агенты-политики, гейты, проверки
│   ├─ base_agent.py          базовый класс агента (BaseAgent: agent_id/decision)
│   ├─ structure_policy.py    структурный агент (рабочий интервал и «врез»)
│   ├─ grid_policy.py         агент сетки (бокс из extent карты, шаг сетки)
│   ├─ facies_policy.py       агент фаций (SIS: метод/классы/вариограмма)
│   ├─ runner.py              поэтапный прогон с гейтами (StageRunner)
│   ├─ gates.py               движок гейтов (политики, байпасс, waiver)
│   ├─ checks/                проверки гейтов (builtin/contract/adapters)
│   └─ evidence.py            сбор свидетельств этапа (static)
│
├─ frontend/                  SPA (index.html, app.js, styles.css)
├─ ontology_project/
│   └─ gerasimovskoe.yaml     ПРОЕКТНЫЙ ГРАФ (данные месторождения: стадии, маркеры, вариации)
├─ ontology/                  ОНТОЛОГИЯ v4 (CSV + RDF) — внутри папки
├─ data/
│   └─ Герасимовское/Source/  ДАННЫЕ поля: RIGIS/*.las, struct/*.irap, GERASIM_406_inkl/*.las,
│                             Wellhead.txt, Welltop.txt, «Координаты устья.xlsx»
├─ tests/test_v5.py           32 проверки (онтология, ассемблер, рендер, QAQC, сетка, траектории)
├─ runs/                      результаты прогонов (создаётся; в .gitignore)
└─ models/                    проекты .snp по ветвям (создаётся; в .gitignore)
```

---

## 3. Как поменять путь до тНава, лицензию, LLM

### 3.1 Путь до tNavigator (обязательно при переносе на другую машину)

Базовый `config.yaml` хранит эталонные 26.1; фактическая установка машины задаётся
переопределением в `config.local.yaml` (не коммитится):

```yaml
tnavigator:
  install_dir: "C:/Program Files/tNavigator/26.2"                    # ПАПКА установки
  executable:  "C:/Program Files/tNavigator/26.2/tNavigator-con.exe"  # консольный сервер (headless)
```

Меняются **обе** строки (папка + exe). `tNavigator-con.exe` — «сервер управления»: через него
Python API создаёт/открывает проект без GUI. Прямая косая черта `/` работает и на Windows.

Проверка: `python -X utf8 main.py preflight` → ожидается `"present": true`,
`"api_available": true`, строка версии вида `tNavigator v26.2-…` и в конце `preflight: OK`.
Каталог `install_dir` должен содержать `libs/python/tNavigator_python_API.zip`.
При первом подключении оркестратор РАСПАКОВЫВАЕТ API из zip в `tnavigator.api_cache_dir`
(по умолчанию `.tnav_api/`, в .gitignore): импорт из архива для исполнения не подходит —
клиент `tNavigator-API-client.exe` ищется рядом с `.py` и внутри архива не находится.
Исходный путь взят из файла-подсказки в корне проекта (`Путь до тнав и пароль.txt`).

### 3.2 Лицензия tNavigator

`config.local.yaml` (в .gitignore):

```yaml
tnavigator:
  license:
    url:  "http://<license-server>:4085"   # адрес сервера лицензий
    login: "<логин>"
    pass:  "<пароль>"
```

Приоритет (`domain/tnav_client.py::_connection_options`): если задан `login` — пишется
`runs/tnav_license_settings.ini` (`url/login/pass`) и передаётся в `ConnectionOptions` как
`license_settings`; иначе используется `license_server_url` + `license_type: network`.
Адрес сервера лицензий можно подсмотреть в `%APPDATA%/tNavigator/tNavigator.ini`.
Запрашиваемые фичи — `tnavigator.license_features` (по умолчанию `["FEAT_GEOLOGY_DESIGNER"]`).
Пример рабочего адреса из прежних прогонов: `tnav://tnavigator-license.irmodel.ru:8057/…`
(если `url` пуст — тНав берёт настройки лицензии из `%APPDATA%`).

Схема `tnav://` (26.2): опции лицензии НЕ передаются — сервер и учётные данные задаются
в `%APPDATA%\tNavigator\tNavigator.ini` (ключи `*_local`), API-клиент получает лицензию
сам; файл настроек по пути с кириллицей клиент открыть не может. Для `http(s)://` файл
настроек пишется в системный temp (ASCII-safe) или по `license_settings_file`.

Без лицензии шаги без `--execute` (dry-run) работают полностью: рендер воркфлоу, план, QA/QC,
тексты шагов — только реальный расчёт тНава не выполняется.

### 3.3 LLM (необязательно)

`config.local.yaml` → `llm.api_key` (DeepSeek), `llm.model` (`deepseek-flash`).
Пусто → берётся переменная окружения `ORCH_LLM_API_KEY`. При недоступности LLM работает
детерминированный fallback — прогон не останавливается (`core/llm_gateway.py`).

### 3.4 Смена месторождения

Нужен новый проектный граф `ontology_project/<поле>.yaml` (маркеры, стадии, вариации,
`dataset_root`) и данные в `data/<поле>/Source/`. Поле выбирается
`--field <поле>` или `project.default_field` в `config.yaml`. Поиск набора — по
`field:` внутри yaml.

---

## 4. Архитектура (как это работает)

Три слоя, связанные только через данные:

```
     ДАННЫЕ                      ЯДРО (core/)                     ДОМЕН (domain/)
ontology/ (v4 CSV+RDF) ──► core/ontology.py ──┐
ontology_project/*.yaml ─► (проектный граф)  ──┼──► core/planner.py
data/<поле>/Source/ ─────► core/datasets.py ───┘         │
                                                         ▼
                                          domain/assembler.py + function_rules.py
                                                         │  гены узлов/функций
                                                         ▼
                                          domain/workflow_renderer.py  → .py-воркфлоу
                                                         │
                                          domain/tnav_client.py ──► tNavigator (headless)
                                                         │  .snp + объекты модели
                                                         ▼
                                   domain/qaqc_adapter.py / metacritic.py → вердикт
```

Путь одного прогона (`python main.py run --field Герасимовское --execute`):

1. **Конфиг** — `core/config.py` читает `config.yaml`, сверху накладывает `config.local.yaml`.
2. **Онтология** — `core/ontology.py` читает CSV-каталоги: 1272 операции, 18 стадий,
   3257 функций тНава, 6117 QA-правил, 403 параметра, 414 software-привязок.
3. **Проектный граф** — `ontology_project/<поле>.yaml`: стадии пайплайна, объекты, маркеры,
   вариации ансамбля, пороги.
4. **Данные** — `core/datasets.py` + `core/data_kinds.py`: инвентарь набора → какие операции
   вообще возможны; `core/planner.py` строит план «по данным» (операция без данных → `needs_data`).
5. **Гены** — `domain/assembler.py` (цепочка групп `hasNextStep` из `ontology.rdf`) +
   `domain/function_rules.py` (правила `<function>.rdf`: параметры/входные/выходные объекты).
6. **Рендер** — `domain/workflow_renderer.py`: `declare_workflow` + `begin_wf_item`/`end_wf_item`
   + вызовы функций тНава (`api_version=v0_0_300a`). Результат — компилируемый `.py`.
7. **Подготовка данных** — `_stage_data()`: копия `data/<поле>/Source` рядом с проектом;
   `domain/trajectories.py` пишет `Wells/<скв>.txt` (`MD X Y Z`, метод минимальной кривизны);
   `domain/welltops.py` приводит имена скважин в отбивках к именам проекта; строится `Polygons/`.
8. **Исполнение** — `domain/tnav_client.py`: `Connection(path_to_exe='…/tNavigator-con.exe')`
   → `create_project(.snp)` → `init_api_license()` → `run_py_code(<воркфлоу>, save=True)`.
   Проект создаётся **всегда с нуля** (старый `.snp`/`.snf` удаляется — иначе в нём остаётся
   объект `main_grid` прошлого прогона и `grid_3d_create_by_horizons` падает).
9. **Чтение результата** — единый канал «py-код в проекте → tmp-файл → разбор по ключам»
   (`_read_py_capture`): STOIIP (волюметрия), геометрия сетки (`nx/ny/nz`, min/max),
   сшивка скважин (отбивка vs горизонт в точке скважины).
10. **QA/QC** — `domain/qaqc_adapter.py` (652 проверки → `kq`/`kc`/физичность) и
    `domain/metacritic.py` (6117 правил → `passed`/`failed`/`unknown`).
11. **Ансамбль** — `_build_ensemble()`: на каждую вариацию своя папка `models/<vid>/`,
    свой воркфлоу и `.snp`; метрика — STOIIP; `best` = максимум; свёртка `rollup`.

---

## 5. Принципы

1. **Данные вместо кода.** Ни одного имени поля/маркера/пути в `.py`: всё — в `config.yaml`,
   `ontology_project/*.yaml`, `domain/templates/`, `domain/ontology_rules/`, `ontology/`.
2. **Ядро не знает домена.** `core/` оперирует контрактами (`node_contract.py`); tNavigator
   живёт только в `domain/`.
3. **План зависит от данных.** Нет входных данных → шаг не исполняется (а не падает).
4. **Отсутствие данных ≠ провал.** QAQC-проверка без входов → `not_applicable` (модель не
   штрафуется); неформализованное правило → `unknown`, а не `false`.
5. **`UNKNOWN` сохраняется** и виден в отчёте — неизвестное не подменяется «ложью».
6. **LLM советует, но не владеет фактами.** Постановка/рассуждение — LLM; числа и вердикт —
   детерминированно.
7. **Неединственность ГГДМ.** Результат — не одна модель, а **ансамбль** ветвей по осям
   вариаций, с физической метрикой для отбора.
8. **Воспроизводимость.** Каждый прогон — с чистого проекта; все артефакты — в `runs/<id>/`.

---

## 6. Что уже реализовано (и проверено)

| # | Блок | Состояние |
|---|---|---|
| 1 | Онтология v4 как данные (CSV + RDF) | ✅ 1272 операции, 18 стадий, 3257 функций, 6117 QA-правил, 403 параметра |
| 2 | Проектный граф `ontology_project/gerasimovskoe.yaml` | ✅ стадии 0…10 (включая фации SIS), маркеры, вариации S001…S005 |
| 3 | План «по данным» (`planner.py`) | ✅ операция без данных не исполняется |
| 4 | Гены + рендер `.py`-воркфлоу тНав v26.1 | ✅ 26 шаблонов функций, `declare_workflow`, api_version |
| 5 | Импорт данных: маркеры, ГИС (LAS), структурные карты (irap) | ✅ стадия 0: `depth_u1` + сейсмотренд `depth_u1_not_tued` (`novalue=9999900`) |
| 6 | Инклинометрия → траектории `Wells/<скв>.txt` | ✅ минимальная кривизна + инвариант `MD ≥ \|ΔXYZ\|` |
| 7 | Нормализация имён скважин в отбивках | ✅ регистр/синонимы, сироты отбрасываются |
| 8 | Горизонты: IDW по маркерам + тренды + сглаживание | ✅ кровля `C1tl_top` ← сейсмотренд `C1tl_Z_trend_smooth`, `C1bb_top` ← `C1bb_top_trend` с **residual IDW** (`use_residual_idw=True`: невязки интерполируются, скважины фиксируются); подошва `C1bb_bot` маркерная (важен **порядок «низ → верх»**) |
| 9 | Локальные боксы структурных построений | ✅ map_2d/interpolate/calculator, horizon_calculator — бокс поля (не чужой `2221900`) |
| 10 | **Решение структурного агента о врезе** | ✅ `structural:` + `agents/structure_policy.py`: по покрытию отбивками детерминированно (Герасимовское: BAJ 55/58 → врез строится); `erosion: on|off` — переопределение человека; шаги пропускаются `skipped_by_policy` |
| 11 | Полигон вреза (эрозия) из структурной карты | ✅ `Polygons/Boundary.txt` |
| 12 | **3D-сетка corner-point** `grid_3d_create_by_horizons` | ✅ **250×311×22**, без ошибок; бокс агент выводит из extent карты |
| 13 | Апскейлинг ГИС (blocked wells) | ✅ кубы `LIT`, `PORO` |
| 14 | Петрофизика PORO | ⚠️ пока **константа 0.2** (не из LAS) |
| 15 | Насыщение: контакт OWC | ✅ `contact_create_by_horizon` |
| 16 | **Волюметрия → STOIIP** | ✅ читается числом (≈1.78·10⁹) |
| 17 | **Ансамбль** ветвей + метрика + `best` | ✅ 5 веток, метрика STOIIP, `best = S004` |
| 18 | QA/QC (652 проверки → kq/kc/физичность) | ✅ `passed 12 / failed 32 / not_applicable 549` → `kq 0.0`, `kc 0.2791`, `fitness 0.1395` |
| 19 | QA/QC-сшивка скважин (отбивка vs горизонт) | ✅ медиана |ΔZ| (допуск 10 м) **и RMSE** (допуск `checks.well_tie_rmse_m`) — `struct.well_tie` + `struct.well_tie_rmse` |
| 20 | Защита геометрии сетки (`check_grid_geometry`) | ✅ ловит вырожденный Z и нереальную мощность |
| 21 | Веб-сервис FastAPI + SPA | ✅ `main.py serve`; детерминированный запуск `POST /api/runs` (кнопка, без LLM); **«⌫ Сбросить»** — `POST /api/reset` очищает сообщения и прогоны (запуск с нуля) |
| 22 | Индикация прогресса | ✅ фазы (plan→data→render→execute→qa→ensemble), WS-heartbeat 0.5 с, поллинг после перезагрузки; строка решения структурного агента в «Прогрессе» |
| 23 | Карты с изолиниями | ✅ стадия 10 `create_screenshot` (изолинии + палитра) + фолбэк `domain/map_render.py`; панель «Карты» в UI |
| 24 | **Агенты-политики этапов** (`BaseAgent`) | ✅ `agents/base_agent.py` + `structure_policy`/`grid_policy`/`facies_policy`: детерминированные решения по ДАННЫМ — врез (покрытие отбивками), бокс сетки (extent карты), фации SIS (метод/классы/вариограмма); патч параметров через `_variant_gene`, решения в отчёте (`grid_policy`/`facies_policy`) |
| 25 | **Фации (SIS), стадия 6** | ✅ включена (агент `AG_FACIES` + статическая проверка `facies.policy`, гейт `G-FACIES`); карта `FACIES` — стадия 10 и `checks.map_files` |
| 26 | Тесты | ✅ `tests/test_v5.py` — **32/32**; `tests/test_agents.py` — **180/180** (офлайн, без сети) |

---

## 7. Что нужно реализовать (roadmap)

Приоритет сверху вниз.

1. **Верифицировать структурные тренды на реальном прогоне.** Кровля `C1tl_top`
   строится IDW с трендом `depth_u1_not_tued` (сейсмика, СЗ край — бланк) и
   **residual IDW** (`use_residual_idw=True` — скважины фиксируются, тренд задаёт
   форму между ними); `C1bb_top` — с трендом `C1bb_top_trend`. Контроль —
   `struct.well_tie_rmse` (допуск `checks.well_tie_rmse_m`): до правки RMSE был
   ~46 м максимум в скважинах. При «The resulting grid has no elements!» на
   прогоне — вернуть `use_trend_horizon: False` у `C1tl_top` (инструкция уже в
   комментариях `gerasimovskoe.yaml`, стадия 2). Решение о врезе (покрытие BAJ)
   агент принимает сам — `structural.erosion`.
2. **Реальная петрофизика вместо константы.** LAS содержат `PHIE, KINT, SW, VCL, LIT`.
   Заменить `PORO = 0.2` на интерполяцию `PHIE` на сетку и добавить `PERMX` из `KINT`.
   Мешает: шаблон `grid_property_interpolate_by_wells_log_3d` (1005 строк) завязан на
   **чужую зону** `Litho3D` → нужны `use_zone=False, use_region=False` и чистка
   `ZoneRegionParameters`/`InterpolationParametersItem`.
3. **Фации (SIS), стадия 6 — включена; проверить на РЕАЛЬНОМ прогоне.** Шаблон
   `grid_property_facies_by_wells_log_3d` очищен от чужих зон (`name="zone_id"` → пустые
   имена, `ZoneRegionParameters.use=False` — правило 7); стадия включена в проектном YAML
   (агент `AG_FACIES`: метод/классы/вариограмма из `geostat:`; гейт `G-FACIES` = `skip`,
   статическая проверка `facies.policy`). Осталось — прогнать на живом тНаве (при
   «Unable to create operation» — вернуть комментарий к блоку; прогон продолжится).
   Фациальная карта `FACIES` уже добавлена в стадию 10 и `checks.map_files`.
4. **Метакритик: `verdict = unknown`.** Сейчас почти все 6117 правил без входных значений.
   Нужно расширить `_qaqc_values()` / `metacritic` значениями ключевых сущностей модели
   (`nx/ny/nz`, толщины, горизонты, STOIIP, диапазоны PORO/PERMX) — тогда вердикт станет
   `passed/failed`.
5. **Пороги QAQC-пакета.** 32 «провала» из 44 применимых проверок — это пороги 0.5–2 м,
   применённые к структурной невязке IDW (макс. 37 м). Для сходимости в точках скважин
   осмысленный порог — единицы метров; правила `domain/qaqc/` нужно уточнить.
6. **Фаза 2 — сценарная ось.** `variations:` есть (5 ветвей), но полноценная модель сценариев
   (`core/system_model.py`, `core/ensemble.py`) не доведена до UI/отчёта.
7. **Фаза 4 — генетический алгоритм.** QAQC-фитнес уже считается; нужно замкнуть цикл
   «мутация параметров → прогон → фитнес → отбор».
8. **Фаза 5 — UI.** Веб-слой работает; довести дерево шагов, граф ансамбля, панель QA/QC.
9. **Фаза 6 — SIS/циклиты (C12/C13/C14)** по онтологии.
10. **Динамика (`build_gdm`).** PVT/SCAL/дек в проектном графе есть, но симуляция не строится;
   `core/metrics.py` (КИН из `RESULTS`) готов к подключению.

---

## 8. QA/QC: два независимых слоя

| Слой | Модуль | Источник | Результат |
|---|---|---|---|
| Оцифрованные проверки качества | `domain/qaqc_adapter.py` + `domain/qaqc/` | пакет `check_<id>(data)` | `passed/failed/not_applicable`, `kq`, `kc`, `physical`, `fitness` |
| Доказательный вердикт | `domain/metacritic.py` | `qaqc_rules.csv` (6117 правил) | `passed/failed/unknown` |

Ключевое правило адаптера: **проверка без входных данных помечается `not_applicable`** и модель
не штрафует («отсутствие данных — не провал»). Поэтому «провалы» нельзя устранять подстановкой
нулей — только предоставлением реальных значений (п. 7.3) или уточнением порога (п. 7.4).
Адаптер **детерминирован**: один и тот же набор значений даёт один и тот же результат
(проверено тремя прогонами на Герасимовском).

Дополнительно `check_grid_geometry()` (в `core/coordinator.py`) — жёсткий инвариант геометрии
сетки: вырожденный Z (≈0) или нереальная мощность ⇒ предупреждение в отчёте.

---

## 9. Ансамбль и метрика

- **Оси вариаций** — `ontology_project/gerasimovskoe.yaml` → `variations:`. Каждая ветка =
  `{функция: {параметр: значение}}` (напр. `horizon_smooth: {radius: 100}`,
  `horizon_interpolate_by_marker_idw: {power_parameter: 3}`).
- **Ветки реально различаются**: параметры подставляются в соответствующую функцию воркфлоу.
- **Метрика** — `STOIIP` (суммарные запасы из волюметрии тНава); `best` = максимум.
- **Свёртка** — `core/rollup.py`: `best` | `pareto` | `p10_p50_p90`.
- **Число реализаций** — `execution.ensemble_size` (`0` = все вариации; `2` = быстрый прогон).
- Артефакты: `models/<vid>/<поле>.snp` (**открывается в GUI тНава**), `report.json → ensemble`.

---

## 10. Данные поля (`data/`)

`data/Герасимовское/Source/`:

| Файл/папка | Что это | Куда идёт |
|---|---|---|
| `Wellhead.txt` | координаты устьев, альтитуда | объекты `Wells` |
| `Welltop.txt` | отбивки (маркер, глубина) | маркеры (BAJ/J1/…) |
| `GERASIM_406_inkl/*.las` | инклинометрия (MD, зенит, азимут) | траектории `Wells/<скв>.txt` |
| `RIGIS/*.las` | ГИС (`PHIE, KINT, SW, VCL, LIT`) | логи скважин |
| `struct/*.irap` | структурные карты (`depth_u1`, faults, …) | горизонты, полигон вреза |
| `Координаты устья.xlsx` | исходный реестр устьев | справка |

Тип набора определяется автоматически (`core/datasets.py`): `logs`, `surfaces`, `wellheads`,
`welltops`, `core`, `seismic`, `production_history`, `decks`, `projects`, `archives`.

---

## 11. Онтология (`ontology/`)

Каталоги v4, читаемые как данные (`core/ontology.py`):

| Файл | Содержимое |
|---|---|
| `process_catalog.csv` | операции / стадии / подстадии (1272) |
| `tnavigator_functions.csv` | функции тНава (3257) |
| `data_parameter_catalog.csv` | параметры и их границы (403) |
| `qaqc_rules.csv` | QA/QC-правила (6117) |
| `software_mappings.csv` | привязки к ПО (414) |
| `GeoModelingEvolutionOntology_v4_AllInOne.rdf` | RDF-граф (грузится **лениво**, по запросу) |

Основной путь планирования — CSV (быстро и детерминированно); RDF — опционально.

---

## 12. Промпт для следующих реализаций

Скопируйте блок ниже в новую сессию LLM и допишите задачу в разделе «ЗАДАЧА».

````text
Ты работаешь с оркестратором ГГДМ в папке `orchestrator/` (tNavigator Python API v26.1).

ПРОЧТИ СНАЧАЛА:
- README.md            — архитектура, принципы, что реализовано;
- ontology_project/gerasimovskoe.yaml — стадии 0…10 (включая фации SIS), объекты, вариации;
- core/coordinator.py  — оркестровка (plan/run/_build_ensemble/_qaqc_values/_read_py_capture);
- domain/workflow_renderer.py — рендер .py-воркфлоу тНава;
- domain/templates/*.txt, domain/ontology_rules/*.rdf — шаблоны и правила функций.

ЖЁСТКИЕ ПРАВИЛА (не нарушать):
1. ДОМЕН — ТОЛЬКО В ДАННЫХ. Имена объектов, маркеры, пороги, пути, координаты — в
   config.yaml / ontology_project/*.yaml / domain/templates / domain/ontology_rules / ontology.
   В .py — ни одного имени поля/маркера/пути.
2. Новая функция тНава подключается ТРИАДОЙ:
   (а) domain/templates/<function>.txt — сырой шаблон ИЗ ЭТАЛОННОГО воркфлоу v26.1;
   (б) domain/ontology_rules/<function>.rdf — правило (параметры, входные/выходные объекты, шаблон_кода);
   (в) блок в ontology_project/gerasimovskoe.yaml: stage → function → parameters/objects/replace.
3. ПРОВЕРКА ПОСЛЕ КАЖДОЙ ПРАВКИ:
   python -X utf8 tests/test_v5.py            # ожидается 32/32
   python -X utf8 main.py preflight           # ожидается preflight: OK
   python -X utf8 main.py run --field Герасимовское   # dry-run: 33/33 шага, render_warnings=[]
   Реальный прогон: main.py run --field Герасимовское --execute  (~13 мин, нужна лицензия).
4. МОДЕЛЬ В ОТМЕТКАХ (Z < 0). В horizons_table порядок горизонтов — СНИЗУ ВВЕРХ
   (bottom-first), иначе тНав даёт нулевые толщины и «The resulting grid has no elements!».
5. ПРОГОН ВСЕГДА С ЧИСТОГО ПРОЕКТА: старый .snp/.snf удаляется перед запуском
   (иначе в проекте остаётся старый `main_grid` и шаг сетки падает).
6. НЕИЗВЕСТНОЕ ≠ ЛОЖЬ: QAQC-проверка без данных → not_applicable; правило без формализации →
   unknown (не false).
7. В шаблонах функций поля с большими вложенными структурами (зоны/фации чужого проекта,
   напр. `Litho3D`) надо отключать: use_zone=False, use_region=False, пустые find_object.
8. Проверяй факты по эталону: `domain/ontology_rules/reference_workflow.py` и
   `domain/templates/*.txt` — это машинный эталон v26.1, а не догадки.

ЗАДАЧА:
<опишите, что нужно сделать — например: «построить PORO из PHIE и добавить PERMX из KINT
на стадии 7» или «включить фации стадии 6 (LIT 0…8)»>

ФОРМАТ РАБОТЫ:
1. найди, где задача уже частично решена (поиск по имени функции тНава и по стадии);
2. сделай минимальную правку по правилам 1–8;
3. прогони dry-run; покажи, что изменилось (steps / qaqc / ensemble / grid_geometry);
4. обнови README.md (разделы 6 «Что реализовано» и 7 «Что нужно реализовать»);
5. при сомнении — НЕ выдумывай: проверь по эталонному воркфлоу или спроси.
````

---

## 13. Типовые проблемы и диагностика

| Симптом | Причина | Что делать |
|---|---|---|
| `The resulting grid has no elements!` | Порядок горизонтов в `horizons_table` (модель в отметках) **или** в проекте остался старый `main_grid` | Порядок — **снизу вверх**; прогон с чистого проекта (удаляется автоматически) |
| `Fail to add marker ... Well ... is not present in the project` | Регистр/синоним имени скважины в отбивках | `domain/welltops.py::normalize_marker_wells` (выполняется автоматически) |
| `MD length of some trajectory segments is smaller than the corresponding XYZ length` | Шум азимута у вертикальной скважины раздувает XYZ | `domain/trajectories.py`: минимальная кривизна + `MD ≥ |ΔXYZ|` |
| `Unable to create operation` (facies / interpolate) | Шаблон завязан на зоны/фации **чужого** проекта (`Litho3D`, `zone_id`) | Отключить зоны: `use_zone=False`, `use_region=False`, пустые `find_object` |
| В рендере чужие координаты (`min_x=2221900` и т.п.) | Шаблон функции несёт бокс обучающего набора, а в проектном YAML бокс не перекрыт | Задать локальный бокс в параметрах шага (`autodetect_box: False` + `min_x/min_y/length/step`); сверка — `workflow.foreign_tokens` в конфиге |
| Карта структурная/толщин «негеологичная» (пятна, чужой extent) | `map_2d_*`/`horizon_calculator` построились на чужом боксе | См. строку выше; проверить `checks.map_extent_tol_m` в QA/QC |
| Шаг в шине имеет статус `skipped_by_policy` | Решение структурного агента: врез не требуется (покрытие кровли отбивками ≥ порога) | Это штатное поведение; принудительно — `structural.erosion: on|off` в проектном YAML |
| Карта кровли «полосатая», максимум |ΔZ| в скважинах десятки метров, Bias ~6 м | Тренд не привязан к отбивкам: IDW без остаточной интерполяции (`use_residual_idw=False`) | Включить `use_residual_idw: True` (невязки «отбивка − тренд» интерполируются и прибавляются к тренду); проверить `struct.well_tie_rmse` |
| Кракозябры в выводе вместо кириллицы | Консоль Windows | Запускать с `-X utf8`; читать с `-Encoding UTF8` |
| Зависшие процессы `tNavigator-con` / «лицензия занята» | Не закрыто соединение | `TnavClient.close()` (в т.ч. `Connection.stop()`); перед прогоном снять зависшие процессы |
| `verdict = unknown` при dry-run | Нет реальных артефактов модели | Это ожидаемо без `--execute` |

**Где смотреть результаты прогона:**
`runs/run_<поле>/report.json` → `steps` (прогресс), `tnav` (rc/ошибка), `ensemble` (ветки + STOIIP + `best`),
`qaqc` (kq/kc/физичность + список `failed_checks`), `critic` (вердикт).
Сборка по ветвям — `models/<vid>/<поле>.snp` (`open_in_tnav` — открыть в GUI).

**Изменение поведения — где что лежит:**
`config.yaml` — пути, тНав, ансамбль, исполнение · `ontology_project/<поле>.yaml` — стадии, объекты,
маркеры, вариации · `domain/templates/<fn>.txt` — состав вызова функции ·
`domain/ontology_rules/<fn>.rdf` — параметры/объекты функции.

---

## 14. Тесты

```powershell
python -X utf8 tests/test_v5.py      # 32 проверки, печатает [OK ]/[FAIL]
python -X utf8 tests/test_agents.py  # 180 проверок агентного слоя (офлайн, без сети)
python -m pytest tests -q            # то же через pytest
```

Группы проверок: онтология как данные · сборка генов (assembler) · рендер воркфлоу
(`declare_workflow`, отступы, api_version) · метакритик (`UNKNOWN` сохраняется) ·
пайплайн/проектный граф (стадии, вариации, объекты) · защита геометрии сетки ·
траектории (минимальная кривизна, `MD ≥ |ΔXYZ|`) · нормализация имён скважин в отбивках.
Агентный слой (`tests/test_agents.py`): реестр BDI и карта этапов · гейты и политики
(`best|skip|halt|ask`, тумблер байпасса, waiver) · проверки, свидетельства и адаптеры
пакета QA/QC · rework-луп с файлами попыток и деградацией · меморандумы передачи
(evidence hash, lineage) · решения оператора (изоляция гейтов, журнал) · LLM-советник
и шлюз на фейковом клиенте (офлайн) · персистентность политик в `config.local.yaml` ·
решение структурного агента (`structure_policy`: покрытие отбивками, порог,
`erosion on|off`, пропуск шагов вреза `skipped_by_policy`) · агенты-политики
(`base_agent` + `grid_policy`/`facies_policy`: бокс сетки из extent карты, фации по
`geostat`, контракт `BaseAgent`) · RMSE сходимости
(`struct.well_tie_rmse`) · полный сброс `POST /api/reset` (сообщения + прогоны).
LLM-тесты не ходят в сеть и не меняют боевые конфиги (только tmp-каталоги).

---

## 15. Ключевые технические находки (неочевидное)

1. **Порядок горизонтов зависит от системы координат.** Модель Герасимовского — в **отметках**
   (отрицательные Z). тНав строит слои, интерпретируя `horizons_table` вдоль оси Z, поэтому
   горизонты нужно перечислять **снизу вверх**; иначе толщины нулевые и сетка пустая.
2. **Проект переиспользовать нельзя.** В сохранённом `.snp` остаётся `main_grid`, и шаг
   `grid_3d_create_by_horizons (mesh=find_object(name="main_grid"))` натыкается на старую сетку.
   Решение — всегда создавать проект с нуля.
3. **`run_py_code` не возвращает значение.** Отсюда единый «файловый канал»
   (`_read_py_capture`): py-сниппет пишет результат в tmp-файл, оркестратор его разбирает.
4. **тНав сам переводит MD → отметку** (по датуму скважины). Конвертировать отбивки в TVDSS
   в данных **нельзя** — получится двойное преобразование (~100 м ошибки).
5. **Сшивка скважин** (наблюдение vs модель) требует учёта наклона ствола: отметка отбивки —
   это Z ствола на глубине отбивки, а не `KB − MD` (иначе выбросы в сотни метров).
6. **Терминал обрезает вывод.** Длинные JSON-отчёты (несколько МБ) и кириллицу надёжнее
   писать в файл (`| Out-File <файл> -Encoding UTF8`) и читать файлом, а не из консоли.
7. **API 26.2 несовместим с 26.1.** `ConnectionOptions()` не принимает аргументы (поля —
   атрибутами после создания); импорт API из zip не годится для подключения
   (`tNavigator-API-client.exe` ищется рядом с `.py` → WinError 2) — нужна распаковка
   в `.tnav_api/`. Обе ветки покрыты `test_tnav_connection_options`.
8. **Лицензия `tnav://`** работает без опций: сервер/учётки — в `%APPDATA%\tNavigator.ini`
   (ключи `*_local`); `lic-set-file` по пути с кириллицей клиент не читает. Для `http(s)` —
   файл настроек в системном temp. Проверено живым прогоном: лицензия `API Client, API
   Server` + фичи `FEAT_GEOLOGY_DESIGNER` активируются.

## 16. Агенты, гейты и байпас

Агентный слой (`agents/`) читает 22 BDI-профиля, handoff-контракты и таблицы
решений из онтологии v4.1 (данные, не код). Агенты-политики этапов
(`BaseAgent` → `StructureAgent`/`GridAgent`/`FaciesAgent`) принимают решения по
данным проекта (рабочий интервал/врез, бокс сетки из extent карты, фации SIS:
метод/классы/вариограмма) и передают патчи параметров в рендер (`_variant_gene`);
решения попадают в отчёт (`structural`/`grid_policy`/`facies_policy`).
Пайплайн исполняется ПОЭТАПНО
(`execution.stage_mode: staged`): после каждого этапа гейт (расширенный
метакритик) выносит ДЕТЕРМИНИРОВАННЫЙ вердикт
(`passed|failed|bypassed|skipped|waived|pending_execution`). Передача следующему
агенту — только меморандумом HandoffMemo (ревизии артефактов, lineage, QA,
допущения, evidence hash); отклонённые ревизии сохраняются.

Политики исчерпания попыток (`on_exhausted`): `best` — лучшая ревизия и
продолжение с деградацией; `skip` — пропуск этапа; `halt` — остановка;
`ask` — пауза и решение оператора из интерфейса. Глобальный тумблер — «байпас
при исчерпании попыток»; выключен → жёсткий режим `halt`.

Переключение — из интерфейса (панель «Гейты и байпас»); значения сохраняются в
`config.local.yaml` (`execution.gate_bypass`, `gates_override.*`; базовый
`config.yaml` не меняется) и применяются к следующим прогонам:

* `GET /api/gates` — текущие политики; `PUT /api/gates` — переключение из панели;
* `POST /api/runs/{id}/gates/{gid}/resolve` — решение по ожидающему гейту
  (`best|skip|halt|waiver`, автор и комментарий → аудит в `gate_decisions`).

Артефакты прогона: `runs/<id>/agents/` — `progress.json` (вердикты этапов),
`gates/*.json`, `handoffs/*.json`, `stages/NN_<gate>.py` (воркфлоу каждого этапа).
В dry-run runtime-проверки не выполняются, гейты помечаются `pending_execution`
— «неизвестное ≠ ложь» (не штрафует модель). `passed` в dry-run получают только
этапы с реально применившимися статическими проверками (например, G-DATA).

Вердикт пополняется из данных: пакет QA/QC по блокам этапа
(`checks.package_blocks` → `kq/kc/физичность`; нужен `numpy` — без него деградация
без штрафа) и диапазоны параметров онтологии; провал попытки запускает rework по
кандидатам из проектных `variations` (до `max_attempts`, попытки сохраняются как
`gates/<gate>.attemptN.json`). В рендере каждого этапа ищутся чужие токены
исходного проекта (`workflow.foreign_tokens`) — находка видна в отчётах и
меморандумах, но вердикт не фабрикует. Пояснение к провалу (не заменяет вердикт)
формирует LLM-советник (`agents/prompts/verify.md`; без ключа — молчит).

Логи тНава и таймаут: `TnavClient.run_workflow` ограничен `tnavigator.timeout_sec`
(зависший вызов не блокирует прогон). Панель «Прогресс» показывает фазу (подготовка →
рендер → исполнение тНава → QA/QC → ансамбль), этап `N/M` и проценты; WebSocket
отдаёт кадр каждые 0.5 с (heartbeat), после перезагрузки страницы статусы
добираются поллингом.

Карты: стадия «10. Экспорт карт» вызывает `create_screenshot` (изолинии
`contour_line_settings_step/style`, палитра, PNG 1200×600) и кладёт файлы в
`runs/<id>/maps/`; если headless-рендер не дал PNG — координатор дорисовывает
карты фолбэком `domain/map_render.py` (matplotlib, источники — `checks.map_sources`).
Гейт `G-MAPS` проверяет наличие ожидаемых карт (`checks.map_files`), API отдаёт их
списком (`GET /api/runs/{id}/maps`) и файлом (`…/maps/{file}`), панель «Карты»
показывает превью. Кнопка «▶ Запустить» шлёт `POST /api/runs` — запуск не зависит
от разбора запроса LLM.

---

*Папка собрана как самодостаточная сборка: код + онтология v4 + данные поля.
Внешним остаётся только tNavigator (`tnavigator.install_dir` / `executable` в `config.yaml`).*






