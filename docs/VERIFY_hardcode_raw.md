# АУДИТ ПРИВЯЗОК И ХАРДКОДА — сырые выводы (2026-10-12 12:11)


## tests/test_verify_field_bindings.py (exit=0)

````
АУДИТ ПРИВЯЗОК: D:\Documents\GIT\ГеоМАС\orchestrator_v8

=== 1. ИМЯ ПОЛЯ В РАНТАЙМ-КОДЕ (без комментариев И docstring-ов) ===
  имён полей к проверке: ['gerasimovskoe', 'Герасимовское']
  [info] docstring с именем поля (пример использования): tools/check_metric_vs_table.py:3
  [info] docstring с именем поля (пример использования): tools/check_surface_bullseye.py:3
  [info] docstring с именем поля (пример использования): tools/petrofacies_report.py:3
[WARN] привязка к полю: tools/render_architecture.py:98: литерал «_pipeline_genes:
порядок поля (Герасимовское)» содержит «Герасимовское» (значение поля в коде) — не рантайм (tools/): допустимо как подпись, но лучше брать имя из данных
  привязок в КОДЕ (литералы вне docstring): 1; упоминаний в docstring-ах (допустимо): 3

=== 2. ПРИВЯЗКИ К ПОЛЮ В ГЛОБАЛЬНЫХ ДАННЫХ (config.yaml) ===
  [info] config.yaml:workflow.available_objects_evidence = grid_properties
  [info] config.yaml:workflow.foreign_tokens = Litho3D
  [info] config.yaml:workflow.foreign_tokens = paleo_Litho
  [info] config.yaml:workflow.foreign_tokens = zone_id
  [info] config.yaml:workflow.foreign_tokens = CS_trend
  [info] config.yaml:workflow.foreign_tokens = 2221900
  [info] config.yaml:workflow.foreign_tokens = 6022300
  [info] config.yaml:workflow.foreign_tokens = 491125
  [info] config.yaml:workflow.foreign_tokens = 7873501
  [info] config.yaml:project.grid_name = main_grid
  [info] config.yaml:gates.evidence.kind = well_tie
  [info] config.yaml:gates.evidence.kind = grid
  [info] config.yaml:gates.evidence.kind = grid_properties
  [info] config.yaml:gates.evidence.kind = property_stats
  [info] config.yaml:gates.evidence.kind = blocked_wells
  [info] config.yaml:gates.evidence.kind = property_mean
  [info] config.yaml:gates.evidence.name = PORO
  [info] config.yaml:gates.evidence.as = poro_mean
  [info] config.yaml:gates.evidence.kind = property_mean
  [info] config.yaml:gates.evidence.name = PERM
  [info] config.yaml:gates.evidence.as = perm_mean
  [info] config.yaml:gates.evidence.kind = grid_properties
  [info] config.yaml:gates.evidence.kind = property_stats
  [info] config.yaml:gates.evidence.kind = stoiip
  [info] config.yaml:gates.evidence.kind = grid_properties
  [info] config.yaml:gates.evidence.kind = property_stats
  [info] config.yaml:gates.evidence.kind = maps
  [info] config.yaml:checks.map_files = U1_top
  [info] config.yaml:checks.map_files = Tl_thick
  [info] config.yaml:checks.map_files = PORO
  [info] config.yaml:checks.map_files = PERM
  [info] config.yaml:checks.map_files = STOIIP
  [info] config.yaml:checks.map_files = HCPV
  [info] config.yaml:checks.map_files = PoreVolume
  [info] config.yaml:checks.map_files = NetVolume
  [info] config.yaml:checks.map_files = FACIES
  [info] config.yaml:checks.map_sources.U1_top = struct/depth_u1.irap
  [info] config.yaml:checks.map_sources.U1_bot = 
  [info] config.yaml:checks.map_sources.Tl_thick = 
  [info] config.yaml:checks.map_sources.LIT = 
  [info] config.yaml:checks.map_sources.PORO = 
  [info] config.yaml:checks.map_sources.PERM = 
  [info] config.yaml:checks.map_sources.STOIIP = 
  [info] config.yaml:checks.map_sources.FACIES = 
  [info] config.yaml:checks.map_kinds.structural = U1_top
  [info] config.yaml:checks.map_kinds.structural = Tl_thick
  [info] config.yaml:checks.map_kinds.facies = FACIES
  [info] config.yaml:checks.map_kinds.petrophysics = PORO
  [info] config.yaml:checks.map_kinds.petrophysics = PERM
  [info] config.yaml:checks.map_kinds.volumetrics = STOIIP
  [info] config.yaml:checks.map_kinds.volumetrics = HCPV
  [info] config.yaml:checks.map_kinds.volumetrics = PoreVolume
  [info] config.yaml:checks.map_kinds.volumetrics = NetVolume
  [info] config.yaml:checks.properties.poro.cube = PORO
  [info] config.yaml:checks.properties.poro.mean_key = poro_mean
  [info] config.yaml:checks.properties.perm.cube = PERM
  [info] config.yaml:checks.properties.perm.mean_key = perm_mean
  [info] config.yaml:checks.properties.facies.cube = FACIES
  [info] config.yaml:checks.properties.facies.mean_key = facies_mean
  [info] config.yaml:checks.properties.metric.min_fraction = 0.05
  [info] config.yaml:ensemble.metric = STOIIP
  объектных ключей в глобальном config.yaml: 61
