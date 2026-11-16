!!! РЕЖИМ --execute (аудит артефактов, прогон НЕ запускаю): реальный прогон тНава (нужна лицензия, ~13 мин на ветвь)
[WARN] в системе есть процессы tNavigator — возможен «залипший» API (см. открытый вопрос 5 PLAN). Вывод tasklist:

Image Name                     PID Session Name        Session#    Mem Usage
========================= ======== ================ =========== ============
tNavigator.exe               30764 RDP-Tcp#2                  1    260 964 K
tNavigator-API-client.exe    27848 RDP-Tcp#2                  1     54 552 K
tNavigator-con.exe           31484 RDP-Tcp#2                  1    397 524 K

=== 1. ОБЯЗАТЕЛЬНЫЕ ТЕСТЫ (python) ===
  tests/test_v5.py: пройдено 32, провалено 0 (exit=0)
  tests/test_agents.py: пройдено 223, провалено 0 (exit=0)
  tests/test_base_agent.py: пройдено 39, провалено 0 (exit=0)

=== 1b. ТЕСТ АУДИТА ХАРДКОДА ===
  exit=0, итог: (4, 0); долг: известный долг есть

=== 1c. ТЕСТЫ УЧАСТНИКОВ ===
  tests/test_contracts.py: пройдено 107, провалено 0 (exit=0)
  tests/test_qaqc_checks.py: пройдено 55, провалено 0 (exit=0)
  tests/test_structural_agent.py: пройдено 69, провалено 0 (exit=0)
  tests/test_facies_agent.py: пройдено 44, провалено 0 (exit=0)
  tests/test_petro_agent.py: пройдено 78, провалено 0 (exit=0)
  найдено тестов участников: 5/5

=== 1d. ПЕРЕСЧЁТ ЧЕРЕЗ pytest (скрытые ошибки импорта) ===
[WARN] pytest пропущен (--skip-heavy)

=== 2. PREFLIGHT ===
  exit=0; строка 'preflight: OK': True

=== 3. DRY-RUN + ИНВАРИАНТЫ ОТЧЁТА ===
  прогон не запускаю (--from-artifacts): читаю артефакты существующего прогона
  читаю СОХРАНЁННЫЙ отчёт реального прогона: runs\artifacts\execute_20261009_193040\report_execute.json
  steps: total=49 done=47 error=0 pending_template=0 skipped_by_policy=2
  render_warnings=[]
[WARN] skipped_by_policy=2 (на базовой линии был ровно 1 — шаг вреза)

=== 4. QA/QC В ОТЧЁТЕ ВЕРХНЕГО УРОВНЯ ===
  qaqc: total=712 passed=12 failed=32 not_applicable=661 kq=0.0 kc=0.2791 physical=False
[WARN] qaqc.failed > 0 на dry-run — проверить, что это не «нет данных = провал»
  qaqc_coverage.json есть; заявленный охват: 6065

=== 5. МЕСТА QA/QC В АРТЕФАКТАХ ===
  карт PNG в runs/<id>/maps/: 7: ['HCPV', 'NetVolume', 'PERM', 'PoreVolume', 'PORO', 'Tl_thick', 'U1_top']
  ожидаемые карты (checks.map_files): ['U1_top', 'Tl_thick', 'PORO', 'PERM', 'STOIIP', 'HCPV', 'PoreVolume', 'NetVolume']
  построено: ['U1_top', 'Tl_thick', 'PORO', 'PERM', 'HCPV', 'PoreVolume', 'NetVolume']; НЕТ PNG: ['STOIIP']
[FAIL] E9: построено 7 из 8 ожидаемых карт (требование ≥8) — нет ['STOIIP']
    Tl_thick.txt: ячеек 78312, непустых 41714 (53.3%)
    PORO.txt: ячеек 77500, непустых 41125 (53.1%)
    PERM.txt: ячеек 77500, непустых 41125 (53.1%)
    STOIIP.txt: ячеек 77500, непустых 0 (0.0%)  <-- ПУСТОЙ ЭКСПОРТ
