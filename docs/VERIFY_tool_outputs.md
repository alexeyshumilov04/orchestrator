# VERIFY - сырые выводы инструментов (замороженный прогон 2026-10-09 18:54)


## tests/test_verify_triads.py  (exit=0)

``
эталон (AST): 12 функций: horizon_calculator, horizon_export_cps_format, horizon_interpolate_by_marker_idw, horizon_smooth, map_2d_distance_to_marker, map_2d_export_cps_format, map_2d_interpolate, marker_create_by_horizon, marker_export_well_marker_table_format, polygon_create_by_map_2d_boundary, wells_attribute_export, wells_attribute_thickness_calculation

=== A. ТРИАДЫ (правило 2): объявлено функций 30 ===
[OK  ] blocked_well_log_change_type                     template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:5. Апскейлинг ГИС на сетку (blocked wells)
[OK  ] contact_create_by_horizon                        template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:8. Насыщение (контакты OWC/GOC)
[OK  ] create_blocked_well_log                          template=True rdf=True yaml_block=True шагов=3 где=gerasimovskoe.yaml:functions
[OK  ] create_object_template                           template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:5. Апскейлинг ГИС на сетку (blocked wells)
[OK  ] fault_import_sticks_xyz_format                   template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:0. Импорт данных Герасимовского
[OK  ] geobody_create_by_property                       template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:6.1 Геологические тела (geobodies из фаций)
[OK  ] grid_3d_create_by_horizons                       template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:4. Структурная 3D-модель и сетка (corner-point)
[OK  ] grid_property_create_volumetric_properties       template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:functions
[OK  ] grid_property_facies_modeling                    template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:6. Фации (дискретный куб FACIES)
[OK  ] grid_property_interpolate_by_wells_log_3d        template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:functions
[OK  ] horizon_export_cps_format                        template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:1. Структурные поверхности: горизонты
[OK  ] horizon_import_ascii_format                      template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:0. Импорт данных Герасимовского
[OK  ] horizon_interpolate_by_marker_idw                template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:functions
[OK  ] horizon_smooth                                   template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:functions
[OK  ] map_2d_calculator                                template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:2. Толщины и 2D-тренды
[OK  ] map_2d_create_by_grid_property                   template=True rdf=True yaml_block=True шагов=6 где=gerasimovskoe.yaml:10. Экспорт карт
[OK  ] map_2d_distance_to_marker                        template=True rdf=True yaml_block=True шагов=0 где=gerasimovskoe.yaml:functions
[OK  ] map_2d_export_ascii_format                       template=True rdf=True yaml_block=True шагов=7 где=gerasimovskoe.yaml:10. Экспорт карт
[OK  ] map_2d_export_cps_format                         template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:2. Толщины и 2D-тренды
[OK  ] map_2d_smooth                                    template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:2. Толщины и 2D-тренды
[OK  ] marker_export_well_marker_table_format           template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:1. Структурные поверхности: горизонты
[OK  ] marker_import_txt_format                         template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:0. Импорт данных Герасимовского
[OK  ] object_template_mapping                          template=True rdf=True yaml_block=True шагов=2 где=gerasimovskoe.yaml:5. Апскейлинг ГИС на сетку (blocked wells)
[OK  ] polygon_create_by_map_2d_boundary                template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:functions
[OK  ] polygon_create_by_map_intersection               template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:3. Полигон вреза (эрозия)
[OK  ] polygon_import_txt_format                        template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:0. Импорт данных Герасимовского
[OK  ] wells_attribute_export                           template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:2. Толщины и 2D-тренды
[OK  ] wells_attribute_thickness_calculation            template=True rdf=True yaml_block=True шагов=0 где=gerasimovskoe.yaml:functions
[OK  ] wells_import_path_deviation_format               template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:0. Импорт данных Герасимовского
[OK  ] wells_log_import_las_format                      template=True rdf=True yaml_block=True шагов=1 где=gerasimovskoe.yaml:0. Импорт данных Герасимовского
[info] шаги без явных parameters/objects/replace (дефолты шаблона): polygon_import_txt_format

=== B/C/D/E. ИСТОЧНИК ШАБЛОНА и АРГУМЕНТЫ (правило 8) ===
корпус источников v7/v8: 1093 файлов
базовых шаблонов по манифесту: 33; текущих: 42
НОВЫХ шаблонов: 10: grid_property_create_by_values, grid_property_create_by_zones, grid_property_facies_modeling, horizon_export_cps_format, map_2d_create_by_grid_property, map_2d_export_ascii_format, map_2d_export_cps_format, marker_export_well_marker_table_format, polygon_create_by_map_2d_boundary, wells_attribute_export
[OK  ] blocked_well_log_change_type                     документ: orchestrator_v7\orchestrator\models\S001\06_5_Апскейлинг_ГИС_на_сетку_blocked_wells.py
       └ ключи YAML (1) все найдены в шаблоне
[OK  ] contact_create_by_horizon                        документ: orchestrator_v7\orchestrator\models\S001\10_8_Насыщение_контакты_OWC_GOC.py
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] create_blocked_well_log                          документ: orchestrator_v7\orchestrator\docs\tasks\B3_petrophysics.md
       └ ключи YAML (5) все найдены в шаблоне
[OK  ] create_object_template                           документ: orchestrator_v7\orchestrator\docs\tasks\B4_facies.md
[OK  ] create_screenshot                                документ: orchestrator_v7\orchestrator\api.py
[OK  ] fault_import_sticks_xyz_format                   документ: orchestrator_v7\orchestrator\models\S001\01_0_Импорт_данных_Герасимовского.py
[OK  ] geobody_create_by_property                       документ: orchestrator_v7\orchestrator\models\S001\08_6_1_Геологические_тела_geobodies_из_фаци.py
       └ ключи YAML (3) все найдены в шаблоне