[WARN] имена объектов поля лежат в ГЛОБАЛЬНОМ config.yaml; для второго поля нужен механизм переопределения из проектного графа (или перенос секций в граф)
  проектный граф gerasimovskoe.yaml: переопределяет глобальные секции —

=== 3. ОНТОЛОГИЯ: роль vs значение поля ===
  [info] agent_literature_map.yaml: секций 8: ['AG_STRUCTURAL', 'AG_GRID_VOLUMETRICS', 'AG_FACIES', 'AG_PETROPHYSICS', 'AG_PVT_SCAL', 'AG_MAPS', 'AG_GEOSTATISTICS', '_unassigned']
  [info] ensemble_rules.yaml: секций 7: ['schema_version', 'knowledge_base', 'policy', 'variation_factors', 'selection', 'reference_check', 'checks']
  [info] facies_methods.yaml: секций 15: ['version', 'agent', 'cube_role', 'blocked_wells_role', 'mesh_role', 'keys', 'evidence', 'palette']
  [info] generic_vocabulary.yaml: секций 8: ['schema_version', 'knowledge_base', 'policy', 'generic_unit_values', 'comment_exceptions', 'audited_rule_files', 'scan_exclusions', 'generality_probe']
  [info] geomate_reuse_rules.yaml: секций 7: ['schema_version', 'knowledge_base', 'source', 'entities', 'validations', 'missing_to_implement', 'checks']
  [info] input_recognition_rules.yaml: секций 11: ['schema_version', 'knowledge_base', 'roles', 'policy', 'markers', 'formats', 'data_integrity', 'template_demo_names']
  [info] object_binding_rules.yaml: секций 13: ['schema_version', 'knowledge_base', 'policy', 'roles', 'bindings', 'prepared_trajectories', 'bindings_by_function', 'prepared_marker_table']
  [info] ontology_extra_rules.yaml: секций 1: ['steps']
  [info] petrofacies_methods.yaml: секций 16: ['schema_version', 'knowledge_base', 'source', 'sources', 'columns', 'interval_fields', 'blank_handling', 'porosity_scale']
  [info] petrophysics_rules.yaml: секций 8: ['schema_version', 'knowledge_base', 'log_preparation', 'curve_continuity', 'permeability_model', 'core_data_contract', 'checks', 'literature_basis']
  [info] pvt_scal_rules.yaml: секций 6: ['schema_version', 'knowledge_base', 'policy', 'pvt', 'scal', 'checks']
  [info] qa_gate_map.yaml: секций 6: ['meta', 'severity_levels', 'gates', 'blocks', 'result_checks', 'evidence_keys']
  [info] structural_geostat_rules.yaml: секций 6: ['schema_version', 'knowledge_base', 'structural', 'grid', 'geostatistics', 'checks']
  [info] thresholds_rules.yaml: секций 7: ['schema_version', 'knowledge_base', 'policy', 'thresholds', 'from_field_data', 'checklist', 'checks']
  object_binding_rules.roles: 14; без источника данных: 0
  политика: mode=bind_from_field, replace_template_values=True, on_unresolved_required=failed, on_unresolved_optional=skip_step
  примеры ролей: horizon_top→markers.reservoir_top, horizon_base→markers.reservoir_base, trend_surface→inputs.surface, residual_map→horizon_top, map_thickness→horizon_top
  bindings (распознаваемые значения → роль), 13 шт.: horizon→horizon_top, result_horizon→horizon_top, input_horizon→horizon_top, output_horizon→horizon_top, trend_horizon→trend_surface, residual_idw→residual_map

