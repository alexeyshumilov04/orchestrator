from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BDI_DIR = HERE / "bdi_knowledge"
AGENT_DIR = BDI_DIR / "neurosymbolic_agents"
BASE_BDI = BDI_DIR / "BDI_KnowledgeBase_v4_AllInOne.rdf"
BASE_MAIN = HERE / "GeoModelingEvolutionOntology_v4_AllInOne.rdf"
V3_BDI = ROOT / "Онтологии процесса 3" / "bdi_knowledge"

GM = "https://example.org/geomodel/evolution/v4#"
ONT = "https://example.org/geomodel/evolution/v4/"
BDI = "https://example.org/geomodel/evolution/v4/bdi#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
XSD = "http://www.w3.org/2001/XMLSchema#"
DCT = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"

TRIPLE_RE = re.compile(r'^<([^>]*)> <([^>]*)> (.+) \.$')
IRI_RE = re.compile(r'^<([^>]*)>$')
LITERAL_RE = re.compile(r'^"((?:\\.|[^"])*)"(?:@[A-Za-z-]+|\^\^<[^>]+>)?$')


def iri(value: str) -> str:
    if value.startswith(("http://", "https://", "urn:")):
        return f"<{value}>"
    return f"<{GM}{value}>"


def esc(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")


def lit(value: object, lang: str | None = None, datatype: str | None = None) -> str:
    if isinstance(value, bool):
        value = str(value).lower()
    result = f'"{esc(value)}"'
    if lang:
        result += f"@{lang}"
    elif datatype:
        result += f"^^<{datatype}>"
    return result


def add(lines: set[str], subject: str, predicate: str, obj: str) -> None:
    lines.add(f"{iri(subject)} {iri(predicate)} {obj} .")


def add_i(lines: set[str], subject: str, predicate: str, obj: str) -> None:
    add(lines, subject, predicate, iri(obj))


def add_l(lines: set[str], subject: str, predicate: str, value: object, *, lang: str | None = None, datatype: str | None = None) -> None:
    add(lines, subject, predicate, lit(value, lang, datatype))


def type_label(lines: set[str], subject: str, type_: str, label: str, description: str = "") -> None:
    add_i(lines, subject, RDF + "type", type_)
    add_l(lines, subject, RDFS + "label", label, lang="ru")
    if description:
        add_l(lines, subject, DCT + "description", description, lang="ru")


def parse(lines: set[str]) -> tuple[dict[str, set[str]], dict[tuple[str, str], list[str]]]:
    types: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[tuple[str, str], list[str]] = defaultdict(list)
    for raw in lines:
        match = TRIPLE_RE.fullmatch(raw)
        if not match:
            continue
        subject, predicate, obj = match.groups()
        outgoing[(subject, predicate)].append(obj)
        value = IRI_RE.fullmatch(obj)
        if predicate == RDF + "type" and value:
            types[subject].add(value.group(1))
    return types, outgoing


def as_iri(token: str) -> str | None:
    match = IRI_RE.fullmatch(token)
    return match.group(1) if match else None


def as_literal(token: str) -> str:
    match = LITERAL_RE.fullmatch(token)
    return match.group(1).replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\") if match else token


def local(value: str) -> str:
    return value.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


CLASSES = [
    ("TypicalAgentRuntime", "Типовой нейросимвольный BDI-LLM runtime"),
    ("DomainAgentProfile", "Доменный профиль агента"),
    ("AgentGroup", "Группа агентов"),
    ("RuntimeModule", "Функциональный модуль агента"),
    ("CoverageReport", "Отчёт покрытия задачи онтологией"),
    ("OperationMode", "Режим работы агента"),
    ("GoalSpec", "Формальная спецификация цели"),
    ("PlanSpec", "Утверждённый шаблон плана"),
    ("PlanDraft", "Черновик плана"),
    ("PlanIR", "Типизированное промежуточное представление плана"),
    ("Capability", "Абстрактная исполняемая способность"),
    ("MetacriticPipeline", "Независимый конвейер метакритика"),
    ("GateDecision", "Решение контрольного шлюза"),
    ("HandoffContract", "Контракт межагентной передачи"),
    ("AutonomyPolicy", "Политика уровня автономии"),
    ("KnowledgeCandidate", "Кандидат знания"),
    ("FactCandidate", "Кандидат факта"),
    ("RuleCandidate", "Кандидат правила"),
    ("PlanCandidate", "Кандидат плана"),
    ("CaseCandidate", "Кандидат прецедента"),
    ("MethodCandidate", "Кандидат метода"),
    ("FailureCandidate", "Кандидат знания об отказе"),
]

OBJECT_PROPERTIES = [
    "usesRuntime", "belongsToAgentGroup", "ownsProcessStage", "readsOntologyModule",
    "usesKnowledgeBase", "hasRuntimeModule", "feedsModule", "selectsOperationMode",
    "compilesToPlanIR", "invokesCapability", "validatedByMetacritic", "hasHandoffContract",
    "handoffFrom", "handoffTo", "requiresGate", "hasCoverageReport", "supportedBy",
]

DATA_PROPERTIES = [
    "profileCode", "scopeText", "defaultAutonomyLevel", "allowedOperationMode", "moduleFunction",
    "inputContract", "outputContract", "knowledgeStatus", "executionEligibility", "decisionScope",
    "requestedCapability", "sourceLocator", "coverageThreshold", "approvalAuthority", "recoveryAction",
]


AGENT_GROUPS = [
    ("GROUP_COORDINATION", "Координация и интеграция"),
    ("GROUP_DATA_PLATFORM", "Данные, знания и программные способности"),
    ("GROUP_GEOSCIENCE", "Геологические и геофизические домены"),
    ("GROUP_RESERVOIR", "Свойства, давление, геомеханика и динамика"),
    ("GROUP_ASSURANCE", "Независимая проверка и управление качеством"),
]

RUNTIME_MODULES = [
    ("MOD_REQUEST", "RequestController", "Принимает задачу и создаёт трассируемый GoalSpec."),
    ("MOD_CONTEXT", "ContextAssembler", "Собирает объект, сценарий, время, версии и права."),
    ("MOD_BELIEF", "BeliefManager", "Формирует типизированный snapshot убеждений с provenance и confidence."),
    ("MOD_GOAL", "GoalManager", "Проверяет непротиворечивость целей и критериев завершения."),
    ("MOD_COVERAGE", "CoverageAssessor", "Оценивает покрытие онтологией и выбирает SYMBOLIC/HYBRID/GENERATIVE."),
    ("MOD_OPTIONS", "OptionGenerator", "Строит допустимые варианты планов и ветви неопределённости."),
    ("MOD_LLM", "LLMPlanner", "Предлагает недостающий фрагмент или PlanDraft без права исполнения."),
    ("MOD_PLANIR", "PlanIRCompiler", "Компилирует план в типизированный PlanIR с pre/postconditions."),
    ("MOD_FORMAL", "FormalValidator", "Проверяет типы, единицы, CRS, зависимости, завершимость и права."),
    ("MOD_UTILITY", "UtilityRanker", "Ранжирует варианты по качеству, риску, стоимости и информации."),
    ("MOD_INTENTION", "IntentionManager", "Фиксирует выбранный план и условия пересмотра намерения."),
    ("MOD_CAPABILITY", "CapabilityBroker", "Разрешает абстрактную операцию в проверенный адаптер ПО."),
    ("MOD_EXECUTION", "ExecutionMonitor", "Исполняет, контролирует timeout, idempotency и компенсацию."),
    ("MOD_CRITIC_GATE", "MetacriticGateway", "Передаёт результат независимому детерминированному метакритику."),
    ("MOD_RECONSIDER", "ReconsiderationManager", "Обновляет beliefs и запускает селективный пересчёт."),
    ("MOD_MEMORY", "MemoryWriter", "Пишет эпизод, решение, evidence и отрицательный опыт."),
    ("MOD_CANDIDATE", "KnowledgeCandidateFactory", "Создаёт кандидаты знаний, но не публикует их как APPROVED."),
    ("MOD_PROVENANCE", "ProvenanceRecorder", "Фиксирует версии, источники, хэши и цепочку ответственности."),
]

AGENT_PROFILES = [
    ("AG_ORCHESTRATOR", "Оркестратор КГМ", "GROUP_COORDINATION", "S01,S16,S18", "A2", "Декомпозиция целей, зависимости, спорные ситуации; не редактирует доменные объекты."),
    ("AG_MODEL_INTEGRATOR", "Интегратор системной модели", "GROUP_COORDINATION", "S15,S16,S17", "A2", "Согласует ветви, версии и междисциплинарные ограничения."),
    ("AG_DATA_STEWARD", "Агент данных и исторической нормировки", "GROUP_DATA_PLATFORM", "S02", "A3", "Каталогизация, идентификаторы, единицы, CRS, винтажи и неизменяемые raw revisions."),
    ("AG_SOFTWARE_BROKER", "Агент программных способностей", "GROUP_DATA_PLATFORM", "S18", "A2", "Разрешает capability в версионный адаптер tNavigator/GeoVation/Petrel и проверяет postconditions."),
    ("AG_KNOWLEDGE_CURATOR", "Куратор базы знаний", "GROUP_DATA_PLATFORM", "S18", "A1", "Кандидаты знаний, дедупликация, тесты, экспертное утверждение, deprecation и rollback."),
    ("AG_REGIONAL_PLAY", "Региональный геолог / petroleum play", "GROUP_GEOSCIENCE", "S03", "A2", "Бассейн, petroleum system, play, CRS-карты, GCoS и аналоги."),
    ("AG_STRATIGRAPHY", "Стратиграф и коррелятор", "GROUP_GEOSCIENCE", "S04", "A2", "Расчленение, корреляция, sequence stratigraphy и альтернативные схемы."),
    ("AG_SEDIMENTOLOGY", "Седиментолог", "GROUP_GEOSCIENCE", "S05", "A2", "Литофации, ассоциации, depositional elements, палеогеография и аналоги."),
    ("AG_SEISMIC", "Сейсмик-интерпретатор", "GROUP_GEOSCIENCE", "S06", "A2", "Сейсмические винтажи, горизонты, разломы, атрибуты и глубинное преобразование."),
    ("AG_STRUCTURAL", "Структурный геолог", "GROUP_GEOSCIENCE", "S07", "A2", "Структурный каркас, fault framework, поверхности и структурные сценарии."),
    ("AG_PETROPHYSICS", "Петрофизик", "GROUP_RESERVOIR", "S08", "A2", "ГИС, керн, environmental corrections, минералогия, пористость, Sw и cut-offs."),
    ("AG_ROCKTYPE", "Агент литологии и типов пород", "GROUP_RESERVOIR", "S09", "A2", "Литология, rock typing, HFU/FZI, NTG и распространение коллектора."),
    ("AG_FACIES", "Агент фациального моделирования", "GROUP_GEOSCIENCE", "S10", "A2", "2D/3D фации, proportions, variograms, object/MPS/PGS и connectivity."),
    ("AG_PRESSURE_WELLTEST", "Агент давления, ГДИС и притока", "GROUP_RESERVOIR", "S11", "A2", "Datum, gauge drift, rate history, derivative regimes, pressure field и inflow."),
    ("AG_PVT_SCAL", "Агент насыщения, PVT и SCAL", "GROUP_RESERVOIR", "S12", "A2", "Контакты, saturation-height, Pc/J-function, PVT regions и relperm."),
    ("AG_GEOMECHANICS", "Геомеханик", "GROUP_RESERVOIR", "S13", "A2", "1D MEM, stress calibration, faults/fractures, compaction, subsidence и coupling."),
    ("AG_GEOSTATISTICS", "Геостатистик", "GROUP_RESERVOIR", "S14", "A2", "Domains, trends, declustering, variograms, simulation и cross-validation."),
    ("AG_GRID_VOLUMETRICS", "Агент сетки, апскейлинга и объёмов", "GROUP_RESERVOIR", "S15", "A2", "Grid design, layering, QC cells, upscaling, volumetrics и reserves cases."),
    ("AG_UNCERTAINTY", "Агент неопределённостей и ансамблей", "GROUP_ASSURANCE", "S16", "A2", "Aleatory/epistemic, branch kinds, sampling, ranking, VOI и assurance."),
    ("AG_DYNAMIC_4D", "Агент динамической адаптации и 4D", "GROUP_RESERVOIR", "S17", "A2", "Static-to-dynamic handoff, history matching, 4D assimilation и forecast."),
    ("AG_LIFECYCLE", "Хранитель эволюционной модели", "GROUP_DATA_PLATFORM", "S18", "A2", "Impact graph, selective rebuild, supersession, архив и 60-летняя воспроизводимость."),
    ("AG_QA_REMEDIATION", "Агент устранения QA/QC-отклонений", "GROUP_ASSURANCE", "S02,S16", "A2", "Маршрутизирует исправления; не может отменять детерминированный finding метакритика."),
]

BELIEF_DEFS: dict[str, tuple[str, str, str]] = {
    "input_completeness": ("decimal", "", "Полнота обязательных входов"),
    "critical_qc_passed": ("boolean", "", "Критические проверки пройдены"),
    "contradiction_count": ("decimal", "", "Число нерешённых противоречий"),
    "conceptual_uncertainty": ("enum", "low|medium|high", "Концептуальная неопределённость"),
    "data_density": ("enum", "sparse|moderate|dense", "Плотность данных"),
    "new_vintage_impact": ("enum", "low|medium|high", "Влияние нового винтажа"),
    "acceptance_criteria_met_v4": ("boolean", "", "Критерии приёмки v4 выполнены"),
    "approved_plan_found": ("boolean", "", "Найден утверждённый PlanSpec"),
    "ontology_coverage": ("decimal", "", "Доля покрытия задачи утверждённой онтологией"),
    "plan_ir_valid": ("boolean", "", "PlanIR прошёл формальную проверку"),
    "metacritic_passed": ("boolean", "", "Метакритик выдал PASS"),
    "metacritic_severity": ("enum", "none|warning|major|fatal", "Максимальная тяжесть finding"),
    "capability_verified": ("boolean", "", "Адаптер и сигнатура capability проверены"),
    "knowledge_status": ("enum", "APPROVED|APPROVED_REFERENCE|CANDIDATE|DRAFT|DEPRECATED", "Статус используемого знания"),
    "risk_class": ("enum", "low|medium|high|critical", "Материальность и риск действия"),
    "evidence_complete": ("boolean", "", "Evidence package полон"),
    "lineage_complete": ("boolean", "", "Lineage и версии полны"),
    "assumptions_registered": ("boolean", "", "Допущения зарегистрированы"),
    "uncertainties_registered": ("boolean", "", "Неопределённости зарегистрированы"),
    "branch_kind": ("enum", "structural_hypothesis|stochastic_realization|engineering_option|unknown", "Тип ветвления ансамбля"),
    "new_evidence_invalidates_precondition": ("boolean", "", "Новое свидетельство нарушило предусловие намерения"),
    "source_traceable": ("boolean", "", "Источник знания трассируем"),
    "sandbox_tests_passed": ("boolean", "", "Golden/negative/boundary/mutation тесты пройдены"),
    "expert_approval_present": ("boolean", "", "Есть утверждение профильного эксперта"),
    "duplicate_or_conflict_found": ("boolean", "", "Найден дубликат или конфликт знания"),
    "analog_similarity": ("decimal", "", "Сходство аналога с целевым объектом"),
    "analog_scale_transform_known": ("boolean", "", "Масштабный перенос аналога обоснован"),
    "training_image_available": ("boolean", "", "Доступен репрезентативный training image"),
    "non_two_point_patterns_material": ("boolean", "", "Связность определяется многоточечными паттернами"),
    "geobody_geometry_constrained": ("boolean", "", "Геометрия геотел ограничена данными/аналогом"),
    "ordered_facies_transitions": ("boolean", "", "Переходы фаций имеют геологический порядок"),
    "seismic_velocity_calibrated": ("boolean", "", "Скоростная модель откалибрована"),
    "depth_uncertainty_material": ("boolean", "", "Глубинная неопределённость материальна"),
    "fault_evidence_confidence": ("enum", "low|medium|high", "Уверенность в разломе"),
    "fault_decision_impact": ("enum", "low|medium|high", "Влияние разлома на решение"),
    "legacy_log_metadata_complete": ("boolean", "", "Метаданные старых ГИС полны"),
    "tool_environment_correction_known": ("boolean", "", "Поправки за среду/прибор известны"),
    "conductive_clay_effect": ("enum", "negligible|material|unknown", "Влияние проводящей глины"),
    "archie_calibration_available": ("boolean", "", "Параметры Archie откалиброваны"),
    "pressure_rate_history_qc": ("boolean", "", "Давление и история дебита прошли QC"),
    "wellbore_storage_dominates": ("boolean", "", "Ранний отклик доминируется wellbore storage"),
    "diagnostic_regime_identified": ("boolean", "", "Диагностический режим распознан"),
    "pressure_datum_consistent": ("boolean", "", "Давления приведены к общему datum"),
    "mem_calibrated": ("boolean", "", "1D MEM откалибрована по наблюдениям"),
    "depletion_geomech_coupling_material": ("boolean", "", "Связь фильтрации и геомеханики материальна"),
    "stress_calibration_data_available": ("boolean", "", "Доступны LOT/XLOT/DFIT/breakout/DITF данные"),
    "preferential_sampling_detected": ("boolean", "", "Обнаружен preferential sampling"),
    "trend_material": ("boolean", "", "Крупномасштабный тренд материален"),
    "residual_stationary": ("boolean", "", "Остаток после тренда стационарен"),
    "dependent_parameters_present": ("boolean", "", "Есть зависимые неопределённые параметры"),
    "correlation_model_validated": ("boolean", "", "Корреляционная модель подтверждена"),
    "aggregation_requested": ("boolean", "", "Требуется агрегация объектов/пластов"),
    "raw_observation_available": ("boolean", "", "Сохранена исходная наблюдаемая запись"),
    "reprocessing_method_changed": ("boolean", "", "Изменилась методика/алгоритм обработки"),
    "impact_graph_available": ("boolean", "", "Доступен граф зависимостей для selective rebuild"),
    "software_mutates_project": ("boolean", "", "Вызов изменяет инженерный проект"),
    "dry_run_passed": ("boolean", "", "Dry-run на копии проекта пройден"),
    "postconditions_passed": ("boolean", "", "Postconditions и checksum результата пройдены"),
}


def rule(priority: int, guard: str, outcome: str, intention: str, *, human: bool = False,
         method: str = "", capability: str = "", function: str = "", next_: str = "",
         return_: str = "", rationale: str = "", status: str = "EVIDENCE_BACKED_CANDIDATE") -> dict[str, object]:
    return {
        "priority": priority, "guard": guard, "outcome": outcome, "intention": intention,
        "human": human, "method": method, "capability": capability, "function": function,
        "next": next_, "return": return_, "rationale": rationale, "status": status,
    }


BRANCHES: list[dict[str, object]] = [
    {
        "id": "BR_NS_COVERAGE_MODE", "kb": "KB_NS_ORCHESTRATION", "owner": "AG_ORCHESTRATOR",
        "label": "Выбор режима SYMBOLIC / HYBRID / GENERATIVE", "activity": "SUB_S01_01",
        "sources": ["STD_OWL2", "STD_SHACL12"],
        "rules": [
            rule(10, "approved_plan_found = true ALL ontology_coverage >= project_symbolic_threshold", "Использовать только утверждённый PlanSpec", "Запустить SYMBOLIC", method="symbolic_plan_selection", capability="compile_plan_ir", next_="SUB_S01_04", rationale="Полное покрытие не требует генерации процесса.", status="APPROVED_ARCHITECTURE"),
            rule(20, "ontology_coverage >= project_hybrid_threshold", "Зафиксировать известный каркас и синтезировать только пробел", "Запустить HYBRID", human=True, method="gap_bounded_plan_synthesis", capability="compile_plan_ir", rationale="LLM ограничен CoverageReport и зарегистрированными capabilities.", status="APPROVED_ARCHITECTURE"),
            rule(30, "ontology_coverage < project_hybrid_threshold", "Сформировать не менее трёх PlanDraft и выполнить sandbox replay", "Запустить GENERATIVE", human=True, method="constrained_multi_plan_generation", capability="sandbox_replay", rationale="Отсутствие онтологии не даёт права production-исполнения.", status="APPROVED_ARCHITECTURE"),
            rule(999, "otherwise", "Остановить выбор режима при неизвестном покрытии", "Запросить уточнение GoalSpec", human=True, return_="SUB_S01_01", rationale="Safe fallback для неполного CoverageReport.", status="APPROVED_ARCHITECTURE"),
        ],
    },
    {
        "id": "BR_NS_EXECUTION_AUTHORITY", "kb": "KB_NS_ORCHESTRATION", "owner": "AG_ORCHESTRATOR",
        "label": "Допуск плана к исполнению", "activity": "SUB_S18_09", "sources": ["STD_SHACL12", "STD_PROVO"],
        "rules": [
            rule(10, "metacritic_severity = fatal", "Запретить исполнение и зафиксировать GateDecision=FAIL", "Устранить fatal finding", human=True, return_="SUB_S16_08", rationale="Fatal finding не может быть отменён LLM."),
            rule(20, "plan_ir_valid = false", "Запретить исполнение", "Исправить типы, единицы, предусловия или завершимость PlanIR", return_="SUB_S18_09", rationale="Невалидный PlanIR не создаёт Intention."),
            rule(30, "capability_verified = false", "Разрешить только sandbox/shadow", "Верифицировать адаптер, версию, лицензию и сигнатуру", human=True, capability="verify_software_capability", rationale="Кандидат функции из мануала не равен проверенному API-вызову."),
            rule(40, "knowledge_status in CANDIDATE|DRAFT", "Разрешить только sandbox replay", "Собрать evidence для продвижения знания", human=True, capability="sandbox_replay", rationale="Кандидат знания не исполняется в production."),
            rule(50, "risk_class = low ALL plan_ir_valid = true ALL metacritic_passed = true", "Разрешить ограниченное production-исполнение в пределах профиля", "Создать Intention и исполнить", capability="execute_plan_ir", rationale="Низкий риск, формальная валидность и независимый PASS."),
            rule(60, "risk_class in high|critical", "Требовать владельца объекта и профильного утверждающего", "Ожидать human gate", human=True, rationale="Материальные изменения модели и запасов не автономизируются по умолчанию."),
            rule(999, "otherwise", "Остановить исполнение", "Собрать недостающие gate facts", human=True, rationale="Неопределённое право трактуется консервативно."),
        ],
    },
    {
        "id": "BR_NS_HANDOFF", "kb": "KB_NS_ORCHESTRATION", "owner": "AG_MODEL_INTEGRATOR",
        "label": "Приёмка межагентной передачи", "activity": "SUB_S16_08", "sources": ["STD_PROVO", "STD_RESQML22"],
        "rules": [
            rule(10, "evidence_complete = false", "Отклонить handoff", "Дособрать входы, критерии и доказательства", return_="SUB_S16_08", rationale="Без evidence пакет невоспроизводим."),
            rule(20, "lineage_complete = false", "Отклонить handoff", "Восстановить версии, источники и checksums", return_="SUB_S02_09", rationale="Нельзя смешивать винтажи без provenance."),
            rule(30, "assumptions_registered = false ANY uncertainties_registered = false", "Отклонить handoff", "Заполнить реестры допущений и неопределённостей", return_="SUB_S01_06", rationale="Скрытые допущения делают междисциплинарную передачу небезопасной."),
            rule(40, "evidence_complete = true ALL lineage_complete = true ALL metacritic_passed = true", "Принять immutable handoff revision", "Передать следующему владельцу", capability="commit_handoff_revision", next_="SUB_S17_01", rationale="Принимается конкретная версия с формальным gate."),
            rule(999, "otherwise", "Поместить пакет в quarantine", "Разрешить конфликт владельцев", human=True, rationale="Fallback не допускает молчаливого принятия."),
        ],
    },
    {
        "id": "BR_NS_KNOWLEDGE_PROMOTION", "kb": "KB_NS_KNOWLEDGE", "owner": "AG_KNOWLEDGE_CURATOR",
        "label": "Продвижение кандидата знания", "activity": "SUB_S18_11", "sources": ["STD_PROVO", "STD_SHACL12"],
        "rules": [
            rule(10, "source_traceable = false", "Отклонить кандидат", "Запросить первичный источник и locator", rationale="Непроверяемое происхождение блокирует публикацию."),
            rule(20, "duplicate_or_conflict_found = true", "Не публиковать и открыть contradiction case", "Сравнить области применимости и версии", human=True, rationale="Конфликт нельзя решать последней записью."),
            rule(30, "sandbox_tests_passed = false", "Оставить CANDIDATE", "Добавить golden, negative, boundary и mutation tests", rationale="Текст правила без тестов не является исполняемым знанием."),
            rule(40, "sandbox_tests_passed = true ALL expert_approval_present = true ALL source_traceable = true", "Опубликовать immutable APPROVED revision", "Активировать новую версию и сохранить rollback", capability="publish_knowledge_revision", rationale="Публикация отделена от генерации."),
            rule(999, "otherwise", "Оставить в quarantine", "Назначить владельца review", human=True, rationale="Один успешный эпизод создаёт CaseCandidate, а не правило."),
        ],
    },
    {
        "id": "BR_NS_BRANCH_KIND", "kb": "KB_NS_ORCHESTRATION", "owner": "AG_UNCERTAINTY",
        "label": "Классификация ветви ансамбля", "activity": "SUB_S16_03", "sources": ["STD_PRMS", "SRC_LOCAL_0757"],
        "rules": [
            rule(10, "branch_kind = structural_hypothesis", "Сохранять отдельные геологические гипотезы и веса", "Оценить model-form uncertainty", method="weighted_concept_scenarios", rationale="Гипотезы не сворачиваются как случайные реализации."),
            rule(20, "branch_kind = stochastic_realization", "Сохранять seed, distribution и ранги", "Оценить квантили внутри концепции", method="stochastic_realization_ensemble", rationale="Реализации условны на выбранной концепции."),
            rule(30, "branch_kind = engineering_option", "Ранжировать по decision metrics", "Выполнить многокритериальный анализ", method="decision_option_ranking", rationale="Инженерный вариант не является геологической вероятностью."),
            rule(999, "otherwise", "Запретить агрегацию ансамбля", "Классифицировать ось ветвления", human=True, rationale="Смешанный мешок моделей математически неинтерпретируем."),
        ],
    },
    {
        "id": "BR_NS_RECONSIDERATION", "kb": "KB_NS_ORCHESTRATION", "owner": "AG_LIFECYCLE",
        "label": "Пересмотр намерения по новому свидетельству", "activity": "SUB_S18_07", "sources": ["STD_PROVO", "SRC_LOCAL_0763"],
        "rules": [
            rule(10, "new_evidence_invalidates_precondition = true", "Отменить текущее Intention", "Построить impact graph и перепланировать", capability="compute_dependency_impact", rationale="BDI обязан reconsider при нарушении предусловий."),
            rule(20, "new_vintage_impact = high ALL impact_graph_available = true", "Пересчитать затронутое замыкание зависимостей", "Запустить selective rebuild", capability="selective_model_rebuild", rationale="Не требуется полный пересчёт неизменённых ветвей."),
            rule(30, "new_vintage_impact = low", "Сохранить намерение и обновить evidence", "Продолжить с новой revision", rationale="Нематериальное свидетельство не должно вызывать churn."),
            rule(999, "otherwise", "Приостановить намерение", "Выполнить impact analysis", human=True, rationale="Неизвестное влияние не игнорируется."),
        ],
    },
    {
        "id": "BR_LIT_ANALOG_TRANSFER", "kb": "KB_NS_REGIONAL", "owner": "AG_REGIONAL_PLAY",
        "label": "Перенос знаний аналога", "activity": "SUB_S03_12", "sources": ["SRC_LOCAL_0763", "SRC_LOCAL_0142"],
        "rules": [
            rule(10, "analog_similarity >= project_analog_threshold ALL analog_scale_transform_known = true", "Использовать аналог как взвешенное мягкое ограничение", "Калибровать prior и диапазоны", method="analog_weighted_prior", rationale="Перенос допустим при сходстве процесса и известном масштабировании."),
            rule(20, "analog_similarity >= project_analog_threshold ALL analog_scale_transform_known = false", "Использовать только качественный сценарий", "Оценить uncertainty масштабного переноса", human=True, rationale="Геометрические числа нельзя переносить без scale transform."),
            rule(30, "analog_similarity < project_analog_threshold", "Отклонить аналог как количественный", "Найти другой аналог или расширить диапазоны", rationale="Поверхностное сходство не заменяет depositional-process match."),
            rule(999, "otherwise", "Не использовать количественно", "Запросить паспорт аналога", human=True, rationale="Неизвестное сходство трактуется как слабое evidence."),
        ],
    },
    {
        "id": "BR_LIT_FACIES_ALGORITHM", "kb": "KB_NS_FACIES", "owner": "AG_FACIES",
        "label": "Выбор семейства алгоритма фациальной модели", "activity": "SUB_S10_05", "sources": ["SRC_LOCAL_0142", "SRC_LOCAL_0188", "SRC_LOCAL_0191"],
        "rules": [
            rule(10, "training_image_available = true ALL non_two_point_patterns_material = true", "Выбрать MPS и проверить репрезентативность training image", "Построить MPS ensemble", method="multiple_point_statistics", rationale="MPS нужен для геометрии, не описываемой двухточечной статистикой."),
            rule(20, "geobody_geometry_constrained = true", "Выбрать object-based simulation", "Параметризовать тела распределениями и трендами", method="object_based_facies_simulation", rationale="Object model уместен при интерпретируемой геометрии геотел."),
            rule(30, "ordered_facies_transitions = true", "Выбрать truncated/plurigaussian simulation", "Задать допустимые контакты и latent fields", method="plurigaussian_facies_simulation", rationale="Метод сохраняет геологический порядок контактов."),
            rule(40, "data_density = dense", "Выбрать SIS с локальными proportion trends", "Построить categorical ensemble", method="sequential_indicator_simulation", rationale="SIS требует проверки stationarity и connectivity."),
            rule(999, "otherwise", "Построить несколько алгоритмических сценариев", "Сравнить connectivity и flow proxies", human=True, rationale="При слабых данных алгоритм является model-form uncertainty."),
        ],
    },
    {
        "id": "BR_LIT_DEPTH_CONVERSION", "kb": "KB_NS_SEISMIC_STRUCT", "owner": "AG_SEISMIC",
        "label": "Глубинное преобразование и структурная неопределённость", "activity": "SUB_S06_11", "sources": ["SRC_LOCAL_0735", "SRC_LOCAL_0823"],
        "rules": [
            rule(10, "seismic_velocity_calibrated = false", "Не выпускать единственную depth surface", "Калибровать checkshot/VSP/well ties и velocity model", return_="SUB_S06_04", rationale="Неоткалиброванная скорость систематически смещает структуру."),
            rule(20, "depth_uncertainty_material = true", "Построить минимум low/base/high depth scenarios", "Передать структурный ансамбль", method="depth_conversion_scenarios", rationale="Материальная velocity uncertainty должна попасть в объёмы и решения."),
            rule(30, "seismic_velocity_calibrated = true ALL depth_uncertainty_material = false", "Принять depth conversion с картой residuals", "Передать структурной модели", next_="SUB_S07_01", rationale="Даже принятая поверхность сохраняет residual evidence."),
            rule(999, "otherwise", "Приостановить release", "Запросить velocity uncertainty assessment", human=True, rationale="Fallback блокирует ложную точность."),
        ],
    },
    {
        "id": "BR_LIT_FAULT_DECISION", "kb": "KB_NS_SEISMIC_STRUCT", "owner": "AG_STRUCTURAL",
        "label": "Разлом ниже разрешения и сценарии влияния", "activity": "SUB_S07_04", "sources": ["SRC_LOCAL_0823", "SRC_LOCAL_0735"],
        "rules": [
            rule(10, "fault_evidence_confidence = low ALL fault_decision_impact = high", "Не фиксировать разлом детерминированно", "Построить with/without fault scenarios", human=True, method="structural_fault_scenarios", rationale="Слабое evidence и высокий impact требуют model-form scenarios."),
            rule(20, "fault_evidence_confidence = high ALL fault_decision_impact = high", "Включить разлом и варьировать geometry/seal", "Передать fault uncertainty", method="fault_framework_with_uncertainty", rationale="Уверенность в наличии не устраняет uncertainty параметров."),
            rule(30, "fault_decision_impact = low", "Сохранить как интерпретационную гипотезу без лишней сеточной сложности", "Документировать exclusion", rationale="Не каждое сейсмическое нарушение должно дробить grid."),
            rule(999, "otherwise", "Запросить структурный review", "Уточнить confidence и decision impact", human=True, rationale="Два независимых признака обязательны."),
        ],
    },
    {
        "id": "BR_LIT_LEGACY_LOG", "kb": "KB_NS_PETRO", "owner": "AG_PETROPHYSICS",
        "label": "Нормировка исторических ГИС", "activity": "SUB_S08_02", "sources": ["SRC_LOCAL_0002", "SRC_LOCAL_0004", "SRC_LOCAL_0422"],
        "rules": [
            rule(10, "legacy_log_metadata_complete = false", "Запретить молчаливое объединение винтажей", "Восстановить tool, year, units, datum и processing history", human=True, return_="SUB_S02_07", rationale="Кривая без технологического контекста не сопоставима."),
            rule(20, "tool_environment_correction_known = false", "Пометить кривую limited-use", "Оценить bias по перекрывающимся современным данным", method="vintage_bias_estimation", rationale="Неизвестная поправка переносится в uncertainty."),
            rule(30, "legacy_log_metadata_complete = true ALL tool_environment_correction_known = true", "Создать новую processed revision, сохранив raw", "Выполнить environmental corrections и depth match", capability="normalize_well_logs", function="interval_log_import_las_format", rationale="Raw observation остаётся неизменяемой."),
            rule(999, "otherwise", "Перевести интервал в quarantine", "Запросить петрофизический review", human=True, rationale="Fallback предотвращает псевдоточную нормировку."),
        ],
    },
    {
        "id": "BR_LIT_SATURATION_MODEL", "kb": "KB_NS_PETRO", "owner": "AG_PETROPHYSICS",
        "label": "Применимость Archie и shaly-sand модели", "activity": "SUB_S08_09", "sources": ["SRC_LOCAL_0422", "SRC_LOCAL_0658"],
        "rules": [
            rule(10, "conductive_clay_effect = negligible ALL archie_calibration_available = true", "Использовать Archie с калиброванными a,m,n,Rw", "Рассчитать Sw и sensitivity", method="archie_saturation", rationale="Archie применим для чистой водосмачиваемой породы после калибровки."),
            rule(20, "conductive_clay_effect in moderate|strong", "Использовать откалиброванную shaly-sand модель", "Сравнить альтернативы и керн/SCAL", human=True, method="shaly_sand_saturation", rationale="Проводящая глина нарушает предпосылки Archie."),
            rule(30, "archie_calibration_available = false", "Не фиксировать Sw одной формулой", "Оценить ensemble параметров и моделей", human=True, method="saturation_model_ensemble", rationale="Показатели насыщения должны быть калиброваны, а не приняты по умолчанию."),
            rule(999, "otherwise", "Остановить выпуск Sw", "Уточнить минералогию, Rw и wettability", human=True, rationale="Неизвестный clay effect — самостоятельная uncertainty."),
        ],
    },
    {
        "id": "BR_LIT_WELLTEST_DIAGNOSTIC", "kb": "KB_NS_PRESSURE", "owner": "AG_PRESSURE_WELLTEST",
        "label": "Диагностическая последовательность ГДИС", "activity": "SUB_S11_06", "sources": ["SRC_LOCAL_0661", "SRC_LOCAL_0713", "SRC_LOCAL_0053"],
        "rules": [
            rule(10, "pressure_rate_history_qc = false", "Не интерпретировать модель пласта", "Исправить gauge drift, time synchronization, rate history и datum", return_="SUB_S11_02", rationale="Невалидная история создаёт ложные режимы."),
            rule(20, "wellbore_storage_dominates = true", "Не выбирать boundary model по раннему времени", "Продлить shut-in или применить validated deconvolution", human=True, method="welltest_storage_diagnostic", rationale="Wellbore storage скрывает пластовый отклик."),
            rule(30, "diagnostic_regime_identified = true ALL pressure_rate_history_qc = true", "Подбирать модели, совместимые с derivative regime", "Оценить параметры и non-uniqueness", method="pressure_derivative_model_selection", rationale="Диагностика предшествует curve fitting."),
            rule(999, "otherwise", "Сохранить несколько допустимых моделей", "Запросить дополнительный test design", human=True, rationale="Неидентифицируемость должна быть явной."),
        ],
    },
    {
        "id": "BR_LIT_PRESSURE_DATUM", "kb": "KB_NS_PRESSURE", "owner": "AG_PRESSURE_WELLTEST",
        "label": "Согласование давлений и контактов", "activity": "SUB_S11_09", "sources": ["SRC_LOCAL_0661", "SRC_LOCAL_0713"],
        "rules": [
            rule(10, "pressure_datum_consistent = false", "Запретить построение единого pressure field", "Привести datum, density/PVT, time и shut-in state", return_="SUB_S11_03", rationale="Смешение datum и режимов имитирует compartments."),
            rule(20, "pressure_datum_consistent = true ALL contradiction_count > 0", "Сохранить альтернативы compartment/contact", "Эскалировать структурному и PVT-агентам", human=True, method="pressure_compartment_scenarios", rationale="Остаточное противоречие может быть геологическим."),
            rule(30, "pressure_datum_consistent = true ALL contradiction_count = 0", "Интерполировать в пределах гидродинамически обоснованных доменов", "Передать pressure field", method="domain_constrained_pressure_interpolation", next_="SUB_S12_01", rationale="Интерполяция не должна пересекать неподтверждённые барьеры."),
            rule(999, "otherwise", "Не объединять наблюдения", "Запросить pressure data review", human=True, rationale="Fallback сохраняет исходные наблюдения."),
        ],
    },
    {
        "id": "BR_LIT_GEOMECH_COUPLING", "kb": "KB_NS_GEOMECH", "owner": "AG_GEOMECHANICS",
        "label": "Выбор уровня геомеханического сопряжения", "activity": "SUB_S13_09", "sources": ["SRC_LOCAL_0069", "SRC_LOCAL_1444"],
        "rules": [
            rule(10, "mem_calibrated = false", "Не запускать predictive 3D geomechanics", "Калибровать 1D MEM по LOT/XLOT/DFIT, breakout/DITF и плотности", human=True, return_="SUB_S13_04", rationale="3D модель наследует bias некалиброванной MEM."),
            rule(20, "depletion_geomech_coupling_material = true ALL stress_calibration_data_available = true", "Выбрать coupled/iteratively coupled model", "Оценить compaction, subsidence, fault reactivation и permeability feedback", method="coupled_geomechanical_simulation", capability="run_geomechanics", rationale="Материальная обратная связь требует сопряжения."),
            rule(30, "depletion_geomech_coupling_material = false ALL mem_calibrated = true", "Использовать one-way geomechanical assessment", "Передать stress-sensitive limits", method="one_way_geomechanical_assessment", rationale="Полное сопряжение не требуется без material impact."),
            rule(999, "otherwise", "Выполнить sensitivity до выбора coupling", "Запросить геомеханический review", human=True, rationale="Неизвестная materiality не является основанием для сложной модели."),
        ],
    },
    {
        "id": "BR_LIT_GEOSTAT_TREND", "kb": "KB_NS_GEOSTAT", "owner": "AG_GEOSTATISTICS",
        "label": "Declustering, trend и stationarity", "activity": "SUB_S14_03", "sources": ["SRC_LOCAL_0748", "SRC_LOCAL_0757"],
        "rules": [
            rule(10, "preferential_sampling_detected = true", "Применить и задокументировать declustering weights", "Оценить sensitivity статистик", method="declustered_statistics", rationale="Скважины редко образуют случайную выборку."),
            rule(20, "trend_material = true ALL residual_stationary = true", "Моделировать trend и residual раздельно", "Симулировать residual и вернуть trend", method="trend_residual_geostatistics", rationale="Вариограмма остатка не должна поглощать крупномасштабный тренд."),
            rule(30, "trend_material = true ALL residual_stationary = false", "Разбить на geological domains или nonstationary scenario", "Пересмотреть домен и координаты", human=True, method="nonstationary_domain_model", rationale="Stationarity — проверяемая предпосылка, а не default."),
            rule(999, "otherwise", "Не фиксировать variogram model", "Выполнить directional pairs и cross-validation", human=True, rationale="Недостаток пар переносится в uncertainty range."),
        ],
    },
    {
        "id": "BR_LIT_UNCERT_AGGREGATION", "kb": "KB_NS_UNCERTAINTY", "owner": "AG_UNCERTAINTY",
        "label": "Агрегация неопределённостей и корреляций", "activity": "SUB_S16_06", "sources": ["SRC_LOCAL_0764", "SRC_LOCAL_0757", "STD_PRMS"],
        "rules": [
            rule(10, "aggregation_requested = true ALL dependent_parameters_present = true ALL correlation_model_validated = false", "Запретить независимое перемножение и сумму квантилей", "Калибровать joint dependence/copula/correlation", human=True, rationale="Зависимости изменяют хвосты распределения."),
            rule(20, "aggregation_requested = true ALL correlation_model_validated = true", "Агрегировать Monte Carlo samples совместно", "Рассчитать квантили суммы", method="correlated_monte_carlo_aggregation", rationale="P90/P50/P10 компонентов нельзя складывать напрямую."),
            rule(30, "aggregation_requested = false", "Сохранять распределение объекта без искусственного risk factor", "Передать условные и risked metrics раздельно", method="conditional_resource_distribution", rationale="Chance of success и условный объём — разные сущности."),
            rule(999, "otherwise", "Не публиковать агрегированные квантили", "Запросить uncertainty review", human=True, rationale="Fallback блокирует неверную арифметику квантилей."),
        ],
    },
    {
        "id": "BR_LIT_VINTAGE_REPROCESS", "kb": "KB_NS_LIFECYCLE", "owner": "AG_LIFECYCLE",
        "label": "Переобработка исторического винтажа", "activity": "SUB_S18_03", "sources": ["SRC_LOCAL_0004", "STD_PROVO"],
        "rules": [
            rule(10, "raw_observation_available = false", "Не заменять текущую интерпретацию автоматически", "Оцифровать источник или зафиксировать unrecoverable lineage gap", human=True, rationale="Без raw нельзя отличить улучшение метода от изменения данных."),
            rule(20, "raw_observation_available = true ALL reprocessing_method_changed = true", "Создать новую processed revision", "Сравнить old/new и распространить impact", capability="create_processed_revision", rationale="Raw immutable; обработка versioned и supersedes, но не стирает прошлое."),
            rule(30, "new_vintage_impact = high ALL impact_graph_available = true", "Запустить selective rebuild всех зависимых артефактов", "Сформировать новый ensemble revision", capability="selective_model_rebuild", rationale="Эволюция трассируется через dependency closure."),
            rule(999, "otherwise", "Сохранить оба винтажа без merge", "Назначить custodian review", human=True, rationale="Неизвестное происхождение нельзя усреднять."),
        ],
    },
    {
        "id": "BR_NS_SOFTWARE_CALL", "kb": "KB_NS_SOFTWARE", "owner": "AG_SOFTWARE_BROKER",
        "label": "Безопасный вызов tNavigator/GeoVation/Petrel", "activity": "SUB_S18_09", "sources": ["SRC_LOCAL_1444", "STD_PROVO"],
        "rules": [
            rule(10, "capability_verified = false", "Не вызывать целевое ПО", "Проверить установленную версию, лицензию, сигнатуру и права", human=True, capability="verify_software_capability", rationale="Строка из руководства является кандидатом, а не контрактом вызова."),
            rule(20, "software_mutates_project = true ALL dry_run_passed = false", "Исполнять только на copy-on-write sandbox", "Проверить idempotency, timeout и compensation", human=True, capability="sandbox_replay", rationale="Изменение проекта требует возможности rollback."),
            rule(30, "capability_verified = true ALL dry_run_passed = true ALL plan_ir_valid = true", "Разрешить вызов в границах профиля", "Выполнить и проверить postconditions", capability="execute_software_operation", rationale="Допуск относится к версии адаптера и конкретному PlanIR."),
            rule(40, "postconditions_passed = false", "Откатить revision и зарегистрировать FailureCandidate", "Запустить recovery plan", capability="rollback_project_revision", rationale="Успешный HTTP/RPC ответ не доказывает корректность модели."),
            rule(999, "otherwise", "Остановить вызов", "Запросить software capability owner", human=True, rationale="Safe fallback для неизвестного состояния."),
        ],
    },
]


def split_guard(guard: str) -> tuple[str, list[tuple[str, str, str]]]:
    if guard == "otherwise":
        return "DEFAULT", []
    if " ANY " in guard:
        operator, parts = "ANY", guard.split(" ANY ")
    else:
        operator, parts = "ALL", guard.split(" ALL ")
    atoms: list[tuple[str, str, str]] = []
    for part in parts:
        tokens = part.strip().split(" ", 2)
        if len(tokens) != 3 or tokens[1] not in {"=", "!=", "<", "<=", ">", ">=", "in", "not in"}:
            raise ValueError(f"Некорректный guard: {guard!r}")
        atoms.append((tokens[0], tokens[1], tokens[2]))
    return operator, atoms


def first_iri(outgoing: dict[tuple[str, str], list[str]], subject: str, predicate: str) -> str | None:
    for token in outgoing.get((subject, predicate), []):
        if value := as_iri(token):
            return value
    return None


def first_literal(outgoing: dict[tuple[str, str], list[str]], subject: str, predicate: str) -> str:
    values = outgoing.get((subject, predicate), [])
    return as_literal(values[0]) if values else ""


def add_formal_guard(lines: set[str], rule_id: str, guard: str, belief_by_code: dict[str, str]) -> None:
    operator, atoms = split_guard(guard)
    add_l(lines, rule_id, BDI + "guardExpression", guard)
    add_l(lines, rule_id, BDI + "isDefault", operator == "DEFAULT", datatype=XSD + "boolean")
    if operator == "DEFAULT":
        return
    group_id = BDI + "CG_V41_" + hashlib.sha1((rule_id + guard).encode("utf-8")).hexdigest()[:16].upper()
    type_label(lines, group_id, BDI + "ConditionGroup", f"Группа условий {local(rule_id)}")
    add_l(lines, group_id, BDI + "logicalOperator", operator)
    add_i(lines, rule_id, BDI + "hasConditionGroup", group_id)
    for index, (code, comparator, expected) in enumerate(atoms, start=1):
        if code not in belief_by_code:
            bid = BDI + "BELIEF_NS_" + re.sub(r"[^A-Za-z0-9]+", "_", code.upper()).strip("_")
            belief_by_code[code] = bid
            kind, allowed, label = BELIEF_DEFS.get(code, ("string", "", code))
            type_label(lines, bid, BDI + "BeliefVariable", label)
            add_l(lines, bid, BDI + "beliefCode", code)
            add_l(lines, bid, BDI + "variableType", kind)
            if allowed:
                add_l(lines, bid, BDI + "allowedValues", allowed)
        condition_id = BDI + "COND_V41_" + hashlib.sha1((rule_id + str(index) + code + comparator + expected).encode("utf-8")).hexdigest()[:16].upper()
        type_label(lines, condition_id, BDI + "AtomicCondition", f"{code} {comparator} {expected}")
        add_i(lines, group_id, BDI + "hasCondition", condition_id)
        add_i(lines, condition_id, BDI + "evaluatesBelief", belief_by_code[code])
        add_l(lines, condition_id, BDI + "comparator", comparator)
        add_l(lines, condition_id, BDI + "expectedValue", expected)


def add_rule_branch(lines: set[str], branch: dict[str, object], belief_by_code: dict[str, str]) -> list[dict[str, object]]:
    branch_id = BDI + str(branch["id"])
    kb_id = BDI + str(branch["kb"])
    profile_id = BDI + str(branch["owner"])
    type_label(lines, kb_id, BDI + "AgentKnowledgeBase", f"База знаний: {branch['label']}")
    add_i(lines, profile_id, BDI + "usesKnowledgeBase", kb_id)
    type_label(lines, branch_id, BDI + "BranchPoint", str(branch["label"]))
    add_i(lines, kb_id, BDI + "hasBranchPoint", branch_id)
    add_i(lines, branch_id, BDI + "belongsToKnowledgeBase", kb_id)
    add_i(lines, branch_id, BDI + "appliesToActivity", GM + str(branch["activity"]))
    add_i(lines, branch_id, BDI + "governsActivity", GM + str(branch["activity"]))
    add_l(lines, branch_id, BDI + "questionText", str(branch["label"]))
    add_l(lines, branch_id, BDI + "hitPolicy", "PRIORITY")
    add_l(lines, branch_id, BDI + "missingDataPolicy", "UNKNOWN -> safe fallback; запрещён closed-world вывод false")
    add_l(lines, branch_id, BDI + "conflictPolicy", "PRIORITY; равный приоритет или противоречие -> quarantine и эскалация")
    add_l(lines, branch_id, BDI + "decisionScope", "NEUROSYMBOLIC_OR_LITERATURE_BRANCH")
    evidence_id = BDI + "EVID_V41_" + str(branch["id"])
    type_label(lines, evidence_id, BDI + "EvidenceRequirement", f"Evidence package: {branch['label']}", "Belief snapshot, source revisions, project policy, rule version, PlanIR, metacritic findings и owner decision.")
    add_i(lines, branch_id, BDI + "requiresEvidence", evidence_id)
    for source in branch.get("sources", []):
        add_i(lines, evidence_id, BDI + "evidenceArtifact", GM + str(source))
    rows: list[dict[str, object]] = []
    for item in branch["rules"]:
        item = dict(item)
        rule_id = BDI + f"RULE_{branch['id']}_{int(item['priority']):03d}"
        type_label(lines, rule_id, BDI + "DecisionRule", f"{branch['label']}: {item['intention']}")
        add_i(lines, branch_id, BDI + "hasRule", rule_id)
        add_l(lines, rule_id, BDI + "rulePriority", item["priority"], datatype=XSD + "integer")
        add_l(lines, rule_id, BDI + "priority", item["priority"], datatype=XSD + "integer")
        add_formal_guard(lines, rule_id, str(item["guard"]), belief_by_code)
        outcome_id = BDI + "OUT_" + hashlib.sha1((local(rule_id) + str(item["outcome"])).encode("utf-8")).hexdigest()[:16].upper()
        intention_id = BDI + "INT_" + hashlib.sha1((local(rule_id) + str(item["intention"])).encode("utf-8")).hexdigest()[:16].upper()
        type_label(lines, outcome_id, BDI + "DecisionOutcome", str(item["outcome"]))
        type_label(lines, intention_id, BDI + "Intention", str(item["intention"]))
        add_i(lines, rule_id, BDI + "concludesOutcome", outcome_id)
        add_i(lines, rule_id, BDI + "setsIntention", intention_id)
        add_l(lines, rule_id, BDI + "outcomeText", item["outcome"])
        add_l(lines, rule_id, BDI + "intentionText", item["intention"])
        add_l(lines, rule_id, BDI + "requiresHumanApproval", item["human"], datatype=XSD + "boolean")
        add_l(lines, rule_id, BDI + "rationale", item["rationale"], lang="ru")
        add_l(lines, rule_id, BDI + "knowledgeStatus", item["status"])
        add_l(lines, rule_id, BDI + "executionEligibility", "PRODUCTION_AFTER_PROJECT_APPROVAL" if str(item["status"]).startswith("APPROVED") else "SANDBOX_OR_SHADOW")
        if item["method"]:
            method_id = GM + "METHOD_NS_" + re.sub(r"[^A-Za-z0-9]+", "_", str(item["method"]).upper()).strip("_")
            type_label(lines, method_id, GM + "Method", str(item["method"]))
            add_i(lines, rule_id, BDI + "selectsMethod", method_id)
        if item["capability"]:
            cap_id = BDI + "CAP_" + re.sub(r"[^A-Za-z0-9]+", "_", str(item["capability"]).upper()).strip("_")
            type_label(lines, cap_id, BDI + "Capability", str(item["capability"]))
            add_i(lines, rule_id, BDI + "invokesCapability", cap_id)
            add_l(lines, rule_id, BDI + "requestedCapability", item["capability"])
        if item["function"]:
            function_id = GM + "TNAV_CALL_" + re.sub(r"[^A-Za-z0-9]+", "_", str(item["function"]).upper()).strip("_")
            add_i(lines, rule_id, BDI + "selectsFunction", function_id)
            add_l(lines, rule_id, BDI + "requestedFunctionCode", item["function"])
        if item["next"]:
            add_i(lines, rule_id, BDI + "advancesToActivity", GM + str(item["next"]))
        if item["return"]:
            add_i(lines, rule_id, BDI + "returnsToActivity", GM + str(item["return"]))
        for source in branch.get("sources", []):
            add_i(lines, rule_id, BDI + "supportedBy", GM + str(source))
        if str(item["guard"]) == "otherwise":
            add_i(lines, branch_id, BDI + "hasFallbackRule", rule_id)
        rows.append({
            "knowledge_base": branch["kb"], "branch_id": branch["id"], "branch": branch["label"],
            "activity": branch["activity"], "hit_policy": "PRIORITY", "rule_id": local(rule_id),
            "priority": item["priority"], "guard": item["guard"], "outcome": item["outcome"],
            "intention": item["intention"], "requires_human_approval": str(item["human"]).lower(),
            "selected_method": item["method"], "selected_function": item["function"],
            "requested_capability": item["capability"], "next_activity": item["next"],
            "return_activity": item["return"], "rationale": item["rationale"],
            "knowledge_status": item["status"],
            "execution_eligibility": "PRODUCTION_AFTER_PROJECT_APPROVAL" if str(item["status"]).startswith("APPROVED") else "SANDBOX_OR_SHADOW",
            "source_ids": ";".join(str(x) for x in branch.get("sources", [])),
        })
    return rows


def enrich_base(base_lines: set[str], extension: set[str], belief_by_code: dict[str, str]) -> None:
    types, outgoing = parse(base_lines)
    branches = sorted(subject for subject, values in types.items() if BDI + "BranchPoint" in values)
    kb_by_branch: dict[str, str] = {}
    for (subject, predicate), tokens in outgoing.items():
        if predicate == BDI + "hasBranchPoint":
            for token in tokens:
                if target := as_iri(token):
                    kb_by_branch[target] = subject
    type_label(extension, BDI + "EVIDENCE_BASE_TRANSITION", BDI + "EvidenceRequirement", "Минимальный evidence package перехода", "Belief snapshot, rule/version, source revisions, QA findings, assumption/uncertainty registers и GateDecision.")
    for branch in branches:
        if branch in kb_by_branch:
            add_i(extension, branch, BDI + "belongsToKnowledgeBase", kb_by_branch[branch])
        activity = first_iri(outgoing, branch, BDI + "appliesToActivity") or first_iri(outgoing, branch, BDI + "governsActivity")
        if activity:
            add_i(extension, branch, BDI + "appliesToActivity", activity)
            add_i(extension, branch, BDI + "governsActivity", activity)
        label = first_literal(outgoing, branch, RDFS + "label") or local(branch)
        add_l(extension, branch, BDI + "questionText", label)
        add_l(extension, branch, BDI + "missingDataPolicy", "UNKNOWN -> safe fallback; запрос evidence; closed-world inference запрещён")
        add_l(extension, branch, BDI + "conflictPolicy", "PRIORITY; конфликт -> сохранить версии, quarantine и эскалировать владельцам")
        add_i(extension, branch, BDI + "requiresEvidence", BDI + "EVIDENCE_BASE_TRANSITION")
        add_l(extension, branch, BDI + "decisionScope", "TRANSITION_GATE" if local(branch).startswith("BR_EV_") else "DOMAIN_DECISION")
        linked_rules = [value for token in outgoing.get((branch, BDI + "hasRule"), []) if (value := as_iri(token))]
        fallbacks: list[str] = []
        for rid in linked_rules:
            guard = first_literal(outgoing, rid, BDI + "guardExpression")
            priority = first_literal(outgoing, rid, BDI + "rulePriority") or first_literal(outgoing, rid, BDI + "priority")
            if priority:
                add_l(extension, rid, BDI + "rulePriority", int(priority), datatype=XSD + "integer")
            is_default = guard == "otherwise" or priority in {"99", "999"}
            add_l(extension, rid, BDI + "isDefault", is_default, datatype=XSD + "boolean")
            add_l(extension, rid, BDI + "knowledgeStatus", "GENERATED_TRANSITION_GATE" if local(rid).startswith("RULE_EV_") else "IMPORTED_V3_REVIEWED")
            add_l(extension, rid, BDI + "executionEligibility", "PROJECT_POLICY_REQUIRED")
            if is_default:
                fallbacks.append(rid)
            if local(rid).startswith("RULE_EV_") and guard and not outgoing.get((rid, BDI + "hasConditionGroup")):
                normalized = guard.replace(" OR ", " ANY ")
                add_formal_guard(extension, rid, normalized, belief_by_code)
            if not outgoing.get((rid, BDI + "concludesOutcome")):
                outcome = first_literal(outgoing, rid, BDI + "outcomeText")
                intention = first_literal(outgoing, rid, BDI + "intentionText")
                out_id = BDI + "OUT_BASE_" + hashlib.sha1(outcome.encode("utf-8")).hexdigest()[:12].upper()
                int_id = BDI + "INT_BASE_" + hashlib.sha1(intention.encode("utf-8")).hexdigest()[:12].upper()
                type_label(extension, out_id, BDI + "DecisionOutcome", outcome)
                type_label(extension, int_id, BDI + "Intention", intention)
                add_i(extension, rid, BDI + "concludesOutcome", out_id)
                add_i(extension, rid, BDI + "setsIntention", int_id)
        if fallbacks:
            add_i(extension, branch, BDI + "hasFallbackRule", sorted(fallbacks)[0])


def branch_metrics(lines: set[str]) -> dict[str, int]:
    types, outgoing = parse(lines)
    branches = {s for s, values in types.items() if BDI + "BranchPoint" in values}
    rules = {s for s, values in types.items() if BDI + "DecisionRule" in values}
    def with_pred(subjects: set[str], predicate: str) -> int:
        return sum(bool(outgoing.get((subject, predicate))) for subject in subjects)
    formal = 0
    for rid in rules:
        guard = first_literal(outgoing, rid, BDI + "guardExpression")
        if guard == "otherwise" or outgoing.get((rid, BDI + "hasConditionGroup")):
            formal += 1
    return {
        "branches": len(branches), "rules": len(rules),
        "branches_with_owner_kb": with_pred(branches, BDI + "belongsToKnowledgeBase"),
        "branches_with_activity": sum(bool(outgoing.get((b, BDI + "appliesToActivity")) or outgoing.get((b, BDI + "governsActivity"))) for b in branches),
        "branches_with_missing_policy": with_pred(branches, BDI + "missingDataPolicy"),
        "branches_with_conflict_policy": with_pred(branches, BDI + "conflictPolicy"),
        "branches_with_evidence": with_pred(branches, BDI + "requiresEvidence"),
        "branches_with_fallback": with_pred(branches, BDI + "hasFallbackRule"),
        "rules_with_formal_guard": formal,
        "rules_with_human_gate": with_pred(rules, BDI + "requiresHumanApproval"),
    }


def main() -> None:
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    base_lines = {line for line in BASE_BDI.read_text(encoding="utf-8").splitlines() if line.strip()}
    main_lines = {line for line in BASE_MAIN.read_text(encoding="utf-8").splitlines() if line.strip()}
    base_types, base_outgoing = parse(base_lines)
    extension: set[str] = set()

    ontology_id = ONT + "21_neurosymbolic_agents"
    add_i(extension, ontology_id, RDF + "type", OWL + "Ontology")
    add_l(extension, ontology_id, RDFS + "label", "Нейросимвольные BDI-агенты и автономные правила v4.1", lang="ru")
    add_l(extension, ontology_id, OWL + "versionInfo", "4.1.0")
    add_l(extension, ontology_id, DCT + "modified", date.today().isoformat(), datatype=XSD + "date")
    add_i(extension, ontology_id, OWL + "imports", ONT + "20_agent_knowledge")

    for class_name, label in CLASSES:
        add_i(extension, BDI + class_name, RDF + "type", OWL + "Class")
        add_l(extension, BDI + class_name, RDFS + "label", label, lang="ru")
    for child in ["FactCandidate", "RuleCandidate", "PlanCandidate", "CaseCandidate", "MethodCandidate", "FailureCandidate"]:
        add_i(extension, BDI + child, RDFS + "subClassOf", BDI + "KnowledgeCandidate")
    for name in OBJECT_PROPERTIES:
        add_i(extension, BDI + name, RDF + "type", OWL + "ObjectProperty")
    for name in DATA_PROPERTIES:
        add_i(extension, BDI + name, RDF + "type", OWL + "DatatypeProperty")

    runtime_id = BDI + "TYPICAL_AGENT_RUNTIME_V41"
    type_label(extension, runtime_id, BDI + "TypicalAgentRuntime", "TypicalAgentRuntime v4.1", "Единый BDI-LLM runtime; специализация задаётся профилем, срезом онтологии, БЗ, правами и capabilities.")
    previous_module = ""
    for module_id, label, function in RUNTIME_MODULES:
        subject = BDI + module_id
        type_label(extension, subject, BDI + "RuntimeModule", label, function)
        add_l(extension, subject, BDI + "moduleFunction", function, lang="ru")
        add_i(extension, runtime_id, BDI + "hasRuntimeModule", subject)
        if previous_module:
            add_i(extension, BDI + previous_module, BDI + "feedsModule", subject)
        previous_module = module_id

    for mode_id, label, threshold in [
        ("MODE_SYMBOLIC", "SYMBOLIC — утверждённый PlanSpec", "coverage >= project_symbolic_threshold"),
        ("MODE_HYBRID", "HYBRID — синтез только выявленного пробела", "project_hybrid_threshold <= coverage < project_symbolic_threshold"),
        ("MODE_GENERATIVE", "GENERATIVE — несколько PlanDraft в sandbox", "coverage < project_hybrid_threshold"),
    ]:
        type_label(extension, BDI + mode_id, BDI + "OperationMode", label)
        add_l(extension, BDI + mode_id, BDI + "coverageThreshold", threshold)
        add_i(extension, runtime_id, BDI + "selectsOperationMode", BDI + mode_id)

    for level, label, authority in [
        ("A0", "Наблюдение и объяснение", "нет права изменения"),
        ("A1", "Рекомендация", "человек выбирает план"),
        ("A2", "Sandbox / shadow исполнение", "изоляция и обязательный gate"),
        ("A3", "Ограниченное production-исполнение", "только APPROVED knowledge, verified capability и low-risk scope"),
    ]:
        policy_id = BDI + "AUTONOMY_" + level
        type_label(extension, policy_id, BDI + "AutonomyPolicy", f"{level}: {label}")
        add_l(extension, policy_id, BDI + "approvalAuthority", authority, lang="ru")

    metacritic_id = BDI + "METACRITIC_PIPELINE_V41"
    type_label(extension, metacritic_id, BDI + "MetacriticPipeline", "Независимый метакритик", "SHACL → process predicates → physics validators → cross-model checks → statistics → GateDecision. LLM объясняет findings, но не отменяет нарушение.")
    for gate in ["GATE_SCHEMA", "GATE_PROCESS", "GATE_PHYSICS", "GATE_CROSS_MODEL", "GATE_STATISTICS", "GATE_RELEASE"]:
        type_label(extension, BDI + gate, BDI + "GateDecision", gate.replace("GATE_", "Контроль: ").replace("_", " "))
        add_i(extension, metacritic_id, BDI + "requiresGate", BDI + gate)

    for group_id, label in AGENT_GROUPS:
        type_label(extension, BDI + group_id, BDI + "AgentGroup", label)

    agent_rows: list[dict[str, object]] = []
    stage_owner: dict[str, str] = {}
    for profile_id, label, group, stages, autonomy, scope in AGENT_PROFILES:
        subject = BDI + profile_id
        type_label(extension, subject, BDI + "DomainAgentProfile", label, scope)
        add_l(extension, subject, BDI + "profileCode", profile_id)
        add_l(extension, subject, BDI + "scopeText", scope, lang="ru")
        add_l(extension, subject, BDI + "defaultAutonomyLevel", autonomy)
        add_l(extension, subject, BDI + "allowedOperationMode", "SYMBOLIC|HYBRID|GENERATIVE_PROPOSAL_ONLY")
        add_i(extension, subject, BDI + "usesRuntime", runtime_id)
        add_i(extension, subject, BDI + "belongsToAgentGroup", BDI + group)
        for stage in stages.split(","):
            add_i(extension, subject, BDI + "ownsProcessStage", GM + "EV_STAGE_" + stage)
            add_i(extension, subject, BDI + "usesKnowledgeBase", BDI + "KB_EV_" + stage)
            if profile_id not in {"AG_ORCHESTRATOR", "AG_MODEL_INTEGRATOR", "AG_QA_REMEDIATION"}:
                stage_owner.setdefault(stage, profile_id)
        agent_rows.append({
            "profile_id": profile_id, "agent": label, "group": group, "stages": stages,
            "default_autonomy": autonomy, "runtime": local(runtime_id), "scope": scope,
            "symbolic_mode": "execute approved PlanSpec", "hybrid_mode": "fill bounded CoverageReport gap",
            "generative_mode": "propose PlanDraft; sandbox and human gate only",
        })

    # The primary owner is explicit even when several profiles read the same stage.
    stage_owner.update({
        "S01": "AG_ORCHESTRATOR", "S02": "AG_DATA_STEWARD", "S03": "AG_REGIONAL_PLAY",
        "S04": "AG_STRATIGRAPHY", "S05": "AG_SEDIMENTOLOGY", "S06": "AG_SEISMIC",
        "S07": "AG_STRUCTURAL", "S08": "AG_PETROPHYSICS", "S09": "AG_ROCKTYPE",
        "S10": "AG_FACIES", "S11": "AG_PRESSURE_WELLTEST", "S12": "AG_PVT_SCAL",
        "S13": "AG_GEOMECHANICS", "S14": "AG_GEOSTATISTICS", "S15": "AG_GRID_VOLUMETRICS",
        "S16": "AG_UNCERTAINTY", "S17": "AG_DYNAMIC_4D", "S18": "AG_LIFECYCLE",
    })

    # Explicit handoffs make ownership, required evidence and rollback targets visible.
    handoff_rows: list[dict[str, object]] = []
    ordered_stages = [f"S{i:02d}" for i in range(1, 19)]
    for source_stage, target_stage in zip(ordered_stages, ordered_stages[1:]):
        source_profile = stage_owner.get(source_stage, "AG_ORCHESTRATOR")
        target_profile = stage_owner.get(target_stage, "AG_ORCHESTRATOR")
        handoff_id = BDI + f"HANDOFF_{source_stage}_{target_stage}"
        type_label(extension, handoff_id, BDI + "HandoffContract", f"Передача {source_stage} → {target_stage}")
        add_i(extension, handoff_id, BDI + "handoffFrom", BDI + source_profile)
        add_i(extension, handoff_id, BDI + "handoffTo", BDI + target_profile)
        add_i(extension, handoff_id, BDI + "requiresGate", BDI + "GATE_RELEASE")
        add_l(extension, handoff_id, BDI + "inputContract", "immutable artifact refs; versions; units/CRS; belief snapshot; QA findings; assumptions; uncertainties")
        add_l(extension, handoff_id, BDI + "outputContract", "accept|reject|conditional; owner; rationale; next/return activity; evidence package hash")
        add_l(extension, handoff_id, BDI + "recoveryAction", f"return to {source_stage} owner without overwriting accepted revision")
        add_i(extension, BDI + source_profile, BDI + "hasHandoffContract", handoff_id)
        handoff_rows.append({
            "handoff_id": local(handoff_id), "from_stage": source_stage, "from_agent": source_profile,
            "to_stage": target_stage, "to_agent": target_profile, "gate": "GATE_RELEASE",
            "required": "artifact revisions; lineage; units/CRS; QA; assumptions; uncertainties; evidence hash",
            "on_reject": f"return to {source_stage}; preserve rejected revision",
        })

    belief_by_code: dict[str, str] = {}
    for subject, values in base_types.items():
        if BDI + "BeliefVariable" in values:
            code = first_literal(base_outgoing, subject, BDI + "beliefCode")
            if code:
                belief_by_code[code] = subject
    for code, (kind, allowed, label) in BELIEF_DEFS.items():
        if code in belief_by_code:
            continue
        bid = BDI + "BELIEF_NS_" + re.sub(r"[^A-Za-z0-9]+", "_", code.upper()).strip("_")
        belief_by_code[code] = bid
        type_label(extension, bid, BDI + "BeliefVariable", label)
        add_l(extension, bid, BDI + "beliefCode", code)
        add_l(extension, bid, BDI + "variableType", kind)
        if allowed:
            add_l(extension, bid, BDI + "allowedValues", allowed)

    enrich_base(base_lines, extension, belief_by_code)
    extension_rule_rows: list[dict[str, object]] = []
    for branch in BRANCHES:
        extension_rule_rows.extend(add_rule_branch(extension, branch, belief_by_code))

    extension_header = {
        f"<{ONT}agent-extension-all> <{RDF}type> <{OWL}Ontology> .",
        f"<{ONT}agent-extension-all> <{OWL}versionInfo> \"4.1.0\" .",
        f"<{ONT}agent-extension-all> <{OWL}imports> <{ONT}21_neurosymbolic_agents> .",
    }
    extension_all = extension | extension_header
    (AGENT_DIR / "NeurosymbolicAgentOntology_v4_1.rdf").write_text("\n".join(sorted(extension_all)) + "\n", encoding="utf-8")
    combined_bdi = base_lines | extension_all | {
        f"<{ONT}bdi-all-v4-1> <{RDF}type> <{OWL}Ontology> .",
        f"<{ONT}bdi-all-v4-1> <{OWL}versionInfo> \"4.1.0\" .",
        f"<{ONT}bdi-all-v4-1> <{PROV}wasRevisionOf> <{ONT}bdi-all> .",
    }
    combined_bdi_path = BDI_DIR / "BDI_KnowledgeBase_v4_1_AllInOne.rdf"
    combined_bdi_path.write_text("\n".join(sorted(combined_bdi)) + "\n", encoding="utf-8")
    combined_main = main_lines | extension_all | {
        f"<{ONT}all-v4-1-agent-extended> <{RDF}type> <{OWL}Ontology> .",
        f"<{ONT}all-v4-1-agent-extended> <{OWL}versionInfo> \"4.1.0-agent-extension\" .",
        f"<{ONT}all-v4-1-agent-extended> <{PROV}wasRevisionOf> <{ONT}all> .",
    }
    combined_main_path = HERE / "GeoModelingEvolutionOntology_v4_1_AgentExtended_AllInOne.rdf"
    combined_main_path.write_text("\n".join(sorted(combined_main)) + "\n", encoding="utf-8")

    # Consolidate the previously split v3 and v4 rule tables into one executable contract.
    v3_rows = list(csv.DictReader((V3_BDI / "decision_tables.csv").open(encoding="utf-8-sig", newline="")))
    v4_rows = list(csv.DictReader((BDI_DIR / "decision_tables.csv").open(encoding="utf-8-sig", newline="")))
    decision_fields = [
        "knowledge_base", "branch_id", "branch", "activity", "hit_policy", "rule_id", "priority",
        "guard", "outcome", "intention", "requires_human_approval", "selected_method", "selected_function",
        "requested_capability", "next_activity", "return_activity", "rationale", "knowledge_status",
        "execution_eligibility", "source_ids",
    ]
    consolidated: list[dict[str, object]] = []
    for row in v3_rows:
        normalized = dict(row)
        normalized.update({
            "knowledge_status": "IMPORTED_V3_REVIEWED", "execution_eligibility": "PROJECT_POLICY_REQUIRED",
            "requested_capability": "", "source_ids": "v3_bdi_sources",
        })
        consolidated.append(normalized)
    for row in v4_rows:
        normalized = dict(row)
        normalized["guard"] = normalized.get("guard", "").replace(" OR ", " ANY ")
        normalized.update({
            "selected_method": "", "selected_function": "", "requested_capability": "",
            "next_activity": "", "return_activity": "EV_STAGE_" + normalized.get("return_stage", ""),
            "knowledge_status": "GENERATED_TRANSITION_GATE", "execution_eligibility": "PROJECT_POLICY_REQUIRED",
            "source_ids": "SRC_LOCAL_0002;STD_SHACL12",
        })
        consolidated.append(normalized)
    consolidated.extend(extension_rule_rows)
    write_csv(AGENT_DIR / "decision_tables_v4_1.csv", consolidated, decision_fields)
    write_csv(AGENT_DIR / "literature_and_architecture_rules.csv", extension_rule_rows, decision_fields)

    belief_rows = list(csv.DictReader((V3_BDI / "belief_schema.csv").open(encoding="utf-8-sig", newline="")))
    by_code = {row["belief_code"]: row for row in belief_rows}
    for code, (kind, allowed, label) in BELIEF_DEFS.items():
        by_code.setdefault(code, {
            "belief_code": code, "belief_id": local(belief_by_code[code]), "variable_type": kind,
            "allowed_values": allowed, "label": label, "unit": "",
        })
    belief_fields = ["belief_id", "belief_code", "label", "variable_type", "allowed_values", "unit"]
    belief_rows_out = sorted(by_code.values(), key=lambda row: row["belief_code"])
    write_csv(AGENT_DIR / "belief_schema_v4_1.csv", belief_rows_out, belief_fields)
    write_csv(AGENT_DIR / "agent_profiles.csv", agent_rows, list(agent_rows[0]))
    write_csv(AGENT_DIR / "handoff_contracts.csv", handoff_rows, list(handoff_rows[0]))

    before = branch_metrics(base_lines)
    after = branch_metrics(combined_bdi)
    schema_codes = set(by_code)
    guard_codes: set[str] = set()
    unparseable: list[str] = []
    for row in consolidated:
        try:
            _, atoms = split_guard(str(row["guard"]))
            guard_codes.update(code for code, _, _ in atoms)
        except ValueError:
            unparseable.append(str(row["rule_id"]))
    missing_schema = sorted(guard_codes - schema_codes)
    qaqc_rows = list(csv.DictReader((HERE / "qaqc_rules.csv").open(encoding="utf-8-sig", newline="")))
    tnav_rows = list(csv.DictReader((HERE / "tnavigator_functions.csv").open(encoding="utf-8-sig", newline="")))
    qaqc_unconfirmed = sum(row.get("state", "") not in {"verified", "approved", "APPROVED"} for row in qaqc_rows)
    tnav_verified = sum("verified" in row.get("status", "").lower() and "candidate" not in row.get("status", "").lower() for row in tnav_rows)
    audit_rows = []
    for key in [
        "branches_with_owner_kb", "branches_with_activity", "branches_with_missing_policy",
        "branches_with_conflict_policy", "branches_with_evidence", "branches_with_fallback",
        "rules_with_formal_guard", "rules_with_human_gate",
    ]:
        denominator_before = before["rules"] if key.startswith("rules_") else before["branches"]
        denominator_after = after["rules"] if key.startswith("rules_") else after["branches"]
        audit_rows.append({
            "criterion": key, "before": before[key], "before_total": denominator_before,
            "after": after[key], "after_total": denominator_after,
            "status_after": "PASS" if after[key] == denominator_after else "GAP",
        })
    audit_rows.extend([
        {"criterion": "decision_csv_covers_all_rules", "before": len(v4_rows), "before_total": before["rules"], "after": len(consolidated), "after_total": after["rules"], "status_after": "PASS" if len(consolidated) == after["rules"] else "GAP"},
        {"criterion": "guard_beliefs_have_schema", "before": "no v4 schema", "before_total": "", "after": len(guard_codes) - len(missing_schema), "after_total": len(guard_codes), "status_after": "PASS" if not missing_schema else "GAP"},
        {"criterion": "guards_parse_in_reference_runtime", "before": "OR dialect mismatch", "before_total": "", "after": len(consolidated) - len(unparseable), "after_total": len(consolidated), "status_after": "PASS" if not unparseable else "GAP"},
        {"criterion": "process_stages_have_domain_owner", "before": 0, "before_total": 18, "after": len(stage_owner), "after_total": 18, "status_after": "PASS" if len(stage_owner) == 18 else "GAP"},
        {"criterion": "verified_tnavigator_callables", "before": tnav_verified, "before_total": len(tnav_rows), "after": tnav_verified, "after_total": len(tnav_rows), "status_after": "BLOCKS_PRODUCTION"},
        {"criterion": "approved_qaqc_rules", "before": len(qaqc_rows) - qaqc_unconfirmed, "before_total": len(qaqc_rows), "after": len(qaqc_rows) - qaqc_unconfirmed, "after_total": len(qaqc_rows), "status_after": "BLOCKS_PRODUCTION"},
    ])
    write_csv(AGENT_DIR / "autonomy_audit.csv", audit_rows, ["criterion", "before", "before_total", "after", "after_total", "status_after"])

    manifest = {
        "name": "NeurosymbolicAgentKB extension", "version": "4.1.0", "generated": date.today().isoformat(),
        "agent_profiles": len(agent_rows), "agent_groups": len(AGENT_GROUPS), "runtime_modules": len(RUNTIME_MODULES),
        "new_branch_points": len(BRANCHES), "new_rules": len(extension_rule_rows),
        "combined_branch_points": after["branches"], "combined_rules": after["rules"],
        "belief_schema_entries": len(belief_rows_out), "handoff_contracts": len(handoff_rows),
        "base_metrics": before, "after_metrics": after, "missing_belief_schemas": missing_schema,
        "unparseable_rules": unparseable, "qaqc_unconfirmed": qaqc_unconfirmed,
        "tnavigator_verified": tnav_verified, "tnavigator_candidates": len(tnav_rows),
        "production_autonomy_status": "BLOCKED_PENDING_RULE_APPROVAL_AND_TOOL_VERIFICATION",
        "sha256": {
            combined_bdi_path.name: hashlib.sha256(combined_bdi_path.read_bytes()).hexdigest(),
            combined_main_path.name: hashlib.sha256(combined_main_path.read_bytes()).hexdigest(),
        },
    }
    (AGENT_DIR / "manifest_v4_1.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    groups_md = []
    for group_id, label in AGENT_GROUPS:
        names = [row["agent"] for row in agent_rows if row["group"] == group_id]
        groups_md.append(f"- **{label}:** " + "; ".join(str(name) for name in names) + ".")
    audit_md = []
    for row in audit_rows:
        audit_md.append(f"| {row['criterion']} | {row['before']}/{row['before_total']} | {row['after']}/{row['after_total']} | {row['status_after']} |")
    report = f"""# Разделение нейросимвольных BDI-агентов и аудит автономности v4.1

Дата: {date.today().isoformat()}

## Вывод

Рекомендуется **один общий `TypicalAgentRuntime` и {len(agent_rows)} версионируемых доменных профиля**, а не {len(agent_rows)} разных программных реализаций. Профиль меняет онтологический срез, БЗ, права, capabilities, владельца объектов и критерии QA/QC; BDI-цикл, `CoverageReport`, `PlanIR`, журнал и политика reconsideration остаются общими.

База знаний после расширения **структурно достаточна для детерминированного выбора ветви и sandbox/shadow-работы**, но **не готова к полностью автономному production-моделированию**. Блокеры: {qaqc_unconfirmed} из {len(qaqc_rows)} QA/QC-правил не имеют статуса APPROVED/verified; {tnav_verified} из {len(tnav_rows)} кандидатов tNavigator проверены на установленной версии; проектные пороги и полномочия ещё не утверждены. Эти ограничения закодированы как hard gates, а не скрыты.

## Разделение

{chr(10).join(groups_md)}

Метакритик намеренно не является доменным BDI-агентом: это независимый детерминированный конвейер `SHACL → process → physics → cross-model → statistics → GateDecision`. `AG_QA_REMEDIATION` только устраняет и маршрутизирует findings и не может отменить fatal finding.

## Общий цикл агента

`GoalSpec → Context/Beliefs → CoverageReport → SYMBOLIC | HYBRID | GENERATIVE → PlanIR → formal validation → Intention → capability execution → metacritic → commit/reconsider → memory/candidate knowledge`.

- `SYMBOLIC`: утверждённый PlanSpec и достаточное покрытие.
- `HYBRID`: онтологический каркас фиксирован; LLM синтезирует только явно найденный пробел.
- `GENERATIVE`: LLM предлагает несколько PlanDraft, но исполнение только в sandbox и после human gate.

## Результаты gap-analysis

| Критерий | До | После | Статус |
|---|---:|---:|---|
{chr(10).join(audit_md)}

Исправлено: единый CSV теперь покрывает все {after['rules']} правил; все {after['branches']} развилки имеют owner-KB, activity, missing/conflict policy, evidence и fallback; строковые условия новых v4-правил дополнены формальными `ConditionGroup/AtomicCondition`; добавлена типизированная схема beliefs; 18 стадий получили доменного владельца; четыре ошибочных идентификатора унаследованных KB исправлены в генераторе v4.

## Новые правила из литературы и архитектуры

Добавлены {len(extension_rule_rows)} правила в {len(BRANCHES)} развилках: режим покрытия, право исполнения, handoff, продвижение знания, тип ветви ансамбля, reconsideration, перенос аналогов, выбор фациального алгоритма, depth conversion, fault scenarios, исторические ГИС, saturation model, ГДИС, pressure datum, geomechanical coupling, trend/stationarity, агрегация uncertainty, reprocessing vintage и безопасный software call.

Основные локальные свидетельства: Walker/Selley/Барабошкин по фациям и седиментологии; Glover и внутренние руководства по петрофизике; Bourdet/Heinemann/Schlumberger по ГДИС; Ковалевский и курс по variogram; материалы по uncertainty/GCoS; руководство tNavigator по geomechanics; рабочие QA/QC-реестры. Каждый новый rule содержит `supportedBy`, `knowledgeStatus` и `executionEligibility`.

## Что нужно для production-автономности

1. Утвердить проектный policy (`project_symbolic_threshold`, `project_hybrid_threshold`, риск-классы, полномочия и критерии materiality).
2. Верифицировать минимальный набор реальных функций/адаптеров tNavigator на установленной версии: signature, license, read/write scope, dry-run, postconditions и rollback.
3. Перевести критические QA/QC-правила из «Статус не подтверждён» в APPROVED после владельца, тестов и эталонных наборов.
4. Прогнать каждый профиль на golden/negative/boundary/mutation cases и shadow-проекте.
5. После этого повышать права точечно: A1 → A2 → A3, без глобального переключателя «полная автономия».
"""
    (AGENT_DIR / "BDI_AGENT_DIVISION_AND_AUTONOMY_AUDIT.md").write_text(report, encoding="utf-8", newline="\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