[OK  ] grid_3d_create_by_horizons                       документ: orchestrator_v7\orchestrator\README_module.md
       └ ключи YAML (16) все найдены в шаблоне
[OK  ] grid_3d_create_by_horizons_with_faults           документ: orchestrator_v7\orchestrator\domain\templates\grid_3d_create_by_horizons_with_faults.txt
[OK  ] grid_property_calculator                         документ: orchestrator_v7\orchestrator\docs\tasks\B4_facies.md
[OK  ] grid_property_create_by_values                   документ: orchestrator_v7\orchestrator\docs\tasks\B4_facies.md
[WARN] правило 8: grid_property_create_by_zones: цитата из комментария не найдена ни в одном источнике — проверить вручную: ['Этот расчёт позволяет создать зоны по Z. Созданное ДИСКРЕТНО']
[OK  ] grid_property_create_by_zones                    документ: orchestrator_v7\orchestrator\docs\tasks\B4_facies.md
[OK  ] grid_property_create_volumetric_properties       документ: orchestrator_v7\orchestrator\models\S001\11_9_Волюметрия_запасы.py
       └ ключи YAML (1) все найдены в шаблоне
[OK  ] grid_property_facies_by_wells_log_3d             документ: orchestrator_v7\orchestrator\domain\templates\grid_property_facies_by_wells_log_3d.txt
[WARN] правило 8: grid_property_facies_modeling: цитата из комментария не найдена ни в одном источнике — проверить вручную: ['Этот расчёт позволяет создать ДИСКРЕТНОЕ свойство по объекту']
[OK  ] grid_property_facies_modeling                    документ: orchestrator_v7\orchestrator\models\S001\07_6_Фации_SIS.py
[OK  ] grid_property_interpolate_by_blocked_wells_trivial_3d документ: orchestrator_v7\orchestrator\domain\templates\grid_property_interpolate_by_blocked_wells_trivial_3d.txt
[OK  ] grid_property_interpolate_by_wells_log_3d        документ: orchestrator_v7\orchestrator\docs\tasks\B3_petrophysics.md
       └ ключи YAML (3) все найдены в шаблоне
[OK  ] horizon_calculator                               эталон, аргументов 30/30
[OK  ] horizon_export_cps_format                        эталон, аргументов 7/7
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] horizon_import_ascii_format                      документ: orchestrator_v7\orchestrator\models\S001\01_0_Импорт_данных_Герасимовского.py
       └ ключи YAML (1) все найдены в шаблоне
[OK  ] horizon_interpolate_by_marker_idw                эталон, аргументов 42/42
       └ ключи YAML (16) все найдены в шаблоне
[OK  ] horizon_smooth                                   эталон, аргументов 11/11
       └ ключи YAML (3) все найдены в шаблоне
[OK  ] map_2d_calculator                                документ: orchestrator_v7\orchestrator\models\S001\03_2_Толщины_и_2D_тренды.py
       └ ключи YAML (12) все найдены в шаблоне
[OK  ] map_2d_create_by_grid_property                   документ: orchestrator_v8\docs\03_AGENTS.md
       └ ключи YAML (3) все найдены в шаблоне
[OK  ] map_2d_distance_to_marker                        эталон, аргументов 34/34
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] map_2d_export_ascii_format                       документ: orchestrator_v8\tools\probe_maps.py
       └ ключи YAML (3) все найдены в шаблоне
[OK  ] map_2d_export_cps_format                         эталон, аргументов 6/6
       └ ключи YAML (3) все найдены в шаблоне
[OK  ] map_2d_import_ascii_format                       документ: orchestrator_v7\orchestrator\domain\templates\map_2d_import_ascii_format.txt
[WARN] правило 8: map_2d_interpolate: аргументы шаблона отсутствуют в эталоне: ['use', 'well_attribute'] [базовый]
[OK  ] map_2d_interpolate                               эталон, аргументов 213/215, лишние=['use', 'well_attribute']
[OK  ] map_2d_smooth                                    документ: orchestrator_v7\orchestrator\models\S001\03_2_Толщины_и_2D_тренды.py
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] map_2d_thickness_map                             документ: orchestrator_v7\orchestrator\domain\templates\map_2d_thickness_map.txt
[OK  ] marker_create_by_horyzon                         документ: orchestrator_v7\orchestrator\tests\test_agents.py
[WARN] правило 8: marker_export_well_marker_table_format: аргументы шаблона отсутствуют в эталоне: ['marker', 'use'] [НОВЫЙ шаблон]
[OK  ] marker_export_well_marker_table_format           эталон, аргументов 20/22, лишние=['marker', 'use']
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] marker_import_txt_format                         документ: orchestrator_v7\orchestrator\models\S001\01_0_Импорт_данных_Герасимовского.py
       └ ключи YAML (1) все найдены в шаблоне
[OK  ] object_template_mapping                          документ: orchestrator_v7\orchestrator\models\S001\06_5_Апскейлинг_ГИС_на_сетку_blocked_wells.py
       └ ключи YAML (1) все найдены в шаблоне
[OK  ] polygon_create_by_map_2d_boundary                эталон, аргументов 6/6
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] polygon_create_by_map_intersection               документ: orchestrator_v7\orchestrator\models\S001\04_3_Полигон_вреза_эрозия.py
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] polygon_import_txt_format                        документ: orchestrator_v7\orchestrator\models\S001\01_0_Импорт_данных_Герасимовского.py
[WARN] правило 8: wells_attribute_export: аргументы шаблона отсутствуют в эталоне: ['attribute_name'] [НОВЫЙ шаблон]
[OK  ] wells_attribute_export                           эталон, аргументов 11/12, лишние=['attribute_name']
       └ ключи YAML (2) все найдены в шаблоне