=== 4. ШАБЛОНЫ/ПРАВИЛА: чужие токены и что доходит до РЕНДЕРА ===
  файлов (шаблоны+правила) с чужими токенами из `workflow.foreign_tokens`: 12
  по токенам: {'paleo_Litho': 1, 'zone_id': 4, 'CS_trend': 3, 'Litho3D': 1, '2221900': 4, '6022300': 4}
  рендер runs\run_Герасимовское\Structure_modeling.py: foreign=—; эвристика вне конфига=['Amazonas']
  рендер runs\run_Герасимовское_dry\Structure_modeling.py: foreign=—; эвристика вне конфига=['Amazonas']

=== 5. ЛИТЕРАЛЬНЫЕ ПУТИ ПРОЕКТА В КОДЕ (литералы вне docstring) ===
  [info] литеральный проектный путь: tools/check_metric_vs_table.py:102: «каталог прогона (runs/run_<поле>)» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:47: «ontology_project/<поле>.yaml
ВСЯ конкретика поля» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:49: «data/<поле>/Source/**
данные заказчика (чтение)» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:88: «данные поля
data/<поле>/Source» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:93: «ontology_project/<поле>.yaml
pipeline: этапы → шаги» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:124: «execute → runs/run_<поле>
dry-run → runs/run_<поле>_dry (данные)» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:182: «runs/run_<поле>
execute» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:182: «runs/run_<поле>_dry
dry-run (runs.dry_suffix)» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:232: «1. положить данные
data/<новое_поле>/Source/**» (не рантайм: tools/)
  [info] литеральный проектный путь: tools/render_architecture.py:233: «2. создать файл поля
ontology_project/<новое_поле>.yaml
(field + dataset_root)» (не рантайм: tools/)
  литеральных проектных путей в литералах кода: 10

=== 7. ОНТОЛОГИЯ: привязка к КОНКРЕТНОМУ объекту поля ===
  конкретных объектов поля к проверке: 32: BAJ, Boundary, Dist_to_well, FACIES, Geobodies_FACIES, HCPV, KINT, LIT, NetVolume, OWC, PERM, PHIE, PORO, Perm, PoreVolume, Poro, Residual_U1_bot, Residual_U1_top, STOIIP, STOIIP_calc, Tl_thick, Tl_thick_smooth, Tl_thick_vrez, U1_bot, U1_seis, U1_seis_boundary, U1_seis_smooth, U1_seis_trend, U1_seis_trend_smooth, U1_top, Vrez, main_grid
  [info] ontology/object_binding_rules.yaml:87: «main_grid» — КЛЮЧ (распознаваемое значение шаблона → роль; дизайн `replace_template_values`): main_grid:                    {role: "grid",            required: fals
  совпадений: значениями (привязка) — 0; ключами — 1; в комментариях — 2
  ВЫВОД: привязок к конкретным объектам поля в данных онтологии НЕТ — только роли, ключи распознавания и комментарии
  машинный эталон reference_workflow.py: собственные объекты поля — ['Boundary', 'Dist_to_well', 'Vrez'] (эталон — данные чужого проекта, правилом 2 разрешён)
  правил функций (RDF): 44; с объектами поля: ['grid_property_interpolate_by_wells_log_sgs_multilayer_facies']

=== 6. МНОГОПОЛЬНОСТЬ: поведение при неизвестном поле ===
  'Герасимовское': стадий 12, вариаций 5
  'НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ': field='НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ', стадий 8, вариаций 0, dataset_root='data/НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ'
  assembler('НЕСУЩЕСТВУЮЩЕЕ_ПОЛЕ'): узлов 8

=== ИТОГ (field bindings) ===
FAIL: 0 | WARN: 2 | INFO: 5
````


## tests/test_verify_hardcode.py (exit=0)

````
токенов СХЕМЫ/API (не домен): 2949
генерическая лексика (единицы измерения) исключена из домена: 1
       [не домен] «percent» ← gerasimovskoe.yaml:.petrophysics.expect.PHIE.units (единица измерения, обоснование — в ontology/generic_vocabulary.yaml)
токенов домена собрано ИЗ ДАННЫХ: 101
allow: 6 шт. в 5 файлах; known_debt: 0 позиций в 0 файлах (базовая линия 26)

=== 3. СКАН В ГРАНИЦАХ ОФИЦИАЛЬНОГО ТЕСТА (agents/ core/ domain/ без qaqc) ===
совпадений всего: 0 | разрешено allow: 0 | объявлено в known_debt: 0 | НЕ ОБЪЯВЛЕНО: 0

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
ontology/: совпадений 5, из них НЕ объявлено в данных: 5
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:557: literal «
FIELD_NAME|Название месторождения|string|none|registered na» домен ['STOIIP']
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:595: literal «
RESERVOIR_NAME|Название пласта / резервуара|string|none|reg» домен ['STOIIP']
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:767: literal «
GRID_NAME|Имя сетки|string|none|unique in model version|dup» домен ['HCPV']
       [info] ontology/build_GeoModelingEvolutionOntology_v4.py:419: literal «Выбор типа и масштаба сетки|Pillar/corner-point/PEBI framewo» домен ['STOIIP']
       [info] ontology/build_NeurosymbolicAgentKB_v4_1.py:269: literal «EVIDENCE_BACKED_CANDIDATE» домен ['EVIDENCE_BACKED_CANDIDATE']
tests/: совпадений 94, из них НЕ объявлено в данных: 94
       [info] tests/test_agents.py:373: literal «Герасимовское» домен ['Герасимовское']
       [info] tests/test_agents.py:566: literal «BAJ» домен ['BAJ']
       [info] tests/test_agents.py:603: literal «staged-skip: толщина отрендерена (Tl_thick в wf02)» домен ['Tl_thick']
       [info] tests/test_agents.py:787: literal «main_grid» домен ['main_grid']
       [info] tests/test_agents.py:789: literal «BAJ» домен ['BAJ']
       [info] tests/test_agents.py:808: literal «probes: STOIIP в свидетельствах» домен ['STOIIP']
       [info] tests/test_agents.py:1195: literal «pipeline: U1_bot (подошва Ю1) — строится по маркеру J2 на эт» домен ['U1_bot']
       [info] tests/test_agents.py:1201: literal «pipeline: толщина Tl_thick = U1_top − U1_bot (кровля − подош» домен ['U1_top', 'U1_bot']
       [info] tests/test_agents.py:1206: literal «pipeline: U1_top (кровля Ю1) — с сейсмическим трендом + resi» домен ['U1_top']
       [info] tests/test_agents.py:173: literal «Герасимовское» домен ['Герасимовское']
       … ещё 84
       (правило 1 про рантайм; ontology/*.py — скрипты-генераторы, tests/ — проверки; фиксируется как зона без автоматического контроля)

=== 4. «МЁРТВЫЙ» ДОЛГ (позиция объявлена, но в файле её нет) ===
мёртвых позиций долга: 0

=== 5. ЧИСЛОВЫЕ ПОРОГИ ИЗ ДАННЫХ, ЗАШИТЫЕ В КОД (информационно) ===
       [info] 0.02 = порог config:gerasimovskoe.yaml:thresholds.poro: 2 мест, напр. domain/ontology_rules/reference_workflow.py:353, domain/ontology_rules/reference_workflow.py:808
       [info] 0.1 = порог config:gerasimovskoe.yaml:thresholds.perm: 3 мест, напр. core/llm_gateway.py:98, domain/ontology_rules/reference_workflow.py:504, domain/ontology_rules/reference_workflow.py:959
       [info] 0.5 = порог config:checks.fitness_alpha: 23 мест, напр. agents/base_agent.py:49, agents/checks/builtin.py:437, agents/checks/builtin.py:454, agents/checks/report.py:194
       [info] 0.6 = порог config:gerasimovskoe.yaml:thresholds.swl: 1 мест, напр. domain/geostat.py:281
       [info] 20.0 = порог config:checks.grid_max_xy_ratio: 12 мест, напр. agents/checks/adapters.py:89, agents/contracts.py:50, core/coordinator.py:1122, core/coordinator.py:513
       [info] 100.0 = порог config:checks.map_extent_tol_m: 13 мест, напр. agents/checks/base.py:410, core/graph_generator.py:88, core/graph_generator.py:88, core/metric_consistency.py:77
       [info] 200.0 = порог config:checks.grid_max_aspect_ratio: 11 мест, напр. agents/checks/adapters.py:94, agents/checks/adapters.py:154, agents/checks/base.py:611, agents/checks/base.py:613
       [info] 5000.0 = порог config:gerasimovskoe.yaml:thresholds.perm: 1 мест, напр. core/coordinator.py:105
       [info] 1000000.0 = порог config:checks.blank_abs: 3 мест, напр. core/graph_generator.py:149, core/metrics.py:19, domain/irap.py:30
значимых совпадений с порогами: 69 (9 разных значений) — оценивать вручную

=== 6. КЛЮЧИ ДАННЫХ, КОТОРЫЕ НЕ ЧИТАЕТ КОД (мёртвые настройки) ===
листовых ключей config.yaml: 120; имя НЕ встречается в коде: 8
       [info] checks.map_sources.U1_bot = ''
       [info] checks.map_sources.U1_top = 'struct/depth_u1.irap'
       [info] execution.build_gdm = True
       [info] execution.build_gm = True
       [info] execution.render_workflow = True
       [info] llm.provider = 'openai_compatible'
       [info] project.branch_zones_keep = 1
       [info] workflow.transitions = 'domain/ontology_rules/transitions.xlsx'

=== 7. ПОХОЖИЕ ИМЕНА КЛЮЧЕЙ (возможная опечатка данных/кода) ===
[WARN] ключ данных `workflow.transitions` не читается; в коде есть похожие имена ['transition'] -> вероятная опечатка в имени ключа
подозрительных пар: 1

=== ИТОГ (hardcode) ===
нарушений правила 1 в ОФИЦИАЛЬНОМ скане (agents/core/domain без qaqc): 0
domain/qaqc/** — ВНЕ официального скана (сгенерированные данные пакета): 38 совпадений домена; это не долг нового кода (см. разбор производности выше)
````


## tests/test_verify_qaqc_checklist.py (exit=0)

````
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
summary: {"checklist_items": 6065, "implemented": 714, "not_implemented": 5158, "checks_not_applicable": 705, "checks_unknown": 7, "checks_failed": 0, "checks_passed": 0, "checks_evaluated": 712, "checks_unverified": 0, "unknown_unformalized": 5353, "catalog_blocks": ["02", "03", "04", "05", "06", "07", "08", "09", "10", "13", "14"], "points": {"total": 6065, "by_status": {"implemented": 288, "not_applicab
[info] покрытие: runs\run_Герасимовское_dry\qaqc_coverage.json (dry-run) — артефакт без данных модели
summary.checklist_items = 6065 — охват чеклиста полный
[info] построчный статус вне-блочных пунктов есть: 195 записей, статусы ['unknown'], причина R4: «вне 13 блоков ГПН (укрупнённый пункт / функция ТПУ / историческое НИОК»
summary.points: total=6065, by_status={'implemented': 288, 'not_applicable': 417, 'unknown': 5360}
[info] DESCRIBED_ONLY (7) не входят в CHECKS — корректно (unknown, не passed)
  блок 01: пунктов=8 реализовано=0 не_реализовано=8 статус=not_implemented проверок_в_пакете=0 points=(0, 0, 8) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0, 'unverified': 0} reason=«нет оцифрованных проверок блока»
  блок 02: пунктов=618 реализовано=438 не_реализовано=180 статус=partial проверок_в_пакете=438 points=(180, 258, 180) states={'passed': 0, 'failed': 0, 'not_applicable': 438, 'unknown': 0, 'unverified': 0} reason=«проверки блока оцифрованы частично (438 из 618 пунктов)»
  блок 03: пунктов=173 реализовано=7 не_реализовано=166 статус=partial проверок_в_пакете=7 points=(4, 3, 166) states={'passed': 0, 'failed': 0, 'not_applicable': 7, 'unknown': 0, 'unverified': 0} reason=«проверки блока оцифрованы частично (7 из 173 пунктов)»
  блок 04: пунктов=679 реализовано=148 не_реализовано=531 статус=partial проверок_в_пакете=148 points=(40, 108, 531) states={'passed': 0, 'failed': 0, 'not_applicable': 148, 'unknown': 0, 'unverified': 0} reason=«проверки блока оцифрованы частично (148 из 679 пунктов)»
  блок 05: пунктов=1481 реализовано=46 не_реализовано=1435 статус=partial проверок_в_пакете=46 points=(10, 36, 1435) states={'passed': 0, 'failed': 0, 'not_applicable': 46, 'unknown': 0, 'unverified': 0} reason=«проверки блока оцифрованы частично (46 из 1481 пунктов)»
  блок 06: пунктов=528 реализовано=18 не_реализовано=510 статус=partial проверок_в_пакете=18 points=(12, 2, 514) states={'passed': 0, 'failed': 0, 'not_applicable': 14, 'unknown': 4, 'unverified': 0} reason=«проверки блока оцифрованы частично (18 из 528 пунктов)»
  блок 07: пунктов=61 реализовано=10 не_реализовано=51 статус=partial проверок_в_пакете=10 points=(10, 0, 51) states={'passed': 0, 'failed': 0, 'not_applicable': 10, 'unknown': 0, 'unverified': 0} reason=«проверки блока оцифрованы частично (10 из 61 пунктов)»
  блок 08: пунктов=69 реализовано=8 не_реализовано=61 статус=partial проверок_в_пакете=8 points=(7, 0, 62) states={'passed': 0, 'failed': 0, 'not_applicable': 7, 'unknown': 1, 'unverified': 0} reason=«проверки блока оцифрованы частично (8 из 69 пунктов)»
  блок 09: пунктов=737 реализовано=12 не_реализовано=725 статус=partial проверок_в_пакете=12 points=(10, 0, 727) states={'passed': 0, 'failed': 0, 'not_applicable': 10, 'unknown': 2, 'unverified': 0} reason=«проверки блока оцифрованы частично (12 из 737 пунктов)»
  блок 10: пунктов=86 реализовано=10 не_реализовано=76 статус=partial проверок_в_пакете=10 points=(10, 0, 76) states={'passed': 0, 'failed': 0, 'not_applicable': 10, 'unknown': 0, 'unverified': 0} reason=«проверки блока оцифрованы частично (10 из 86 пунктов)»
  блок 11: пунктов=399 реализовано=0 не_реализовано=399 статус=out_of_scope проверок_в_пакете=0 points=(5, 0, 394) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0, 'unverified': 0} reason=«оценка неопределённостей — вне области статической ГМ этой и»
  блок 12: пунктов=158 реализовано=0 не_реализовано=158 статус=out_of_scope проверок_в_пакете=0 points=(0, 0, 158) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0, 'unverified': 0} reason=«гидродинамическая модель — вне области статической ГМ»
  блок 13: пунктов=873 реализовано=15 не_реализовано=858 статус=partial проверок_в_пакете=15 points=(0, 10, 863) states={'passed': 0, 'failed': 0, 'not_applicable': 15, 'unknown': 0, 'unverified': 0} reason=«проверки блока оцифрованы частично (15 из 873 пунктов)»
  блок 14: пунктов=0 реализовано=2 не_реализовано=0 статус=out_of_checklist проверок_в_пакете=2 points=(None, None, None) states={'passed': 0, 'failed': 0, 'not_applicable': 0, 'unknown': 0, 'unverified': 0} reason=«блок есть в каталоге проверок, но отсутствует в чеклисте»
реализовано (по отчёту) 714; проверок в пакете domain/qaqc 714
прогон проверок: passed=0 failed=0 not_applicable=705 unknown=7

=== ИТОГ (qaqc checklist) ===
FAIL: 0 | WARN: 0 | INFO: 3
````
