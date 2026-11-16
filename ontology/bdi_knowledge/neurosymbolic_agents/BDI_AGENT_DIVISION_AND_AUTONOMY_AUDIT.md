# Разделение нейросимвольных BDI-агентов и аудит автономности v4.1

Дата: 2026-09-12

## Вывод

Рекомендуется **один общий `TypicalAgentRuntime` и 22 версионируемых доменных профиля**, а не 22 разных программных реализаций. Профиль меняет онтологический срез, БЗ, права, capabilities, владельца объектов и критерии QA/QC; BDI-цикл, `CoverageReport`, `PlanIR`, журнал и политика reconsideration остаются общими.

База знаний после расширения **структурно достаточна для детерминированного выбора ветви и sandbox/shadow-работы**, но **не готова к полностью автономному production-моделированию**. Блокеры: 6117 из 6117 QA/QC-правил не имеют статуса APPROVED/verified; 0 из 3257 кандидатов tNavigator проверены на установленной версии; проектные пороги и полномочия ещё не утверждены. Эти ограничения закодированы как hard gates, а не скрыты.

## Разделение

- **Координация и интеграция:** Оркестратор КГМ; Интегратор системной модели.
- **Данные, знания и программные способности:** Агент данных и исторической нормировки; Агент программных способностей; Куратор базы знаний; Хранитель эволюционной модели.
- **Геологические и геофизические домены:** Региональный геолог / petroleum play; Стратиграф и коррелятор; Седиментолог; Сейсмик-интерпретатор; Структурный геолог; Агент фациального моделирования.
- **Свойства, давление, геомеханика и динамика:** Петрофизик; Агент литологии и типов пород; Агент давления, ГДИС и притока; Агент насыщения, PVT и SCAL; Геомеханик; Геостатистик; Агент сетки, апскейлинга и объёмов; Агент динамической адаптации и 4D.
- **Независимая проверка и управление качеством:** Агент неопределённостей и ансамблей; Агент устранения QA/QC-отклонений.

Метакритик намеренно не является доменным BDI-агентом: это независимый детерминированный конвейер `SHACL → process → physics → cross-model → statistics → GateDecision`. `AG_QA_REMEDIATION` только устраняет и маршрутизирует findings и не может отменить fatal finding.

## Общий цикл агента

`GoalSpec → Context/Beliefs → CoverageReport → SYMBOLIC | HYBRID | GENERATIVE → PlanIR → formal validation → Intention → capability execution → metacritic → commit/reconsider → memory/candidate knowledge`.

- `SYMBOLIC`: утверждённый PlanSpec и достаточное покрытие.
- `HYBRID`: онтологический каркас фиксирован; LLM синтезирует только явно найденный пробел.
- `GENERATIVE`: LLM предлагает несколько PlanDraft, но исполнение только в sandbox и после human gate.

## Результаты gap-analysis

| Критерий | До | После | Статус |
|---|---:|---:|---|
| branches_with_owner_kb | 69/281 | 300/300 | PASS |
| branches_with_activity | 281/281 | 300/300 | PASS |
| branches_with_missing_policy | 69/281 | 300/300 | PASS |
| branches_with_conflict_policy | 69/281 | 300/300 | PASS |
| branches_with_evidence | 69/281 | 300/300 | PASS |
| branches_with_fallback | 69/281 | 300/300 | PASS |
| rules_with_formal_guard | 508/1713 | 1796/1796 | PASS |
| rules_with_human_gate | 1713/1713 | 1796/1796 | PASS |
| decision_csv_covers_all_rules | 1417/1713 | 1796/1796 | PASS |
| guard_beliefs_have_schema | no v4 schema/ | 252/252 | PASS |
| guards_parse_in_reference_runtime | OR dialect mismatch/ | 1796/1796 | PASS |
| process_stages_have_domain_owner | 0/18 | 18/18 | PASS |
| verified_tnavigator_callables | 0/3257 | 0/3257 | BLOCKS_PRODUCTION |
| approved_qaqc_rules | 0/6117 | 0/6117 | BLOCKS_PRODUCTION |

Исправлено: единый CSV теперь покрывает все 1796 правил; все 300 развилки имеют owner-KB, activity, missing/conflict policy, evidence и fallback; строковые условия новых v4-правил дополнены формальными `ConditionGroup/AtomicCondition`; добавлена типизированная схема beliefs; 18 стадий получили доменного владельца; четыре ошибочных идентификатора унаследованных KB исправлены в генераторе v4.

## Новые правила из литературы и архитектуры

Добавлены 83 правила в 19 развилках: режим покрытия, право исполнения, handoff, продвижение знания, тип ветви ансамбля, reconsideration, перенос аналогов, выбор фациального алгоритма, depth conversion, fault scenarios, исторические ГИС, saturation model, ГДИС, pressure datum, geomechanical coupling, trend/stationarity, агрегация uncertainty, reprocessing vintage и безопасный software call.

Основные локальные свидетельства: Walker/Selley/Барабошкин по фациям и седиментологии; Glover и внутренние руководства по петрофизике; Bourdet/Heinemann/Schlumberger по ГДИС; Ковалевский и курс по variogram; материалы по uncertainty/GCoS; руководство tNavigator по geomechanics; рабочие QA/QC-реестры. Каждый новый rule содержит `supportedBy`, `knowledgeStatus` и `executionEligibility`.

## Что нужно для production-автономности

1. Утвердить проектный policy (`project_symbolic_threshold`, `project_hybrid_threshold`, риск-классы, полномочия и критерии materiality).
2. Верифицировать минимальный набор реальных функций/адаптеров tNavigator на установленной версии: signature, license, read/write scope, dry-run, postconditions и rollback.
3. Перевести критические QA/QC-правила из «Статус не подтверждён» в APPROVED после владельца, тестов и эталонных наборов.
4. Прогнать каждый профиль на golden/negative/boundary/mutation cases и shadow-проекте.
5. После этого повышать права точечно: A1 → A2 → A3, без глобального переключателя «полная автономия».