[OK  ] wells_attribute_thickness_calculation            эталон, аргументов 24/24
       └ ключи YAML (4) все найдены в шаблоне
[OK  ] wells_import_path_deviation_format               документ: orchestrator_v7\orchestrator\models\S001\01_0_Импорт_данных_Герасимовского.py
       └ ключи YAML (1) все найдены в шаблоне
[OK  ] wells_log_import_las_format                      документ: orchestrator_v7\orchestrator\models\S001\01_0_Импорт_данных_Герасимовского.py
       └ ключи YAML (1) все найдены в шаблоне

=== F. ФУНКЦИИ ЭТАЛОНА БЕЗ ТРИАДЫ ===
[WARN] эталон содержит marker_create_by_horizon(), но триады в v8 нет (шаг не рендерится)
   при этом в пайплайн НЕ включены: horizon_calculator, map_2d_interpolate, marker_create_by_horizon

=== G. ПРАВИЛО 4: ПОРЯДОК ГОРИЗОНТОВ В СЕТКЕ (bottom-first) ===
маркеры: кровля BAJ -> U1_top; подошва J2 -> U1_bot; шагов сетки: 1
  grid_3d_create_by_horizons: строки horizons_table ['Top', 'Bot'] -> после replace ['U1_bot', 'U1_top']
  [OK ] правило 4: grid_3d_create_by_horizons: снизу вверх (U1_bot … U1_top)

=== ИТОГ (triads) ===
FAIL: 0 | WARN: 6 | функций в YAML: 30 | шаблонов: 42 | правил: 42 | новых шаблонов: 10
``


## tests/test_verify_hardcode.py  (exit=0)

``
токенов СХЕМЫ/API (не домен): 2949
токенов домена собрано ИЗ ДАННЫХ: 91
allow: 6 шт. в 5 файлах; known_debt: 24 позиций в 6 файлах (базовая линия 26)

=== 3. СКАН В ГРАНИЦАХ ОФИЦИАЛЬНОГО ТЕСТА (agents/ core/ domain/ без qaqc) ===
совпадений всего: 14 | разрешено allow: 0 | объявлено в known_debt: 14 | НЕ ОБЪЯВЛЕНО: 0
       [долг] core/coordinator.py:515: literal «main_grid» домен «main_grid»
       [долг] core/coordinator.py:646: literal «main_grid» домен «main_grid»
       [долг] core/coordinator.py:515: literal «main_grid» домен «main_grid»
       [долг] core/coordinator.py:646: literal «main_grid» домен «main_grid»
       [долг] core/coordinator.py:37: name «_STOIIP_TMP» домен «STOIIP»
       [долг] core/coordinator.py:634: name «_STOIIP_TMP» домен «STOIIP»
       [долг] core/coordinator.py:633: name «_STOIIP_TMP» домен «STOIIP»
       [долг] core/ensemble.py:99: literal «базовая ГМ» домен «базовая»
       [долг] core/ensemble.py:38: literal «базовая (без вариаций)» домен «базовая»
       [долг] core/ensemble.py:108: literal «S001» домен «S001»
       [долг] domain/geostat.py:170: literal «PHIE» домен «PHIE»
       [долг] domain/geostat.py:171: literal «KINT» домен «KINT»
       [долг] domain/trajectories.py:244: literal «Boundary» домен «Boundary»
       [долг] domain/welltops.py:14: literal «BAJ» домен «BAJ»

=== 3b. domain/qaqc/ (официальный тест исключает каталог целиком) ===
совпадений: 38 в файлах: {'domain/qaqc/check_functions.py': 6, 'domain/qaqc/checks.py': 21, 'domain/qaqc/parameters.py': 11}
НЕ объявлено в данных: 38; в known_debt: 0
из них доменный ТОКЕН дословно присутствует в исходных CSV пакета: 33/38 (87%) -> производные данные (текст проверок), не рукописный домен
[info] не выводятся из CSV пакета (5) — ручная оценка (наследованные сгенерированные файлы: parameters.py — лист «Обозначения_параметров», генератор и исходная книга в репозитории отсутствуют):
       [info] domain/qaqc/parameters.py:54: literal «HCPV» ['HCPV']
       [info] domain/qaqc/parameters.py:331: literal «KINT» ['KINT']
       [info] domain/qaqc/parameters.py:54: literal «HCPV» ['HCPV']
       [info] domain/qaqc/parameters.py:331: literal «KINT» ['KINT']
       [info] domain/qaqc/parameters.py:331: literal «KINT» ['KINT']
checks_table.csv: 714 строк; CHECKS (исполняемых): 707; строк со способом unknown: 7