[FAIL] E9: экспорт STOIIP.txt полностью пуст (все значения = novalue) — карта не содержит данных
    HCPV.txt: ячеек 77500, непустых 41035 (52.9%)
    PoreVolume.txt: ячеек 77500, непустых 41035 (52.9%)
    NetVolume.txt: ячеек 77500, непустых 41125 (53.1%)
  ветвей ансамбля в отчёте: 5
  ветвей ok: 0/5; metric заполнена у 0
    S001: ok=False metric=None qaqc={p:12, f:32, na:549, kq:0.0, kc:0.2791} err=Error occurred while running workflow.
Error type: RuntimeEr
    S002: ok=False metric=None qaqc={p:12, f:32, na:549, kq:0.0, kc:0.2791} err=Error occurred while running workflow.
Error type: RuntimeEr
    S003: ok=False metric=None qaqc={p:12, f:32, na:549, kq:0.0, kc:0.2791} err=Error occurred while running workflow.
Error type: RuntimeEr
    S004: ok=False metric=None qaqc={p:12, f:32, na:549, kq:0.0, kc:0.2791} err=Error occurred while running workflow.
Error type: RuntimeEr
    S005: ok=False metric=None qaqc={p:12, f:32, na:549, kq:0.0, kc:0.2791} err=Error occurred while running workflow.
Error type: RuntimeEr
[FAIL] --execute: ни одна ветвь ансамбля не завершилась успешно
  отрендеренный воркфлоу: строк 3960, begin_wf_item=48
[FAIL] в воркфлоу 48 блоков begin_wf_item, а done-шагов 47 (шаг без блока или блок без шага)
  чужые токены обучения в рендере: нет (всего проверено 8)

=== 6. РЕАЛЬНЫЙ ПРОГОН (--execute) ===
  tnav: ok=False kind=staged error=Error occurred while running workflow.
Error type: RuntimeError
Error location:  in Structure_modeling () in item 2 ("Fa
[FAIL] реальный прогон тНава не ok: Error occurred while running workflow.
Error type: RuntimeError
Error location:  in Structure_modeling () in item 2 ("Facies Modelling (Zones, Regions)")
Error message: Error while launching calculation: Parameter "Grid" (in group "Input") is not specified!
    ветка S001: проект НЕТ (Герасимовское.snp)
[WARN] ветка S001: нет файла проекта D:\Documents\GIT\ГеоМАС\orchestrator_v8\models\S001\Герасимовское.snp — кубы FACIES/PORO/PERM не доказаны артефактом
    ветка S002: проект НЕТ (Герасимовское.snp)
[WARN] ветка S002: нет файла проекта D:\Documents\GIT\ГеоМАС\orchestrator_v8\models\S002\Герасимовское.snp — кубы FACIES/PORO/PERM не доказаны артефактом
    ветка S003: проект НЕТ (Герасимовское.snp)
[WARN] ветка S003: нет файла проекта D:\Documents\GIT\ГеоМАС\orchestrator_v8\models\S003\Герасимовское.snp — кубы FACIES/PORO/PERM не доказаны артефактом
    ветка S004: проект НЕТ (Герасимовское.snp)
[WARN] ветка S004: нет файла проекта D:\Documents\GIT\ГеоМАС\orchestrator_v8\models\S004\Герасимовское.snp — кубы FACIES/PORO/PERM не доказаны артефактом
    ветка S005: проект НЕТ (Герасимовское.snp)
[WARN] ветка S005: нет файла проекта D:\Documents\GIT\ГеоМАС\orchestrator_v8\models\S005\Герасимовское.snp — кубы FACIES/PORO/PERM не доказаны артефактом

=== ИТОГ (chain) ===
FAIL: 5 | WARN: 9