=== 3c. ВНЕ официального скана (ontology/, tests/) — информационно ===
ontology/: совпадений 4, из них НЕ объявлено в данных: 4
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:557: literal «
FIELD_NAME|Название месторождения|string|none|registered na» домен ['STOIIP']
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:595: literal «
RESERVOIR_NAME|Название пласта / резервуара|string|none|reg» домен ['STOIIP']
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:767: literal «
GRID_NAME|Имя сетки|string|none|unique in model version|dup» домен ['HCPV']
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:419: literal «Выбор типа и масштаба сетки|Pillar/corner-point/PEBI framewo» домен ['STOIIP']
tests/: совпадений 63, из них НЕ объявлено в данных: 63
       [info] tests/test_agents.py:367: literal «Герасимовское» домен ['Герасимовское']
       [info] tests/test_agents.py:560: literal «BAJ» домен ['BAJ']
       [info] tests/test_agents.py:593: literal «staged-skip: толщина отрендерена (Tl_thick в wf02)» домен ['Tl_thick']
       [info] tests/test_agents.py:760: literal «main_grid» домен ['main_grid']
       [info] tests/test_agents.py:762: literal «BAJ» домен ['BAJ']
       [info] tests/test_agents.py:781: literal «probes: STOIIP в свидетельствах» домен ['STOIIP']
       [info] tests/test_agents.py:1168: literal «pipeline: U1_bot (подошва Ю1) — строится по маркеру J2 на эт» домен ['U1_bot']
       [info] tests/test_agents.py:1174: literal «pipeline: толщина Tl_thick = U1_top − U1_bot (кровля − подош» домен ['U1_top', 'U1_bot']
       [info] tests/test_agents.py:1179: literal «pipeline: U1_top (кровля Ю1) — с сейсмическим трендом + resi» домен ['U1_top']
       [info] tests/test_agents.py:173: literal «Герасимовское» домен ['Герасимовское']
       … ещё 53
       (правило 1 про рантайм; ontology/*.py — скрипты-генераторы, tests/ — проверки; фиксируется как зона без автоматического контроля)

=== 4. «МЁРТВЫЙ» ДОЛГ (позиция объявлена, но в файле её нет) ===
мёртвых позиций долга: 0

=== 5. ЧИСЛОВЫЕ ПОРОГИ ИЗ ДАННЫХ, ЗАШИТЫЕ В КОД (информационно) ===
       [info] 0.02 = порог config:gerasimovskoe.yaml:thresholds.poro: 2 мест, напр. domain/ontology_rules/reference_workflow.py:353, domain/ontology_rules/reference_workflow.py:808
       [info] 0.1 = порог config:gerasimovskoe.yaml:thresholds.perm: 3 мест, напр. core/llm_gateway.py:98, domain/ontology_rules/reference_workflow.py:504, domain/ontology_rules/reference_workflow.py:959
       [info] 0.5 = порог config:checks.fitness_alpha: 22 мест, напр. agents/base_agent.py:49, agents/checks/builtin.py:181, agents/checks/builtin.py:198, agents/checks/report.py:191
       [info] 0.6 = порог config:gerasimovskoe.yaml:thresholds.swl: 1 мест, напр. domain/geostat.py:277
       [info] 20.0 = порог config:checks.grid_max_xy_ratio: 7 мест, напр. agents/checks/adapters.py:89, agents/contracts.py:43, core/coordinator.py:156, domain/ontology_rules/reference_workflow.py:356
       [info] 100.0 = порог config:checks.map_extent_tol_m: 7 мест, напр. agents/checks/base.py:407, core/pipeline.py:77, core/rollup.py:36, core/runner.py:65
       [info] 200.0 = порог config:checks.grid_max_aspect_ratio: 10 мест, напр. agents/checks/adapters.py:94, agents/checks/adapters.py:154, agents/checks/base.py:608, agents/checks/base.py:610
       [info] 5000.0 = порог config:gerasimovskoe.yaml:thresholds.perm: 1 мест, напр. core/coordinator.py:52
       [info] 1000000.0 = порог config:checks.blank_abs: 2 мест, напр. core/metrics.py:19, domain/irap.py:30
значимых совпадений с порогами: 55 (9 разных значений) — оценивать вручную

=== 6. КЛЮЧИ ДАННЫХ, КОТОРЫЕ НЕ ЧИТАЕТ КОД (мёртвые настройки) ===
листовых ключей config.yaml: 101; имя НЕ встречается в коде: 9
       [info] checks.map_sources.Tl_thick = ''
       [info] checks.map_sources.U1_bot = ''
       [info] checks.map_sources.U1_top = 'struct/depth_u1.irap'
       [info] execution.build_gdm = True
       [info] execution.build_gm = True
       [info] execution.render_workflow = True
       [info] llm.provider = 'openai_compatible'
       [info] workflow.reference = 'domain/ontology_rules/reference_workflo
       [info] workflow.transitions = 'domain/ontology_rules/transitions.xlsx'

=== 7. ПОХОЖИЕ ИМЕНА КЛЮЧЕЙ (возможная опечатка данных/кода) ===
[WARN] ключ данных `workflow.transitions` не читается; в коде есть похожие имена ['transition'] -> вероятная опечатка в имени ключа
подозрительных пар: 1

=== ИТОГ (hardcode) ===
нарушений правила 1 в ОФИЦИАЛЬНОМ скане (agents/core/domain без qaqc): 0
domain/qaqc/** — ВНЕ официального скана (сгенерированные данные пакета): 38 совпадений домена; это не долг нового кода (см. разбор производности выше)
``


## tests/test_verify_rule6.py  (exit=0)

``
=== 1. МОЛЧАЛИВОЕ ГЛУШЕНИЕ ОШИБОК (except: pass/continue) ===
[WARN] правило 6: agents/checks/base.py:452: except → pass (QA/QC-путь; далее есть продолжение/фолбэк — проверить, что результат не теряется)
[WARN] правило 6: agents/checks/builtin.py:161: except → continue (QA/QC-путь; далее есть продолжение/фолбэк — проверить, что результат не теряется)
[WARN] правило 6: agents/checks/report.py:376: except → pass (QA/QC-путь; далее есть продолжение/фолбэк — проверить, что результат не теряется)
[WARN] правило 6: agents/decisions.py:37: except → pass
[WARN] правило 6: agents/evidence.py:44: except → continue
[WARN] правило 6: agents/facies.py:443: except → pass
[WARN] правило 6: agents/grid.py:204: except → continue
[WARN] правило 6: agents/knowledge.py:136: except → continue
[WARN] правило 6: agents/runner.py:370: except → pass
[WARN] правило 6: agents/runner.py:563: except → pass
[WARN] правило 6: agents/runner.py:87: except → pass
[WARN] правило 6: agents/runner.py:164: except → pass
[WARN] правило 6: agents/runner.py:355: except → pass
[WARN] правило 6: agents/runner.py:363: except → pass
[WARN] правило 6: agents/runner.py:521: except → continue
[WARN] правило 6: agents/runner.py:294: except → pass
[WARN] правило 6: agents/saturation.py:98: except → continue
[WARN] правило 6: core/coordinator.py:602: except → pass
[WARN] правило 6: core/coordinator.py:757: except → continue
[WARN] правило 6: core/coordinator.py:227: except → pass
[WARN] правило 6: core/coordinator.py:308: except → pass
[WARN] правило 6: core/coordinator.py:434: except → pass
[WARN] правило 6: core/coordinator.py:727: except → continue
[WARN] правило 6: core/pipeline.py:51: except → pass
[WARN] правило 6: domain/geostat.py:158: except → continue
[WARN] правило 6: domain/qaqc/primitives.py:48: except → pass (QA/QC-путь; далее есть продолжение/фолбэк — проверить, что результат не теряется)
[WARN] правило 6: domain/qc/maps.py:43: except → continue (QA/QC-путь; далее есть продолжение/фолбэк — проверить, что результат не теряется)
[WARN] правило 6: domain/qc/maps.py:228: except → continue (QA/QC-путь; далее есть продолжение/фолбэк — проверить, что результат не теряется)
[WARN] правило 6: domain/tnav_client.py:243: except → pass
[WARN] правило 6: domain/tnav_client.py:131: except → pass
[WARN] правило 6: domain/tnav_client.py:336: except → pass
[WARN] правило 6: domain/tnav_client.py:456: except → pass
[WARN] правило 6: domain/tnav_client.py:466: except → pass
[WARN] правило 6: domain/trajectories.py:80: except → continue
[WARN] правило 6: domain/trajectories.py:105: except → continue
[WARN] правило 6: domain/welltops.py:32: except → continue
всего мест с молчаливым глушением: 36; из них скрывают результат: 0

=== 2. ПОДСТАНОВКА НУЛЯ ВМЕСТО ОТСУТСТВУЮЩИХ ДАННЫХ ===
       [info] agents/base_agent.py:159: self.cfg.get("agents.policy.hybrid_threshold", 0.0) or 0.0)}
       [info] agents/base_agent.py:191: ratio = (len(known) / total) if total else 0.0
       [info] agents/checks/base.py:118: out[o.state] = out.get(o.state, 0) + 1
       [info] agents/checks/base.py:781: gates[c.gate] = gates.get(c.gate, 0) + 1
       [info] agents/checks/base.py:782: sources[c.source] = sources.get(c.source, 0) + 1
       [info] agents/checks/builtin.py:90: total = int(m.get("total") or 0)
       [info] agents/checks/builtin.py:93: share = int(m.get("blank") or 0) / total
       [info] agents/checks/builtin.py:140: written = int(tr.get("written") or 0)
       [info] agents/checks/builtin.py:141: skipped = int(tr.get("skipped") or 0)
       [info] agents/checks/builtin.py:393: n_facies = int(pol.get("n_facies") or 0)
       [info] agents/checks/builtin.py:421: n = int(pol.get("n_facies") or 0)
       [info] agents/checks/builtin.py:423: rng = float(var.get("range_m") or 0.0)
       [info] agents/checks/builtin.py:424: nug = float(var.get("nugget") or 0.0)
       [info] agents/checks/builtin.py:425: ani = float(var.get("anisotropy") or 0.0)
       [info] agents/checks/builtin.py:438: cell = max(float(step.get("step_x") or 0.0), float(step.get("step_y") or 0.0))
       [info] agents/checks/report.py:102: alpha = cfg.get("checks.fitness_alpha", 0.5) if cfg is not None else 0.5
       [info] agents/checks/report.py:103: beta = cfg.get("checks.fitness_beta", 0.5) if cfg is not None else 0.5
       [info] agents/checks/report.py:188: return round(sum(scores) / len(scores), 4) if scores else 0.0
       [info] agents/checks/report.py:201: counts[row.state] = counts.get(row.state, 0) + 1
       [info] agents/checks/report.py:205: slot[row.state] = slot.get(row.state, 0) + 1
       [info] agents/checks/report.py:209: src[row.state] = src.get(row.state, 0) + 1
       [info] agents/checks/report.py:212: score = 1.0 if row.state == PASSED else 0.0
       [info] agents/checks/report.py:304: map_items = int(info.get("items") or 0)
       [info] agents/checks/report.py:315: states[row.state] = states.get(row.state, 0) + 1
       [info] agents/checks/report.py:369: outside = int(index.get("outside", meta.get("items_outside_blocks") or 0))
       [info] agents/decisions.py:20: self.timeout_sec = float(timeout_sec or 0.0)
       [info] agents/facies.py:278: rng = float(variogram.get("range_m") or 0.0)
       [info] agents/facies.py:279: ani = float(variogram.get("anisotropy") or 0.0)
       [info] agents/facies.py:355: return props, "свидетельство этапа", int(ev.get("proportion_wells") or 0), []
       [info] agents/facies.py:406: counts[code] = counts.get(code, 0) + 1
       [info] agents/facies.py:456: rng = float(variogram.get("range_m") or 0.0)
       [info] agents/facies.py:457: nug = float(variogram.get("nugget") or 0.0)
       [info] agents/facies.py:458: ani = float(variogram.get("anisotropy") or 0.0)
       [info] agents/gates.py:225: 1 if (kq_raw is not None or kc_raw is not None) else 0)
       [info] agents/knowledge.py:150: return float(self.cfg.get("agents.recall.numeric_tolerance", 0.25) or 0.25)
       [info] agents/knowledge.py:169: return sum(diffs) / len(diffs) if diffs else 0.0
       [info] agents/knowledge.py:332: out.sort(key=lambda r: (r.get("branch_id", ""), _num(r.get("priority")) or 0))
       [info] agents/registry.py:174: priority = int(float(r.get("priority", "0") or 0))
       [info] agents/runner.py:429: attempts=int(getattr(verdict, "attempts", 0) or 0),
       [info] core/coordinator.py:336: "steps_done": (staged.get("steps") or {}).get("summary", {}).get("done", 0)}
       [info] core/coordinator.py:584: values["GRID"] = [float(geom.get("nx") or 0), float(geom.get("ny") or 0),
       [info] core/coordinator.py:585: float(geom.get("nz") or 0)]
       [info] core/coordinator.py:586: values["H_grid"] = [float(geom.get("min_z") or 0), float(geom.get("max_z") or 0)]
       [info] core/coordinator.py:739: t = (md - m0) / (m1 - m0) if m1 > m0 else 0.0
       [info] core/datasets.py:72: "well_logs": counts.get("logs", 0),
       [info] core/datasets.py:73: "surfaces": counts.get("surfaces", 0),
       [info] core/datasets.py:74: "has_wellhead": counts.get("wellheads", 0) > 0,
       [info] core/datasets.py:75: "has_welltop": counts.get("welltops", 0) > 0,
       [info] core/datasets.py:76: "tnav_projects": counts.get("projects", 0),
       [info] core/metrics.py:103: "success": 1.0 if ok else 0.0,
       [info] core/metrics.py:107: "steps": summary.get("steps", 0),
       [info] core/pipeline.py:72: counts[s.status] = counts.get(s.status, 0) + 1
       [info] core/pipeline.py:77: "percent": round(100 * done / total, 1) if total else 0.0, "counts": counts}
       [info] core/rollup.py:51: and (n.metrics.get("success", 0) >= m.metrics.get("success", 0)))
       [info] core/rollup.py:67: winner, value = max(scored, key=lambda t: (t[1], t[0].metrics.get("success", 0)))
       [info] core/runner.py:65: "percent": round(100 * done / total, 1) if total else 0.0}
       [info] domain/geostat.py:126: counts[code] = counts.get(code, 0) + 1
       [info] domain/geostat.py:302: return 0.0, ys[0] if ys else 0.0
       [info] domain/geostat.py:306: a = sxy / sxx if sxx else 0.0
       [info] domain/geostat.py:322: return 0.55 if stochastic else 0.0
       [info] domain/geostat.py:369: probs = {c: idw_field(nx, ny, [(s.x, s.y, 1.0 if s.facies == c else 0.0)
       [info] domain/irap.py:110: rotation = float(h2[1]) if len(h2) > 1 else 0.0
       [info] domain/qaqc/build_from_ontology.py:238: number=int(det.get("№") or 0),
       [info] domain/qaqc/build_from_ontology.py:467: by_block[c.block[:2]] = by_block.get(c.block[:2], 0) + 1
       [info] domain/qaqc/coverage.py:123: total = int(slot.get("total") or 0)
       [info] domain/qaqc/coverage.py:124: impl = int(slot.get(STATUS_IMPLEMENTED) or 0)
       [info] domain/qaqc/coverage.py:134: total = int(slot.get("total") or 0)
       [info] domain/qaqc/coverage.py:135: impl = int(slot.get(STATUS_IMPLEMENTED) or 0)
       [info] domain/qaqc/coverage.py:136: na = int(slot.get(STATUS_NOT_APPLICABLE) or 0)
       [info] domain/qaqc/coverage.py:137: unk = int(slot.get(STATUS_UNKNOWN) or 0)
       [info] domain/qaqc/coverage.py:262: "by_status": {k: counts.get(k, 0) for k in
       [info] domain/qaqc/coverage.py:265: "reasons": [{"code": code, "text": REASONS[code], "count": reason_count.get(code, 0),
       [info] domain/qaqc/engine.py:141: result = fn(args[0], p.get("lo", 0.0), p.get("hi", 1.0))
       [info] domain/qaqc/engine.py:145: result = fn(args[0], args[1], p.get("tol", 0.0))
       [info] domain/qaqc/primitives.py:142: return float(np.max(np.abs((x - np.mean(x)) / s))) if s != 0 else 0.0
       [info] domain/qaqc/primitives.py:291: return float(np.all(x)) if x.size else 0.0
       [info] domain/qaqc_adapter.py:115: score = 1.0 if state == "passed" else 0.0
       [info] domain/qaqc_adapter.py:127: report.kq = sum(fit_vals) / len(fit_vals) if fit_vals else 0.0
       [info] domain/qaqc_adapter.py:128: report.kc = sum(qc_vals) / len(qc_vals) if qc_vals else 0.0
       [info] domain/qc/values.py:167: "passed": counts.get(PASSED, 0),
       [info] domain/qc/values.py:168: "failed": counts.get(FAILED, 0),
       [info] domain/qc/values.py:169: "not_applicable": counts.get(NOT_APPLICABLE, 0),
       [info] domain/tnav_client.py:64: self.cpu_num = int(sec.get("cpu_num", 0) or 0)
       [info] domain/tnav_client.py:238: wait = int(lic.get("wait_sec") or sec.get("license_wait_sec") or 0)
       [info] domain/tnav_probes.py:42: "         float (finite.min ()) if finite.size else 0.0,\n"
       [info] domain/tnav_probes.py:43: "         float (finite.max ()) if finite.size else 0.0,\n"
       [info] domain/tnav_probes.py:44: "         float (finite.mean ()) if finite.size else 0.0))\n"
       [info] domain/welltops.py:67: unknown[parts[0]] = unknown.get(parts[0], 0) + 1
совпадений `or 0 / else 0 / get(k,0)`: 88 (оценивать: 0 может быть структурным, но в сборке значений это подмена)

=== 3. QA/QC-ПАКЕТ НА ПУСТЫХ ДАННЫХ ===
evaluate({}) -> total=593 passed=0 failed=0 not_applicable=593 physical=None kq=0.0 kc=0.0 fitness=0.0
by_block: {'02': {'passed': 0, 'failed': 0, 'not_applicable': 438}, '03': {'passed': 0, 'failed': 0, 'not_applicable': 7}, '04': {'passed': 0, 'failed': 0, 'not_applicable': 148}}

=== 4. CheckRegistry НА ПУСТЫХ СВИДЕТЕЛЬСТВАХ ===
проверок в реестре: 21; гейтов из данных: 8
на пустых свидетельствах ни одна проверка не вынесла вердикт — корректно

=== 5. АГЕНТЫ БЕЗ ВХОДОВ → ABSTAIN ===
       agents.structural.StructuralAgent: mode=abstain missing=['structural', 'welltops'] (входов требуется 2)
       agents.grid.GridAgent: mode=abstain missing=['box', 'maps'] (входов требуется 2)
       agents.facies.FaciesAgent: mode=abstain missing=['geostat'] (входов требуется 1)
       agents.petrophysics.PetrophysicsAgent: mode=abstain missing=['petrophysics'] (входов требуется 1)
       agents.saturation.SaturationAgent: mode=abstain missing=['contacts'] (входов требуется 1)
       agents.maps.MapsAgent: mode=abstain missing=[] (входов требуется 0)

=== ИТОГ (rule6) ===
FAIL: 0 | WARN: 36 | INFO: 1
``


## tests/test_verify_qaqc_checklist.py  (exit=0)

``
чеклист: D:\Documents\GIT\ГеоМАС\QAQC\QA_QC_чеклист.xlsx
строк чеклиста с ID: 6065

=== 1. ФАЙЛЫ ontology/qa_checks/*.csv: 12 ===
  b05.csv: 6 проверок
  b06.csv: 11 проверок
  b07.csv: 10 проверок
  b08.csv: 8 проверок
  b09.csv: 12 проверок
  b10.csv: 10 проверок
  b13.csv: 5 проверок
  checklist_details.csv: 62 проверок
  digitized_map.csv: 0 проверок
по блокам (из CSV): {'': 62, '05': 6, '06': 11, '07': 10, '08': 8, '09': 12, '10': 10, '13': 5}
пакет domain/qaqc/checks_table.csv: 714 проверок
все ID из ontology/qa_checks найдены в чеклисте ГПН
все оцифрованные проверки присутствуют в пакете domain/qaqc

=== 1b. ИСПОЛНЯЕМЫЙ ПАКЕТ: CHECKS vs checks_table.csv ===
строк CSV: 714; исполняемых CHECKS: 707; не исполняются со способом «unknown»: 7
QC_*: оцифровано 62, исполняемых 55, unknown 7: ['QC_LITH_005', 'QC_LITH_006', 'QC_LITH_008', 'QC_LITH_010', 'QC_PERM_006', 'QC_SAT_007', 'QC_SAT_008']

=== 3. СВЕРКА ЧИСЛОВЫХ ПОРОГОВ С ЧЕКЛИСТОМ (по ID) ===
сравнено проверок с числами: 46; расхождений: 0

=== 4. ОБЯЗАТЕЛЬНЫЙ НАБОР QC_* ИЗ ЗАДАНИЯ ===
блок 05: 6/6 оцифровано, 6/6 в пакете -> OK
блок 06: 11/11 оцифровано, 11/11 в пакете -> OK
блок 07: 10/10 оцифровано, 10/10 в пакете -> OK
блок 08: 8/8 оцифровано, 8/8 в пакете -> OK
блок 09: 12/12 оцифровано, 12/12 в пакете -> OK
блок 10: 10/10 оцифровано, 10/10 в пакете -> OK
блок 13: 5/5 оцифровано, 5/5 в пакете -> OK

=== 5. qaqc_coverage.json ===
meta.source=ontology/qa_gate_map.yaml meta.checklist=../QAQC/QA_QC_чеклист.xlsx
summary: {"checklist_items": 6065, "implemented": 714, "not_implemented": 5158, "checks_not_applicable": 705, "checks_unknown": 7, "checks_failed": 0, "checks_passed": 0, "checks_evaluated": 712, "unknown_unformalized": 5353, "catalog_blocks": ["02", "03", "04", "05", "06", "07", "08", "09", "10", "13", "14"], "points": {"total": 6065, "by_status": {"implemented": 288, "not_applicable": 417, "unknown": 536
summary.checklist_items = 6065 — охват чеклиста полный
[info] построчный статус вне-блочных пунктов есть: 195 записей, статусы ['unknown'], причина R4: «вне 13 блоков ГПН (укрупнённый пункт / функция ТПУ / историческое НИОК»
summary.points: total=6065, by_status={'implemented': 288, 'not_applicable': 417, 'unknown': 5360}
[info] DESCRIBED_ONLY (7) не входят в CHECKS — корректно (unknown, не passed)
  блок 01: пунктов=8 реализовано=0 не_реализовано=8 статус=not_implemented проверок_в_пакете=0 points=(0, 0, 8) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0} reason=«нет оцифрованных проверок блока»
  блок 02: пунктов=618 реализовано=438 не_реализовано=180 статус=partial проверок_в_пакете=438 points=(180, 258, 180) states={'passed': 0, 'failed': 0, 'not_applicable': 438, 'unknown': 0} reason=«проверки блока оцифрованы частично (438 из 618 пунктов)»
  блок 03: пунктов=173 реализовано=7 не_реализовано=166 статус=partial проверок_в_пакете=7 points=(4, 3, 166) states={'passed': 0, 'failed': 0, 'not_applicable': 7, 'unknown': 0} reason=«проверки блока оцифрованы частично (7 из 173 пунктов)»
  блок 04: пунктов=679 реализовано=148 не_реализовано=531 статус=partial проверок_в_пакете=148 points=(40, 108, 531) states={'passed': 0, 'failed': 0, 'not_applicable': 148, 'unknown': 0} reason=«проверки блока оцифрованы частично (148 из 679 пунктов)»
  блок 05: пунктов=1481 реализовано=46 не_реализовано=1435 статус=partial проверок_в_пакете=46 points=(10, 36, 1435) states={'passed': 0, 'failed': 0, 'not_applicable': 46, 'unknown': 0} reason=«проверки блока оцифрованы частично (46 из 1481 пунктов)»
  блок 06: пунктов=528 реализовано=18 не_реализовано=510 статус=partial проверок_в_пакете=18 points=(12, 2, 514) states={'passed': 0, 'failed': 0, 'not_applicable': 14, 'unknown': 4} reason=«проверки блока оцифрованы частично (18 из 528 пунктов)»
  блок 07: пунктов=61 реализовано=10 не_реализовано=51 статус=partial проверок_в_пакете=10 points=(10, 0, 51) states={'passed': 0, 'failed': 0, 'not_applicable': 10, 'unknown': 0} reason=«проверки блока оцифрованы частично (10 из 61 пунктов)»
  блок 08: пунктов=69 реализовано=8 не_реализовано=61 статус=partial проверок_в_пакете=8 points=(7, 0, 62) states={'passed': 0, 'failed': 0, 'not_applicable': 7, 'unknown': 1} reason=«проверки блока оцифрованы частично (8 из 69 пунктов)»
  блок 09: пунктов=737 реализовано=12 не_реализовано=725 статус=partial проверок_в_пакете=12 points=(10, 0, 727) states={'passed': 0, 'failed': 0, 'not_applicable': 10, 'unknown': 2} reason=«проверки блока оцифрованы частично (12 из 737 пунктов)»
  блок 10: пунктов=86 реализовано=10 не_реализовано=76 статус=partial проверок_в_пакете=10 points=(10, 0, 76) states={'passed': 0, 'failed': 0, 'not_applicable': 10, 'unknown': 0} reason=«проверки блока оцифрованы частично (10 из 86 пунктов)»
  блок 11: пунктов=399 реализовано=0 не_реализовано=399 статус=out_of_scope проверок_в_пакете=0 points=(5, 0, 394) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0} reason=«оценка неопределённостей — вне области статической ГМ этой и»
  блок 12: пунктов=158 реализовано=0 не_реализовано=158 статус=out_of_scope проверок_в_пакете=0 points=(0, 0, 158) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0} reason=«гидродинамическая модель — вне области статической ГМ»
  блок 13: пунктов=873 реализовано=15 не_реализовано=858 статус=partial проверок_в_пакете=15 points=(0, 10, 863) states={'passed': 0, 'failed': 0, 'not_applicable': 15, 'unknown': 0} reason=«проверки блока оцифрованы частично (15 из 873 пунктов)»
  блок 14: пунктов=0 реализовано=2 не_реализовано=0 статус=out_of_checklist проверок_в_пакете=2 points=(None, None, None) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0} reason=«блок есть в каталоге проверок, но отсутствует в чеклисте»
реализовано (по отчёту) 714; проверок в пакете domain/qaqc 714
прогон проверок: passed=0 failed=0 not_applicable=705 unknown=7

=== ИТОГ (qaqc checklist) ===
FAIL: 0 | WARN: 0 | INFO: 3
``


## tests/test_verify_manual_citations.py  (exit=0)

``
warning: The `fitz` API is deprecated and will be removed in future. Use `import pymupdf` instead.
источников с цитатами: 5; мануал: tNavUserGuideDesignerRussian.pdf
страниц в мануале: 4093
уникальных цитат мануала: 5

--- domain/ontology_rules/map_2d_create_by_grid_property.rdf
   заявленные стр.: [1812]
    [WARN] «V9 create строка без zone_id OK» -> в мануале НЕ найдена (проверить вручную)
[WARN] правило 8: domain/ontology_rules/map_2d_create_by_grid_property.rdf: цитата «V9 create строка без zone_id OK» не найдена в tNavUserGuideDesignerRussian.pdf
   заявленные стр.: [1812]
    [OK ] «41 3 6 2D Карта по кубу свойств» -> PDF стр. [29, 1812, 1813, 1814]

--- domain/templates/grid_property_create_by_values.txt
   заявленные стр.: [2734]
    [OK ] «Создать свойство по таблице значений» -> PDF стр. [42, 2564, 2731, 2734]

--- domain/templates/grid_property_create_by_zones.txt
   заявленные стр.: [2733]
    [OK ] «Создать свойство по таблице зон» -> PDF стр. [42, 2564, 2731, 2733]

--- domain/templates/grid_property_facies_modeling.txt
   заявленные стр.: [2581]
    [OK ] «Фациальное моделирование Зоны Регионы» -> PDF стр. [41, 1830, 2563, 2580]

--- domain/templates/map_2d_create_by_grid_property.txt
   заявленные стр.: [1812]
    [OK ] «41 3 6 2D Карта по кубу свойств» -> PDF стр. [29, 1812, 1813, 1814]

=== ИТОГ (manual citations) ===
проверено цитат: 5; не найдено: 1; FAIL: 0
``
