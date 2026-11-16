from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import openpyxl


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODULE_DIR = HERE / "modules"
CORPUS_DIR = HERE / "corpus_analysis"
V3_DIR = ROOT / "Онтологии процесса 3"
TASK3 = HERE.parent

BASE = "https://example.org/geomodel/evolution/v4#"
ONT = "https://example.org/geomodel/evolution/v4/"
BDI_BASE = "https://example.org/geomodel/evolution/v4/bdi#"
V3_BASE = "https://example.org/tnav/geomodel/v3#"
V3_ONT = "https://example.org/tnav/geomodel/v3/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
XSD = "http://www.w3.org/2001/XMLSchema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DCT = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"
GEO = "http://www.opengis.net/ont/geosparql#"
SOSA = "http://www.w3.org/ns/sosa/"
QUDT = "http://qudt.org/schema/qudt/"
BDI_BASE = "https://example.org/geomodel/evolution/v4/bdi#"
OLD_BDI_BASE = "https://example.org/tnav/geomodel/bdi/v1#"
OLD_BDI_ONT = "https://example.org/tnav/geomodel/bdi/v1/"


MODULES = {
    "00_core": "Ядро эволюционной онтологии",
    "01_governance": "Цели, управление и жизненный цикл решения",
    "02_data_qc": "Наполнение данными, нормировка и первичный контроль",
    "03_stratigraphy": "Стратиграфия и межскважинная корреляция",
    "04_structural": "Сейсмическая интерпретация и структурная модель",
    "05_facies": "Седиментология, литология и фациальная модель",
    "06_petrophysics": "Петрофизика, керн и ГИС",
    "07_geostatistics": "Геостатистика и моделирование свойств",
    "08_grid_volumetrics": "Сетки, апскейлинг, объёмы и запасы",
    "09_uncertainty": "Неопределённости, аналоги и ансамбли",
    "10_dynamic_handoff": "ГДМ, 4D-наблюдения и адаптация",
    "11_tnavigator": "Функции tNavigator и точки автоматизации",
    "12_lifecycle_evolution": "60-летняя эволюция данных, технологий и моделей",
    "13_regional_play": "Региональная модель, бассейн и petroleum play",
    "14_pressure_welltest": "Давление, ГДИС, приток и межскважинные поля",
    "15_geomechanics": "Геомеханика и естественная трещиноватость",
    "16_data_ontology": "Онтология данных и параметров всех уровней",
    "17_qaqc_rules": "Правила QA/QC, валидация и эскалация",
    "18_software_bridge": "Слой связей с профильным ПО",
    "19_sources_alignments": "Источники, стандарты и семантические соответствия",
    "20_agent_knowledge": "Базы знаний BDI-агентов и правила решений",
}

IMPORTS = {
    "00_core": [],
    "01_governance": ["00_core"],
    "02_data_qc": ["00_core", "01_governance"],
    "03_stratigraphy": ["00_core", "02_data_qc"],
    "04_structural": ["00_core", "02_data_qc", "03_stratigraphy"],
    "05_facies": ["00_core", "03_stratigraphy", "04_structural"],
    "06_petrophysics": ["00_core", "02_data_qc", "05_facies"],
    "07_geostatistics": ["00_core", "05_facies", "06_petrophysics"],
    "08_grid_volumetrics": ["00_core", "04_structural", "07_geostatistics"],
    "09_uncertainty": ["00_core", "01_governance", "08_grid_volumetrics"],
    "10_dynamic_handoff": ["00_core", "06_petrophysics", "08_grid_volumetrics", "09_uncertainty"],
    "11_tnavigator": ["00_core", "02_data_qc", "04_structural", "05_facies", "06_petrophysics", "07_geostatistics", "08_grid_volumetrics", "09_uncertainty", "10_dynamic_handoff"],
    "12_lifecycle_evolution": ["00_core", "01_governance", "02_data_qc", "09_uncertainty", "10_dynamic_handoff"],
    "13_regional_play": ["00_core", "01_governance", "03_stratigraphy", "05_facies", "09_uncertainty"],
    "14_pressure_welltest": ["00_core", "02_data_qc", "06_petrophysics", "07_geostatistics", "10_dynamic_handoff"],
    "15_geomechanics": ["00_core", "04_structural", "06_petrophysics", "07_geostatistics", "10_dynamic_handoff"],
    "16_data_ontology": ["00_core"] + list(MODULES)[1:16],
    "17_qaqc_rules": ["00_core", "02_data_qc", "16_data_ontology"],
    "18_software_bridge": ["00_core", "11_tnavigator", "16_data_ontology", "17_qaqc_rules"],
    "19_sources_alignments": list(MODULES)[:19],
    "20_agent_knowledge": list(MODULES)[:20],
}


def iri(value: str) -> str:
    if value.startswith(("http://", "https://", "urn:")):
        return f"<{value}>"
    return f"<{BASE}{value}>"


def esc(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")


def literal(value: object, lang: str | None = None, datatype: str | None = None) -> str:
    if isinstance(value, bool):
        value = str(value).lower()
    result = f'"{esc(value)}"'
    if lang:
        result += f"@{lang}"
    elif datatype:
        result += f"^^<{datatype}>"
    return result


graphs: dict[str, set[str]] = {name: set() for name in MODULES}


def add(module: str, subject: str, predicate: str, obj: str) -> None:
    graphs[module].add(f"{iri(subject)} {iri(predicate)} {obj} .")


def add_i(module: str, subject: str, predicate: str, obj: str) -> None:
    add(module, subject, predicate, iri(obj))


def add_l(module: str, subject: str, predicate: str, value: object, lang: str | None = None, datatype: str | None = None) -> None:
    add(module, subject, predicate, literal(value, lang, datatype))


def labels(module: str, subject: str, ru: str, en: str | None = None) -> None:
    add_l(module, subject, RDFS + "label", ru, lang="ru")
    if en:
        add_l(module, subject, RDFS + "label", en, lang="en")


def class_(name: str, ru: str, en: str, parent: str | None = None) -> None:
    add_i("00_core", name, RDF + "type", OWL + "Class")
    labels("00_core", name, ru, en)
    if parent:
        add_i("00_core", name, RDFS + "subClassOf", parent)


def property_(name: str, ru: str, en: str, datatype: bool = False) -> None:
    add_i("00_core", name, RDF + "type", OWL + ("DatatypeProperty" if datatype else "ObjectProperty"))
    labels("00_core", name, ru, en)


def individual(module: str, name: str, type_: str, ru: str, en: str | None = None, description: str | None = None) -> None:
    add_i(module, name, RDF + "type", type_)
    labels(module, name, ru, en)
    if description:
        add_l(module, name, DCT + "description", description, lang="ru")


def safe(value: str, max_len: int = 90) -> str:
    normalized = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").upper()
    if not normalized:
        normalized = "NODE"
    if len(normalized) > max_len:
        digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12].upper()
        normalized = normalized[: max_len - 13] + "_" + digest
    return normalized


def parse_rows(text: str, level: str, domain: str, stage: str, equipment: str = "project dependent") -> list[dict[str, str]]:
    result = []
    for raw in text.strip().splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) != 6:
            raise ValueError(f"Parameter row must have 6 columns: {raw}")
        code, name, data_type, unit, typical_range, typical_error = parts
        result.append({
            "code": code, "name": name, "data_type": data_type, "unit": unit,
            "typical_range": typical_range, "typical_error": typical_error,
            "level": level, "domain": domain, "stage": stage, "equipment": equipment,
        })
    return result


# ---------------------------------------------------------------------------
# Prior-version continuity
# ---------------------------------------------------------------------------

def import_v3() -> None:
    module_map = {name: name for name in list(MODULES)[:12]}
    module_map["12_sources_alignments"] = "19_sources_alignments"
    for old_module, new_module in module_map.items():
        path = V3_DIR / "modules" / f"{old_module}.rdf"
        if not path.is_file():
            raise FileNotFoundError(path)
        old_ontology_subject = f"<{V3_ONT}{old_module}>"
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith(old_ontology_subject + " "):
                continue
            mapped = line.replace(V3_ONT + "12_sources_alignments", ONT + "19_sources_alignments")
            mapped = mapped.replace(V3_ONT, ONT).replace(V3_BASE, BASE)
            graphs[new_module].add(mapped)
    add_l("01_governance", "PROCESS_GEO_MODEL_V3", OWL + "deprecated", True, datatype=XSD + "boolean")


import_v3()


# ---------------------------------------------------------------------------
# Vocabulary extensions
# ---------------------------------------------------------------------------

for args in [
    ("IntegratedGeomodelingProcess", "Процесс комплексного геологического моделирования", "Integrated geological modeling process", PROV + "Activity"),
    ("LifecycleStage", "Стадия жизненного цикла месторождения", "Field lifecycle stage", PROV + "Entity"),
    ("TechnologyEra", "Поколение технологии", "Technology era", PROV + "Entity"),
    ("ProcessDomain", "Домен процесса", "Process domain", PROV + "Entity"),
    ("ProcessSubstage", "Подэтап процесса", "Process substage", "ProcessStage"),
    ("AtomicModelingTask", "Атомарная задача моделирования", "Atomic modeling task", "Activity"),
    ("TransitionCondition", "Условие перехода", "Transition condition", PROV + "Entity"),
    ("IterationTrigger", "Триггер итерации", "Iteration trigger", "TransitionCondition"),
    ("DataContract", "Контракт передачи данных", "Data handoff contract", PROV + "Entity"),
    ("SpatialLevel", "Пространственный уровень", "Spatial level", SKOS + "Concept"),
    ("Region", "Регион", "Region", GEO + "Feature"),
    ("Basin", "Осадочный бассейн", "Sedimentary basin", "Region"),
    ("PetroleumSystem", "Нефтегазовая система", "Petroleum system", GEO + "Feature"),
    ("Play", "Нефтегазоносный комплекс / play", "Petroleum play", GEO + "Feature"),
    ("Field", "Месторождение", "Field", GEO + "Feature"),
    ("Area", "Площадь / участок", "Area", GEO + "Feature"),
    ("Reservoir", "Пласт / резервуар", "Reservoir", GEO + "Feature"),
    ("Deposit", "Залежь / объект разработки", "Deposit", GEO + "Feature"),
    ("Zone", "Зона", "Zone", GEO + "Feature"),
    ("Layer", "Слой", "Layer", GEO + "Feature"),
    ("Well", "Скважина", "Well", GEO + "Feature"),
    ("Wellbore", "Ствол скважины", "Wellbore", GEO + "Feature"),
    ("Completion", "Заканчивание", "Completion", PROV + "Entity"),
    ("PerforationInterval", "Интервал перфорации", "Perforation interval", GEO + "Feature"),
    ("GridCell", "Ячейка сетки", "Grid cell", GEO + "Feature"),
    ("ParameterDefinition", "Определение параметра", "Parameter definition", "Parameter"),
    ("ParameterQualityProfile", "Профиль качества параметра", "Parameter quality profile", PROV + "Entity"),
    ("TechnologyMetadataProfile", "Профиль временных и технологических метаданных", "Technology metadata profile", PROV + "Entity"),
    ("UncertaintyProfile", "Профиль неопределённости параметра", "Uncertainty profile", "Uncertainty"),
    ("TemporalValidity", "Интервал применимости", "Temporal validity", PROV + "Entity"),
    ("DataVintage", "Винтаж данных", "Data vintage", PROV + "Entity"),
    ("LegacyDataIssue", "Проблема исторических данных", "Legacy data issue", "FailureMode"),
    ("QAQCRule", "Правило QA/QC", "QA/QC rule", PROV + "Plan"),
    ("CrossDisciplineRule", "Междисциплинарное правило QA/QC", "Cross-discipline QA/QC rule", "QAQCRule"),
    ("HistoricalQAQCRule", "Историческое правило QA/QC", "Historical QA/QC rule", "QAQCRule"),
    ("QualityCriterionVersion", "Версия критерия качества", "Quality criterion version", PROV + "Entity"),
    ("EscalationRoute", "Маршрут эскалации", "Escalation route", PROV + "Plan"),
    ("AbstractSoftwareOperation", "Абстрактная операция ПО", "Abstract software operation", PROV + "Plan"),
    ("SoftwareProduct", "Профильное ПО", "Software product", PROV + "SoftwareAgent"),
    ("SoftwareVersion", "Версия ПО", "Software version", PROV + "SoftwareAgent"),
    ("SoftwareBinding", "Привязка операции к ПО", "Software binding", PROV + "Entity"),
    ("TNavigatorCallableCandidate", "Функция tNavigator из руководства", "tNavigator callable from manual", "TNavigatorFunction"),
    ("DeprecationPolicy", "Политика устаревания", "Deprecation policy", PROV + "Plan"),
    ("SourceArtifact", "Локальный источник знаний", "Local knowledge source", "Source"),
    ("ExternalKnowledgeResource", "Внешний ресурс знаний", "External knowledge resource", "Source"),
    ("ContradictionCheck", "Проверка непротиворечивости", "Contradiction check", "QualityControl"),
    ("AssumptionRegisterEntry", "Запись реестра допущений", "Assumption register entry", "Assumption"),
    ("UncertaintyRegisterEntry", "Запись реестра неопределённостей", "Uncertainty register entry", "Uncertainty"),
]:
    class_(*args)

for args in [
    ("hasLifecycleStage", "имеет стадию жизненного цикла", "has lifecycle stage"),
    ("appliesDuring", "применяется на стадии", "applies during"),
    ("hasTechnologyEra", "имеет поколение технологии", "has technology era"),
    ("validDuring", "действительно в интервале", "valid during"),
    ("refinesStage", "детализирует этап", "refines stage"),
    ("hasSubstage", "содержит подэтап", "has substage"),
    ("hasTransitionCondition", "имеет условие перехода", "has transition condition"),
    ("hasIterationTrigger", "имеет триггер итерации", "has iteration trigger"),
    ("passesParameter", "передаёт параметр", "passes parameter"),
    ("hasDataContract", "имеет контракт данных", "has data contract"),
    ("appliesToLevel", "применяется к уровню", "applies to level"),
    ("hasQualityProfile", "имеет профиль качества", "has quality profile"),
    ("hasTechnologyMetadataProfile", "имеет технологический профиль", "has technology metadata profile"),
    ("hasUncertaintyProfile", "имеет профиль неопределённости", "has uncertainty profile"),
    ("measuredByEquipment", "измеряется оборудованием", "measured by equipment"),
    ("normalizesTo", "нормируется к", "normalizes to"),
    ("supersedes", "заменяет", "supersedes"),
    ("hasRule", "имеет правило", "has rule"),
    ("targetsNode", "адресует онтологический узел", "targets ontology node"),
    ("escalatesTo", "эскалирует роли", "escalates to"),
    ("hasEscalationRoute", "имеет маршрут эскалации", "has escalation route"),
    ("implementsOperation", "реализует операцию", "implements operation"),
    ("targetsSoftware", "направляется в ПО", "targets software"),
    ("targetsVersion", "направляется в версию", "targets version"),
    ("hasAlternativeBinding", "имеет альтернативную привязку", "has alternative binding"),
    ("detectedInManual", "найдена в руководстве", "detected in manual"),
    ("supportsProcessDomain", "поддерживает домен процесса", "supports process domain"),
    ("exactDuplicateOf", "точный дубликат", "exact duplicate of"),
    ("hasAssumptionEntry", "имеет запись допущения", "has assumption entry"),
    ("hasUncertaintyEntry", "имеет запись неопределённости", "has uncertainty entry"),
]:
    property_(*args)

for args in [
    ("lifecycleCode", "код стадии жизненного цикла", "lifecycle code"),
    ("startYear", "начальный год", "start year"),
    ("endYear", "конечный год", "end year"),
    ("technologyGeneration", "поколение технологии", "technology generation"),
    ("transitionExpression", "формула условия перехода", "transition expression"),
    ("iterationExpression", "формула возврата", "iteration expression"),
    ("dataType", "тип данных", "data type"),
    ("unitSymbolV4", "единица измерения", "unit symbol"),
    ("typicalRange", "типовой диапазон", "typical range"),
    ("typicalUncertainty", "типовая погрешность", "typical uncertainty"),
    ("uncertaintyModel", "модель неопределённости", "uncertainty model"),
    ("acquisitionYearRequired", "требуется год получения", "acquisition year required"),
    ("equipmentMetadataRequired", "требуются сведения об оборудовании", "equipment metadata required"),
    ("technologyGenerationRequired", "требуется поколение технологии", "technology generation required"),
    ("normalizationRequirement", "требование нормировки", "normalization requirement"),
    ("qualityRuleText", "правило QA/QC в читаемом формате", "human-readable QA/QC rule"),
    ("conditionText", "условие", "condition"),
    ("actionText", "действие", "action"),
    ("criterionVersion", "версия критерия", "criterion version"),
    ("severity", "серьёзность", "severity"),
    ("softwareName", "название ПО", "software name"),
    ("softwareVersionText", "версия ПО", "software version"),
    ("implementationLocator", "метод или точка вызова", "implementation locator"),
    ("bindingStatus", "статус привязки", "binding status"),
    ("deprecationStatus", "статус устаревания", "deprecation status"),
    ("manualPage", "страница руководства", "manual page"),
    ("sourcePath", "путь к источнику", "source path"),
    ("sourceSha256", "SHA-256 источника", "source SHA-256"),
    ("sourceTheme", "тема источника", "source theme"),
    ("sourceModified", "дата изменения источника", "source modified"),
    ("evidenceStatus", "статус свидетельства", "evidence status"),
]:
    property_(*args, datatype=True)


# ---------------------------------------------------------------------------
# Lifecycle, technology eras and spatial hierarchy
# ---------------------------------------------------------------------------

individual("01_governance", "PROCESS_GEO_MODEL_V4", "IntegratedGeomodelingProcess", "Эволюционный процесс комплексного 2D/3D геологического моделирования", "Evolutionary integrated 2D/3D geological modeling", "Непрерывный процесс от чистого поля до поздней стадии и архивирования знаний; сохраняет исходные наблюдения, версии интерпретаций и ансамбль допустимых моделей.")
add_l("01_governance", "PROCESS_GEO_MODEL_V4", "version", "4.0.0")
add_i("01_governance", "PROCESS_GEO_MODEL_V4", PROV + "wasRevisionOf", "PROCESS_GEO_MODEL_V3")

LIFECYCLE = [
    ("LC_01", "1", "Стадия 1: региональное изучение, поиск и разведка", "Чистое поле, бассейн, play, проспект, открытие и первичная оценка."),
    ("LC_02", "2", "Стадия 2: оценка и проектирование разработки", "Оценочные скважины, концепция залежи, план разработки и базовый ансамбль."),
    ("LC_03", "3", "Стадия 3: ввод, рост и плато добычи", "Уточнение связности, 4D-наблюдения, адаптация и оптимизация системы разработки."),
    ("LC_04", "4", "Стадия 4: зрелая и поздняя разработка", "Высокая обводнённость, остаточные запасы, уплотнение сетки, ГТМ, EOR и вывод фонда."),
    ("LC_AFTERCARE", "A", "Послеэксплуатационное сопровождение и архив знаний", "Консервация, ликвидация, мониторинг, сохранение воспроизводимого цифрового наследия."),
]
for sid, code, label, desc in LIFECYCLE:
    individual("12_lifecycle_evolution", sid, "LifecycleStage", label, description=desc)
    add_l("12_lifecycle_evolution", sid, "lifecycleCode", code)
    add_i("01_governance", "PROCESS_GEO_MODEL_V4", "hasLifecycleStage", sid)

TECH_ERAS = [
    ("ERA_1960_1975", 1960, 1975, "Аналоговая регистрация и бумажные основы", "аналоговые ГИС, фотобумага, ручные карты, ранние 2D-съёмки"),
    ("ERA_1976_1990", 1976, 1990, "Переход к цифровой регистрации", "первые цифровые ГИС и сейсмика, ведомственные форматы, оцифровка"),
    ("ERA_1991_2004", 1991, 2004, "Рабочие станции и 3D-сейсмика", "интерактивная интерпретация, corner-point grid, геостатистика"),
    ("ERA_2005_2014", 2005, 2014, "Интегрированное статико-динамическое моделирование", "единые проекты, RESQML/WITSML, ансамбли и history matching"),
    ("ERA_2015_2024", 2015, 2024, "4D, облачные данные и промышленная автоматизация", "4D seismic, OSDU, ML-помощники, потоковые данные"),
    ("ERA_2025_PLUS", 2025, 2100, "Семантическое и агентное моделирование", "эволюционные онтологии, BDI-агенты, physics-informed ML, непрерывная ассимиляция"),
]
for eid, start, end, label, desc in TECH_ERAS:
    individual("12_lifecycle_evolution", eid, "TechnologyEra", label, description=desc)
    add_l("12_lifecycle_evolution", eid, "startYear", start, datatype=XSD + "integer")
    add_l("12_lifecycle_evolution", eid, "endYear", end, datatype=XSD + "integer")
    add_l("12_lifecycle_evolution", eid, "technologyGeneration", label, lang="ru")
    add_i("12_lifecycle_evolution", "PROCESS_GEO_MODEL_V4", "hasTechnologyEra", eid)

SPATIAL_LEVELS = [
    ("LEVEL_REGION", "Регион", "Region"), ("LEVEL_BASIN", "Бассейн", "Basin"),
    ("LEVEL_PLAY", "Petroleum play", "Play"), ("LEVEL_FIELD", "Месторождение / площадь", "Field"),
    ("LEVEL_RESERVOIR", "Пласт / резервуар", "Reservoir"), ("LEVEL_DEPOSIT", "Залежь / объект", "Deposit"),
    ("LEVEL_ZONE", "Зона / слой", "Zone"), ("LEVEL_WELL", "Скважина / ствол", "Well"),
    ("LEVEL_COMPLETION", "Заканчивание / перфорация", "Completion"), ("LEVEL_GRID", "Сетка", "Grid"),
    ("LEVEL_CELL", "Ячейка сетки", "GridCell"), ("LEVEL_TIME", "Временной срез / винтаж", "DataVintage"),
]
for lid, label, cls in SPATIAL_LEVELS:
    individual("16_data_ontology", lid, "SpatialLevel", label, cls)
    add_i("16_data_ontology", lid, "representsFeature", cls)

LEVEL_CHAIN = [row[0] for row in SPATIAL_LEVELS[:11]]
for parent, child in zip(LEVEL_CHAIN, LEVEL_CHAIN[1:]):
    add_i("16_data_ontology", parent, SKOS + "narrower", child)
    add_i("16_data_ontology", child, SKOS + "broader", parent)


# ---------------------------------------------------------------------------
# Fundamental process: stages, substages, atomic tasks and handoffs
# ---------------------------------------------------------------------------

STAGES = [
    ("S01", "01_governance", "Цели, границы и управление моделью", "STAGE_01_SCOPE", "LC_01,LC_02,LC_03,LC_04,LC_AFTERCARE",
     "Формулирование решений и fit-for-purpose|Паспорт геологического объекта|Границы 2D/3D-модели и масштабы|RACI и полномочия профильных агентов|Критерии приёмки и доказательства|Реестр допущений|Реестр неопределённостей|Стратегия версий и воспроизводимости|План внешней экспертизы|План эволюционного обновления"),
    ("S02", "02_data_qc", "Наполнение проекта, каталогизация и нормировка", "STAGE_02_DATA", "LC_01,LC_02,LC_03,LC_04",
     "Инвентаризация всех источников|Идентификация мастер-объектов|Дедупликация и разрешение идентификаторов|Проверка CRS и datum|Приведение единиц измерения|Синхронизация временных шкал|Оцифровка аналоговых материалов|Нормировка старых форматов|Версионирование сырых и обработанных данных|Оценка полноты и информационных пробелов|Первичный автоматический QA/QC|Формирование data-ready пакета"),
    ("S03", "13_regional_play", "Региональная модель, бассейновый анализ и petroleum play", "STAGE_01_SCOPE", "LC_01,LC_02,LC_03,LC_04",
     "Тектоническое районирование|Региональная стратиграфическая схема|Палеогеографическая реконструкция|История погружения и термальная эволюция|Материнские породы и зрелость|Генерация, миграция и аккумуляция|Коллектор, покрышка и ловушка|Элементы petroleum system|Сегментация play|Common Risk Segment карты|Оценка GCoS|Выбор региональных аналогов"),
    ("S04", "03_stratigraphy", "Стратиграфия, расчленение и корреляция", "STAGE_03_STRAT", "LC_01,LC_02,LC_03,LC_04",
     "Таксономия стратиграфических единиц|Хроностратиграфическая привязка|Выбор опорных маркеров|Корреляция по каротажным паттернам|Керновая и биостратиграфическая калибровка|Секвенс-стратиграфическая интерпретация|Явное моделирование перерывов и эрозии|Альтернативные схемы корреляции|Зональность и layering framework|QC межскважинных панелей|Обновление корреляции по новым скважинам"),
    ("S05", "05_facies", "Седиментология и концептуальная модель", "STAGE_05_FACIES", "LC_01,LC_02,LC_03,LC_04",
     "Описание керновых текстур и структур|Выделение литофаций|Фациальные ассоциации|Диагностика обстановки осадконакопления|Иерархия depositional elements|Палеотранспорт и тренды|Анализ архитектуры геотел|Сейсмофациальные свидетельства|Концептуальные сценарии|Масштабирование по аналогам|2D палеогеографические карты|QC закона Вальтера и архитектуры"),
    ("S06", "04_structural", "Обработка и интерпретация сейсмики", "STAGE_04_STRUCT", "LC_01,LC_02,LC_03,LC_04",
     "Аудит геометрии и навигации съёмки|Амплитудно-фазовая нормировка винтажей|Подавление шума и кратных волн|Скоростной анализ и томография|PSTM/PSDM/RTM/FWI imaging|Сейсмоскважинная привязка|Интерпретация горизонтов|Интерпретация разломов|Атрибутный анализ|Инверсия и rock physics|4D cross-equalization|Оценка сейсмической разрешающей способности"),
    ("S07", "04_structural", "Структурный каркас и глубинная модель", "STAGE_04_STRUCT", "LC_01,LC_02,LC_03,LC_04",
     "Топология разломной сети|Fault framework и пересечения|Каркас горизонтов|Скоростная модель|Преобразование время-глубина|Калибровка по checkshot/VSP|Структурные поверхности и карты|Сегментация блоков|Fault juxtaposition и seal|Структурные сценарии|Проверка well mistie|Экспорт структурного каркаса"),
    ("S08", "06_petrophysics", "ГИС, керн и петрофизическая интерпретация", "STAGE_06_PETRO", "LC_01,LC_02,LC_03,LC_04",
     "Инвентаризация кривых ГИС|Depth matching и environmental corrections|Нормализация кривых между скважинами|Оценка Vsh и минералогии|Расчёт общей и эффективной пористости|Керн-ГИС калибровка|Оценка проницаемости|Расчёт водонасыщенности|Saturation-height модели|Cut-off и net-to-gross|Электрофации и ML-классификация|Петрофизические сценарии"),
    ("S09", "06_petrophysics", "Литология, типы пород и распространение коллектора", "STAGE_06_PETRO", "LC_01,LC_02,LC_03,LC_04",
     "Литологическая типизация|Петрофизические rock types|Hydraulic flow units|Выделение коллектора|Вероятность коллектора|Тренды net-to-gross|Связанность порового пространства|Границы rock-type доменов|Калибровка по ГДИС|Сценарии распространения коллектора|QC баланса объёмов и ФЕС"),
    ("S10", "05_facies", "2D/3D фациальное моделирование", "STAGE_05_FACIES", "LC_01,LC_02,LC_03,LC_04",
     "Подготовка фациальных данных|Модели вертикальных пропорций|Карты вероятностей и тренды|Variogram-based SIS|Truncated Gaussian simulation|Plurigaussian simulation|Object-based modeling|Multiple-point statistics|Гибридное ML-геостатистическое моделирование|Условие на скважины и сейсмику|Связность и геометрия геотел|Фациальный ансамбль и blind-well QC"),
    ("S11", "14_pressure_welltest", "Давления, ГДИС, приток и межскважинные поля", "STAGE_10_HANDOFF", "LC_01,LC_02,LC_03,LC_04",
     "QC манометрии и глубин приведения|Нормализация давлений к datum|Интерпретация КВД/КПД|Pressure transient analysis|Rate transient analysis|Модель притока IPR|Оценка skin и продуктивности|Диагностика границ и разломов|Интерференционные и pulse tests|Карты изобар и градиенты|4D поле давления|Согласование с PVT и материальным балансом"),
    ("S12", "10_dynamic_handoff", "Насыщение, PVT, SCAL и распределение флюидов", "STAGE_10_HANDOFF", "LC_01,LC_02,LC_03,LC_04",
     "QC проб пластовых флюидов|PVT-рекомбинация и EOS|Регионализация PVT|Флюидальные контакты и FWL|Капиллярное давление|Относительные проницаемости|Смачиваемость и гистерезис|Saturation-height functions|Инициализация насыщения|Историческое насыщение по PLT/RST|4D seismic saturation change|QC гидростатического равновесия"),
    ("S13", "15_geomechanics", "Геомеханика, напряжения и трещиноватость", "STAGE_04_STRUCT", "LC_01,LC_02,LC_03,LC_04",
     "1D mechanical earth model|Поровое давление и градиент разрыва|Модули Юнга и Пуассона|Прочность и критерии разрушения|Ориентация и величины напряжений|Калибровка по LOT/XLOT/DFIT|Стабильность ствола|Естественная трещиноватость|Discrete fracture network|Апскейлинг трещин|4D coupled geomechanics|Риск уплотнения и просадки"),
    ("S14", "07_geostatistics", "Геостатистика и распределение свойств", "STAGE_07_GEOSTAT", "LC_01,LC_02,LC_03,LC_04",
     "Support и blocking|Декластеризация|Univariate и multivariate EDA|Normal-score transforms|Тренды и stationarity domains|Экспериментальные вариограммы|Теоретические модели вариограмм|Kriging и cokriging|SGS и cosimulation|ML property modeling|Cross-validation и blind wells|Ансамбль свойств и обратное преобразование"),
    ("S15", "08_grid_volumetrics", "Сетка, апскейлинг, объёмы и запасы", "STAGE_08_GRID", "LC_01,LC_02,LC_03,LC_04",
     "Выбор типа и масштаба сетки|Pillar/corner-point/PEBI framework|Zonation и layering|Pinch-out и эрозионные контакты|Grid geometry QC|Upscaling пористости и NTG|Flow-based upscaling permeability|Fault transmissibility|Объёмный расчёт STOIIP/GIIP|PRMS-классификация ресурсов|Сценарии контактов и GRV|Simulation-ready export"),
    ("S16", "09_uncertainty", "Неопределённости, аналоги и ансамбли", "STAGE_09_UNCERT", "LC_01,LC_02,LC_03,LC_04",
     "Таксономия aleatory/epistemic неопределённостей|Реестр допущений|Выбор и калибровка аналогов|Концептуальные сценарии|Параметрические распределения|Корреляции и copula|DoE/Latin hypercube/Sobol|Monte Carlo и геологический ансамбль|Sensitivity и value of information|P10/P50/P90 и representative realizations|Независимая экспертиза|План снижения неопределённостей"),
    ("S17", "10_dynamic_handoff", "ГДМ, 4D-ассимиляция и адаптация", "STAGE_10_HANDOFF", "LC_02,LC_03,LC_04",
     "Преобразование статических свойств|Инициализация и material balance|Скважины и completions|История добычи и закачки|Observation error model|Flow diagnostics|Objective matching|Assisted history matching|Ensemble smoother/EnKF|Согласование 4D seismic|Posterior ensemble|Прогнозные сценарии и ограничения"),
    ("S18", "12_lifecycle_evolution", "Эволюционное обновление и поздний жизненный цикл", "STAGE_10_HANDOFF", "LC_01,LC_02,LC_03,LC_04,LC_AFTERCARE",
     "Приём нового винтажа данных|Impact analysis новой информации|Сравнение версий и причин изменений|Локальное обновление интерпретаций|Обновление ensemble weights|Пересмотр критериев качества|Миграция форматов и ПО|Переоценка остаточных запасов|Late-life redevelopment и EOR screening|Abandonment uncertainty|Архив исходных данных и моделей|Проверка воспроизводимости через десятилетия"),
]

STEP_KINDS = [
    ("01", "Собрать и квалифицировать исходные свидетельства", "deterministic evidence inventory"),
    ("02", "Нормировать единицы, координаты, время и версии", "deterministic normalization"),
    ("03", "Построить базовую интерпретацию", "expert deterministic interpretation"),
    ("04", "Построить альтернативы и количественную модель", "stochastic or ML-assisted modeling"),
    ("05", "Выполнить QA/QC и междисциплинарную сверку", "cross-domain validation"),
    ("06", "Зафиксировать решение, параметры и пакет передачи", "auditable handoff"),
]

stage_nodes: dict[str, str] = {}
activity_rows: list[dict[str, str]] = []
stage_last_activity: dict[str, str] = {}
stage_first_activity: dict[str, str] = {}
substage_domain: dict[str, str] = {}

for order, (code, module, label, legacy_stage, lifecycle_text, substage_text) in enumerate(STAGES, start=1):
    lifecycle = lifecycle_text.split(",")
    substages = substage_text.split("|")
    stage_id = f"EV_STAGE_{code}"
    stage_nodes[code] = stage_id
    individual(module, stage_id, "ProcessStage", label, description=f"Фундаментальный этап {order} из {len(STAGES)} эволюционного процесса.")
    add_l(module, stage_id, "order", order, datatype=XSD + "integer")
    add_i(module, stage_id, "refinesStage", legacy_stage)
    add_i(module, "PROCESS_GEO_MODEL_V4", "hasStage", stage_id)
    for lc in lifecycle:
        add_i(module, stage_id, "appliesDuring", lc)
    previous_activity = None
    for sub_index, sub_label in enumerate(substages, start=1):
        sub_id = f"SUB_{code}_{sub_index:02d}"
        substage_domain[sub_id] = code
        individual(module, sub_id, "ProcessSubstage", sub_label)
        add_i(module, stage_id, "hasSubstage", sub_id)
        input_id = f"INPUT_{code}_{sub_index:02d}"
        output_id = f"OUTPUT_{code}_{sub_index:02d}"
        contract_id = f"CONTRACT_{code}_{sub_index:02d}"
        transition_id = f"TRANSITION_{code}_{sub_index:02d}"
        method_id = f"METHOD_{code}_{sub_index:02d}"
        individual(module, input_id, "Dataset", f"Вход: {sub_label}")
        individual(module, output_id, "Artifact", f"Выход: {sub_label}")
        individual(module, contract_id, "DataContract", f"Контракт передачи: {sub_label}")
        individual(module, transition_id, "TransitionCondition", f"Условие завершения: {sub_label}")
        add_l(module, transition_id, "transitionExpression", "обязательные входы доступны AND критические QA/QC пройдены AND неопределённости и допущения зарегистрированы", lang="ru")
        add_l(module, transition_id, "iterationExpression", "при новом винтаже, провале критерия или междисциплинарном противоречии вернуть процесс к ближайшему причинному подэтапу", lang="ru")
        individual(module, method_id, "Method", f"Метод выполнения: {sub_label}", description="Семейство метода выбирается по доступным данным, масштабу решения и типу неопределённости.")
        add_i(module, sub_id, "hasInput", input_id)
        add_i(module, sub_id, "hasOutput", output_id)
        add_i(module, sub_id, "hasDataContract", contract_id)
        add_i(module, sub_id, "hasTransitionCondition", transition_id)
        for step_code, step_label, method_family in STEP_KINDS:
            act_id = f"ACT_{code}_{sub_index:02d}_{step_code}"
            full_label = f"{sub_label}: {step_label.lower()}"
            individual(module, act_id, "AtomicModelingTask", full_label)
            add_i(module, sub_id, "hasActivity", act_id)
            add_i(module, act_id, "belongsToStage", stage_id)
            add_i(module, act_id, "hasInput", input_id)
            add_i(module, act_id, "hasOutput", output_id)
            add_i(module, act_id, "usesMethod", method_id)
            add_i(module, act_id, "hasTransitionCondition", transition_id)
            add_l(module, act_id, "executionMode", method_family)
            for lc in lifecycle:
                add_i(module, act_id, "appliesDuring", lc)
            if previous_activity:
                add_i(module, previous_activity, "precedes", act_id)
            else:
                stage_first_activity[code] = act_id
            previous_activity = act_id
            stage_last_activity[code] = act_id
            activity_rows.append({
                "id": act_id, "stage": stage_id, "stage_label": label,
                "substage": sub_id, "substage_label": sub_label,
                "task": step_label, "method": method_id,
                "input": input_id, "output": output_id, "transition": transition_id,
            })

stage_codes = [row[0] for row in STAGES]
stage_modules = {row[0]: row[1] for row in STAGES}
for left, right in zip(stage_codes, stage_codes[1:]):
    add_i(stage_modules[left], stage_nodes[left], "precedes", stage_nodes[right])
    add_i(stage_modules[left], stage_last_activity[left], "precedes", stage_first_activity[right])


# ---------------------------------------------------------------------------
# Data ontology: parameter definitions, ranges, errors and metadata profiles
# ---------------------------------------------------------------------------

PARAMETERS: list[dict[str, str]] = []
PARAMETERS += parse_rows("""
REGION_NAME|Название региона|string|none|registered name|identifier conflict resolved
REGION_AREA|Площадь региона|float|km2|1e2..1e7|1..10 %
REGION_CRS|Система координат региона|string|EPSG/WKT|controlled CRS|no silent transformation
TECTONIC_PROVINCE|Тектоническая провинция|categorical|none|controlled vocabulary|expert confidence 0..1
BASIN_TYPE|Тип осадочного бассейна|categorical|none|rift, foreland, passive margin, intracratonic, strike-slip|expert confidence 0..1
BASEMENT_DEPTH|Глубина фундамента|float|m TVDSS|-15000..0|50..500 m
CRUSTAL_THICKNESS|Мощность земной коры|float|km|5..70|1..5 km
REGIONAL_HEAT_FLOW|Региональный тепловой поток|float|mW/m2|20..150|5..20 mW/m2
GEOTHERMAL_GRADIENT|Геотермический градиент|float|degC/km|10..80|2..10 degC/km
PRESENT_DAY_SURFACE_TEMP|Современная температура поверхности|float|degC|-50..50|1..3 degC
GRAVITY_ANOMALY|Гравитационная аномалия|float|mGal|-300..300|0.1..5 mGal
MAGNETIC_ANOMALY|Магнитная аномалия|float|nT|-5000..5000|1..50 nT
REGIONAL_STRESS_AZIMUTH|Азимут максимального горизонтального напряжения|float|degree|0..360|5..20 degree
TECTONIC_EVENT_AGE|Возраст тектонического события|float|Ma|0..4600|0.1..20 Ma
UPLIFT_MAGNITUDE|Амплитуда поднятия|float|m|0..10000|50..500 m
EROSION_THICKNESS|Эродированная мощность|float|m|0..10000|50..1000 m
STRATIGRAPHIC_AGE_TOP|Возраст кровли единицы|float|Ma|0..4600|0.01..10 Ma
STRATIGRAPHIC_AGE_BASE|Возраст подошвы единицы|float|Ma|0..4600|0.01..10 Ma
DEPOSITIONAL_ENVIRONMENT|Обстановка осадконакопления|categorical|none|continental, transitional, shallow marine, deep marine, carbonate|classification probability 0..1
PALEOWATER_DEPTH|Палеоглубина моря|float|m|0..6000|10..500 m
PALEOCURRENT_AZIMUTH|Азимут палеотечения|float|degree|0..360|10..40 degree
SEDIMENT_SUPPLY_RATE|Темп поступления осадка|float|m/Ma|0..10000|order-of-magnitude
SUBSIDENCE_RATE|Темп погружения|float|m/Ma|-5000..5000|10..500 m/Ma
SOURCE_ROCK_TOC|TOC материнской породы|float|wt%|0..30|0.1..1 wt%
SOURCE_ROCK_HI|Водородный индекс|float|mgHC/gTOC|0..1000|20..100 mgHC/gTOC
SOURCE_ROCK_RO|Отражательная способность витринита Ro|float|%|0..5|0.05..0.2 %
KEROGEN_TYPE|Тип керогена|categorical|none|I, II, III, IV|expert probability 0..1
EXPULSION_EFFICIENCY|Эффективность эмиграции УВ|float|fraction|0..1|0.1..0.3
MIGRATION_DISTANCE|Длина миграции|float|km|0..1000|1..100 km
CHARGE_TIMING|Время зарядки ловушки|float|Ma|0..500|1..20 Ma
SEAL_CAPACITY|Предельное давление покрышки|float|MPa|0..100|0.5..10 MPa
TRAP_FORMATION_AGE|Возраст формирования ловушки|float|Ma|0..500|1..20 Ma
PLAY_AREA|Площадь play|float|km2|1..1e6|5..30 %
PLAY_RESERVOIR_PRESENCE|Вероятность наличия коллектора|float|fraction|0..1|calibrated probability
PLAY_CHARGE_PRESENCE|Вероятность зарядки|float|fraction|0..1|calibrated probability
PLAY_SEAL_PRESENCE|Вероятность покрышки|float|fraction|0..1|calibrated probability
PLAY_TRAP_PRESENCE|Вероятность ловушки|float|fraction|0..1|calibrated probability
PLAY_GCOS|Геологическая вероятность успеха GCoS|float|fraction|0..1|dependency-aware probability
REGIONAL_ANALOG_DISTANCE|Геологическая дистанция аналога|float|dimensionless|0..1|method dependent
REGIONAL_DATA_DENSITY|Плотность региональных наблюдений|float|count/km2|0..100|sampling uncertainty
""", "LEVEL_REGION", "regional_play", "S03", "regional seismic, maps, wells, basin-model inputs")

PARAMETERS += parse_rows("""
FIELD_NAME|Название месторождения|string|none|registered name|identifier conflict resolved
FIELD_AREA|Площадь месторождения|float|km2|0.1..10000|1..10 %
STRUCTURAL_CLOSURE_AREA|Площадь замыкания|float|km2|0.001..10000|3..30 %
STRUCTURAL_CLOSURE_HEIGHT|Высота замыкания|float|m|0..5000|5..200 m
CREST_DEPTH|Глубина свода|float|m TVDSS|-15000..500|2..100 m
SPILL_POINT_DEPTH|Глубина точки перелива|float|m TVDSS|-15000..500|5..150 m
FIELD_FAULT_COUNT|Число картированных разломов|integer|count|0..100000|interpretation dependent
FAULT_THROW|Амплитуда разлома|float|m|0..5000|1..100 m
FAULT_DIP|Угол падения разлома|float|degree|0..90|2..10 degree
FAULT_AZIMUTH|Азимут простирания разлома|float|degree|0..360|2..15 degree
FAULT_HEAVE|Горизонтальная амплитуда разлома|float|m|0..5000|2..150 m
FAULT_SEAL_PROBABILITY|Вероятность экранирования разлома|float|fraction|0..1|0.1..0.3
SHALE_GOUGE_RATIO|Shale gouge ratio|float|fraction|0..1|0.05..0.2
FAULT_TRANSMISSIBILITY_MULTIPLIER|Множитель проводимости разлома|distribution|dimensionless|0..1000|scenario distribution
HORIZON_TIME|Время отражающего горизонта|float|ms TWT|0..20000|1..20 ms
HORIZON_DEPTH|Глубина горизонта|float|m TVDSS|-15000..500|2..200 m
DEPTH_CONVERSION_BIAS|Систематическая ошибка преобразования глубины|float|m|-1000..1000|posterior distribution
WELL_MISTIE|Невязка скважина-поверхность|float|m|-500..500|target project tolerance
SEISMIC_COVERAGE|Покрытие сейсмикой|float|fraction|0..1|survey footprint error
WELL_DENSITY|Плотность скважин|float|count/km2|0..100|sampling uncertainty
FIELD_OIL_WATER_CONTACT|ГНК/ВНК по месторождению|float|m TVDSS|-15000..500|1..100 m
FIELD_GAS_OIL_CONTACT|ГНК по месторождению|float|m TVDSS|-15000..500|1..100 m
FIELD_PRESSURE_DATUM|Глубина приведения давления|float|m TVDSS|-15000..500|0.1..5 m
FIELD_INITIAL_PRESSURE|Начальное пластовое давление|float|MPa|0..200|0.1..5 MPa
FIELD_TEMPERATURE|Пластовая температура|float|degC|-10..300|0.5..5 degC
FIELD_STOIIP|Геологические запасы нефти STOIIP|distribution|m3|0..1e12|P10/P50/P90
FIELD_GIIP|Геологические запасы газа GIIP|distribution|m3|0..1e15|P10/P50/P90
FIELD_CUM_OIL|Накопленная добыча нефти|float|m3|0..1e12|0.1..5 %
FIELD_CUM_WATER|Накопленная добыча воды|float|m3|0..1e12|0.5..10 %
FIELD_CUM_GAS|Накопленная добыча газа|float|m3|0..1e15|0.5..10 %
FIELD_CUM_INJECTION|Накопленная закачка|float|m3|0..1e12|0.5..10 %
FIELD_VOIDAGE_REPLACEMENT|Коэффициент компенсации отбора|float|fraction|0..5|0.02..0.2
FIELD_WATER_CUT|Обводнённость месторождения|float|fraction|0..1|0.01..0.1
FIELD_RECOVERY_FACTOR|Коэффициент извлечения|distribution|fraction|0..1|P10/P50/P90
FIELD_DEVELOPMENT_STAGE|Стадия разработки|categorical|none|1, 2, 3, 4, aftercare|classification governed
""", "LEVEL_FIELD", "field_structure", "S07", "seismic interpretation, surveys, production accounting")

PARAMETERS += parse_rows("""
RESERVOIR_NAME|Название пласта / резервуара|string|none|registered stratigraphic name|identifier conflict resolved
RESERVOIR_TOP_DEPTH|Глубина кровли пласта|float|m TVDSS|-15000..500|0.5..50 m
RESERVOIR_BASE_DEPTH|Глубина подошвы пласта|float|m TVDSS|-15000..500|0.5..50 m
GROSS_THICKNESS|Общая мощность|float|m|0..2000|0.1..20 m
NET_THICKNESS|Эффективная мощность|float|m|0..2000|0.1..20 m
NET_TO_GROSS|Коэффициент песчанистости NTG|float|fraction|0..1|0.02..0.15
RESERVOIR_GRV|Геометрический объём пласта GRV|distribution|m3|0..1e13|P10/P50/P90
BULK_ROCK_VOLUME|Объём породы|distribution|m3|0..1e13|P10/P50/P90
PORE_VOLUME|Поровый объём|distribution|m3|0..1e12|P10/P50/P90
HYDROCARBON_PORE_VOLUME|Поровый объём УВ|distribution|m3|0..1e12|P10/P50/P90
LITHOLOGY_CLASS|Класс литологии|categorical|none|project code list|classification probability 0..1
FACIES_CLASS|Класс фации|categorical|none|project hierarchy|posterior probability 0..1
ROCK_TYPE|Тип породы|categorical|none|petrophysical rock type|classification probability 0..1
HYDRAULIC_FLOW_UNIT|Гидравлическая единица потока HFU|categorical|none|project code list|cluster stability
TOTAL_POROSITY|Общая пористость|float|fraction|0..0.7|0.005..0.05
EFFECTIVE_POROSITY|Эффективная пористость|float|fraction|0..0.6|0.005..0.05
CONNECTED_POROSITY|Связанная пористость|float|fraction|0..0.6|0.01..0.08
MATRIX_PERMEABILITY_X|Проницаемость по X|distribution|mD|1e-6..1e6|log-space uncertainty
MATRIX_PERMEABILITY_Y|Проницаемость по Y|distribution|mD|1e-6..1e6|log-space uncertainty
MATRIX_PERMEABILITY_Z|Вертикальная проницаемость|distribution|mD|1e-8..1e6|log-space uncertainty
KH|Горизонтальная проницаемость|distribution|mD|1e-6..1e6|log-space uncertainty
KV|Вертикальная проницаемость|distribution|mD|1e-8..1e6|log-space uncertainty
KV_KH_RATIO|Анизотропия Kv/Kh|distribution|fraction|0..100|scenario distribution
POROSITY_CUTOFF|Граничная пористость коллектора|float|fraction|0..0.5|project sensitivity
PERMEABILITY_CUTOFF|Граничная проницаемость коллектора|float|mD|0..10000|project sensitivity
SHALE_VOLUME_CUTOFF|Граничная глинистость|float|fraction|0..1|project sensitivity
WATER_SATURATION|Водонасыщенность|distribution|fraction|0..1|0.02..0.15
OIL_SATURATION|Нефтенасыщенность|distribution|fraction|0..1|closure residual
GAS_SATURATION|Газонасыщенность|distribution|fraction|0..1|closure residual
IRREDUCIBLE_WATER_SATURATION|Связанная водонасыщенность Swir|float|fraction|0..1|0.02..0.15
RESIDUAL_OIL_SATURATION|Остаточная нефтенасыщенность Sor|float|fraction|0..1|0.03..0.2
RESIDUAL_GAS_SATURATION|Остаточная газонасыщенность Sgr|float|fraction|0..1|0.02..0.2
FREE_WATER_LEVEL|Уровень свободной воды FWL|distribution|m TVDSS|-15000..500|1..100 m
TRANSITION_ZONE_THICKNESS|Мощность переходной зоны|distribution|m|0..1000|10..50 %
CAPILLARY_PRESSURE|Капиллярное давление|function|MPa|-10..100|laboratory repeatability
LEVERETT_J|Функция Леверетта J|function|dimensionless|-10..100|rock-type dependent
INTERFACIAL_TENSION|Межфазное натяжение|float|mN/m|0..100|0.1..5 mN/m
WETTABILITY_INDEX|Индекс смачиваемости|float|dimensionless|-1..1|0.05..0.2
RELATIVE_PERMEABILITY_OW|Относительная проницаемость нефть-вода|function|fraction|0..1|SCAL envelope
RELATIVE_PERMEABILITY_GO|Относительная проницаемость газ-нефть|function|fraction|0..1|SCAL envelope
COREY_EXPONENT_WATER|Показатель Кори для воды|float|dimensionless|0.1..10|fit confidence interval
COREY_EXPONENT_OIL|Показатель Кори для нефти|float|dimensionless|0.1..10|fit confidence interval
HYSTERESIS_MODEL|Модель гистерезиса|categorical|none|none, Carlson, Killough, Land|model-form uncertainty
RESERVOIR_PRESSURE|Пластовое давление|distribution|MPa|0..250|0.05..5 MPa
PRESSURE_GRADIENT|Градиент давления|float|MPa/km|0..30|0.05..1 MPa/km
RESERVOIR_TEMPERATURE|Температура пласта|distribution|degC|-10..350|0.5..5 degC
COMPARTMENT_ID|Идентификатор гидродинамического блока|string|none|project identifier|connectivity uncertainty
COMPARTMENT_CONNECTIVITY|Связность блоков|float|fraction|0..1|posterior probability
PRESSURE_COMMUNICATION|Вероятность гидродинамической связи|float|fraction|0..1|posterior probability
AQUIFER_STRENGTH|Активность водоносной области|distribution|dimensionless|0..100|scenario distribution
AQUIFER_VOLUME|Объём аквифера|distribution|m3|0..1e15|P10/P50/P90
FRACTURE_INTENSITY|Интенсивность трещин P32|distribution|m2/m3|0..100|sampling uncertainty
FRACTURE_APERTURE|Раскрытие трещин|distribution|mm|0..100|log-space uncertainty
FRACTURE_PERMEABILITY|Проницаемость трещин|distribution|mD|1e-6..1e9|log-space uncertainty
RESERVOIR_STOIIP|Геологические запасы нефти пласта|distribution|m3|0..1e12|P10/P50/P90
RESERVOIR_GIIP|Геологические запасы газа пласта|distribution|m3|0..1e15|P10/P50/P90
RESERVES_CLASS|Категория запасов / ресурсов|categorical|none|PRMS and jurisdiction-specific|classification governance
""", "LEVEL_RESERVOIR", "reservoir_properties", "S14", "logs, core, pressure, PVT, seismic and geomodel")

PARAMETERS += parse_rows("""
DEPOSIT_NAME|Название залежи / объекта|string|none|registered name|identifier conflict resolved
DEPOSIT_TYPE|Тип залежи|categorical|none|oil, gas, condensate, mixed|classification confidence
TRAP_TYPE|Тип ловушки|categorical|none|structural, stratigraphic, combination|classification confidence
FLUID_CONTACT_TILT|Наклон флюидного контакта|float|m/km|-100..100|0.1..10 m/km
CONTACT_AZIMUTH|Азимут наклона контакта|float|degree|0..360|5..30 degree
DEPOSIT_AREA|Площадь залежи|distribution|km2|0.001..10000|P10/P50/P90
DEPOSIT_HEIGHT|Высота залежи|distribution|m|0..5000|P10/P50/P90
OIL_COLUMN_HEIGHT|Высота нефтяной части|distribution|m|0..5000|P10/P50/P90
GAS_CAP_HEIGHT|Высота газовой шапки|distribution|m|0..5000|P10/P50/P90
DEPOSIT_AVG_POROSITY|Средняя пористость залежи|distribution|fraction|0..0.6|P10/P50/P90
DEPOSIT_AVG_PERMEABILITY|Средняя проницаемость залежи|distribution|mD|1e-6..1e6|log-space uncertainty
DEPOSIT_AVG_SATURATION|Средняя насыщенность УВ|distribution|fraction|0..1|P10/P50/P90
DEPOSIT_INITIAL_PRESSURE|Начальное давление залежи|distribution|MPa|0..250|0.05..5 MPa
DEPOSIT_CURRENT_PRESSURE|Текущее давление залежи|distribution|MPa|0..250|0.05..5 MPa
DEPLETION|Истощение давления|distribution|MPa|-100..250|survey and datum uncertainty
DEPOSIT_COMPARTMENT_COUNT|Число гидродинамических блоков|integer|count|1..100000|interpretation dependent
DEPOSIT_CONNECTIVITY_INDEX|Индекс связности залежи|float|fraction|0..1|posterior uncertainty
DEPOSIT_RECOVERY_FACTOR|Коэффициент извлечения залежи|distribution|fraction|0..1|P10/P50/P90
DEPOSIT_REMAINING_MOBILE_OIL|Остаточная подвижная нефть|distribution|m3|0..1e12|P10/P50/P90
DEPOSIT_BYPASSED_PAY|Невыработанные интервалы|distribution|m|0..2000|surveillance uncertainty
""", "LEVEL_DEPOSIT", "deposit_characterization", "S16", "integrated static, dynamic and surveillance interpretation")

PARAMETERS += parse_rows("""
WELL_UWI|Уникальный идентификатор скважины|string|none|globally unique in project|duplicate forbidden
WELL_NAME|Имя скважины|string|none|registered name|alias resolution required
WELL_TYPE|Тип скважины|categorical|none|exploration, appraisal, producer, injector, observation, abandoned|classification governed
WELL_STATUS|Состояние скважины|categorical|none|planned, drilling, active, suspended, abandoned|effective-dated value
SPUD_DATE|Дата начала бурения|date|ISO-8601|project history|date uncertainty allowed
COMPLETION_DATE|Дата ввода / заканчивания|date|ISO-8601|project history|date uncertainty allowed
SURVEY_DATE|Дата инклинометрии|date|ISO-8601|project history|timestamp accuracy
WELL_X|Координата устья X|float|m|CRS domain|0.01..20 m
WELL_Y|Координата устья Y|float|m|CRS domain|0.01..20 m
WELL_DATUM_ELEVATION|Абсолютная отметка datum|float|m|-1000..10000|0.01..2 m
KELLY_BUSHING_ELEVATION|Отметка стола ротора / KB|float|m|-1000..10000|0.01..0.5 m
GROUND_LEVEL_ELEVATION|Отметка земли|float|m|-1000..10000|0.01..2 m
MEASURED_DEPTH|Измеренная глубина MD|float|m|0..20000|0.01..5 m
TRUE_VERTICAL_DEPTH|Вертикальная глубина TVD|float|m|0..15000|0.05..10 m
TRUE_VERTICAL_DEPTH_SS|Абсолютная глубина TVDSS|float|m|-15000..1000|0.05..10 m
INCLINATION|Зенитный угол|float|degree|0..180|0.05..2 degree
AZIMUTH|Азимут ствола|float|degree|0..360|0.1..5 degree
DOGLEG_SEVERITY|Интенсивность искривления DLS|float|degree/30m|0..100|0.1..2 degree/30m
CALIPER|Диаметр ствола CALI|curve|mm|0..1000|tool and washout dependent
BIT_SIZE|Диаметр долота BS|curve|mm|0..1000|0.1..2 mm
GAMMA_RAY|Гамма-каротаж GR|curve|API|-50..1000|2..15 API
SPONTANEOUS_POTENTIAL|Потенциал самопроизвольной поляризации SP|curve|mV|-500..500|2..20 mV
NEUTRON_POROSITY|Нейтронная пористость NPHI|curve|fraction|-0.2..1|0.01..0.05
BULK_DENSITY|Объёмная плотность RHOB|curve|g/cm3|0.5..5|0.01..0.05 g/cm3
DENSITY_CORRECTION|Поправка плотностного каротажа DRHO|curve|g/cm3|-1..1|tool dependent
COMPRESSSIONAL_SONIC|Интервальное время P-волны DT|curve|us/ft|20..1000|0.5..10 us/ft
SHEAR_SONIC|Интервальное время S-волны DTS|curve|us/ft|20..2000|1..20 us/ft
PHOTOELECTRIC_FACTOR|Фотоэлектрический фактор PE|curve|b/e|-5..30|0.1..1 b/e
DEEP_RESISTIVITY|Глубокое сопротивление RT|curve|ohm.m|1e-4..1e6|5..20 %
MEDIUM_RESISTIVITY|Среднее сопротивление|curve|ohm.m|1e-4..1e6|5..20 %
SHALLOW_RESISTIVITY|Мелкое сопротивление|curve|ohm.m|1e-4..1e6|5..20 %
MICRO_RESISTIVITY|Микросопротивление MSFL|curve|ohm.m|1e-4..1e6|5..25 %
URANIUM|Содержание урана|curve|ppm|0..1000|0.1..5 ppm
THORIUM|Содержание тория|curve|ppm|0..1000|0.1..5 ppm
POTASSIUM|Содержание калия|curve|wt%|0..20|0.05..0.5 wt%
NMR_TOTAL_POROSITY|Пористость ЯМК|curve|fraction|0..0.7|0.01..0.05
NMR_T2_DISTRIBUTION|Распределение T2 ЯМК|array|ms|0.01..10000|tool and inversion dependent
NMR_PERMEABILITY|Проницаемость ЯМК|curve|mD|1e-6..1e6|model-form uncertainty
BOREHOLE_IMAGE_ORIENTATION|Ориентация элемента изображения ствола|array|degree|0..360|1..10 degree
FRACTURE_DIP_WELL|Угол падения трещины по имиджеру|float|degree|0..90|2..10 degree
FRACTURE_AZIMUTH_WELL|Азимут трещины по имиджеру|float|degree|0..360|3..15 degree
CORE_TOP_MD|Глубина верха керна|float|m MD|0..20000|0.01..1 m
CORE_RECOVERY|Вынос керна|float|fraction|0..1|0.01..0.1
CORE_POROSITY|Пористость керна|float|fraction|0..0.7|0.002..0.03
CORE_PERMEABILITY|Проницаемость керна|float|mD|1e-8..1e7|5..30 %
CORE_GRAIN_DENSITY|Минералогическая плотность керна|float|g/cm3|1..6|0.005..0.05 g/cm3
CORE_WATER_SATURATION|Водонасыщенность керна|float|fraction|0..1|preservation dependent
CORE_OIL_SATURATION|Нефтенасыщенность керна|float|fraction|0..1|preservation dependent
MICP_ENTRY_PRESSURE|Давление вытеснения MICP|float|MPa|0..500|2..15 %
PORE_THROAT_RADIUS|Радиус поровых каналов|distribution|um|0.001..10000|model dependent
LOG_SHALE_VOLUME|Объём глинистого материала Vsh|curve|fraction|0..1|0.03..0.15
LOG_EFFECTIVE_POROSITY|Эффективная пористость по ГИС|curve|fraction|0..0.6|0.01..0.06
LOG_WATER_SATURATION|Водонасыщенность по ГИС|curve|fraction|0..1|0.03..0.2
LOG_LITHOLOGY|Литология по ГИС|categorical_curve|none|project code list|posterior probability
LOG_FACIES|Фация по скважине|categorical_curve|none|project hierarchy|posterior probability
LOG_PERMEABILITY|Проницаемость по ГИС|curve|mD|1e-8..1e7|log-space uncertainty
FORMATION_PRESSURE_POINT|Точечное пластовое давление RFT/MDT|observation|MPa|0..250|0.01..1 MPa
FORMATION_MOBILITY|Подвижность по опробованию пласта|observation|mD/cP|0..1e8|tool and cleanup dependent
WELLTEST_TIME|Время ГДИС|series|h|0..1e6|sampling accuracy
WELLTEST_PRESSURE|Давление ГДИС|series|MPa|0..250|0.001..0.1 MPa
WELLTEST_RATE|Дебит / приёмистость ГДИС|series|m3/day|-1e6..1e6|1..10 %
PRESSURE_DERIVATIVE|Производная давления|series|MPa|0..250|diagnostic noise
WELLTEST_SKIN|Скин-фактор|distribution|dimensionless|-100..10000|interpretation uncertainty
WELLTEST_KH|Гидропроводность kh|distribution|mD.m|1e-6..1e10|interpretation uncertainty
PRODUCTIVITY_INDEX|Коэффициент продуктивности PI|distribution|m3/day/MPa|0..1e8|test stability dependent
INJECTIVITY_INDEX|Коэффициент приёмистости|distribution|m3/day/MPa|0..1e8|test stability dependent
IPR_CURVE|Индикаторная диаграмма IPR|function|mixed|operating envelope|fit uncertainty
AOF|Абсолютно свободный дебит газа AOF|distribution|m3/day|0..1e9|method uncertainty
PERFORATION_TOP|Верх перфорации|float|m MD|0..20000|0.01..1 m
PERFORATION_BASE|Низ перфорации|float|m MD|0..20000|0.01..1 m
PERFORATION_DATE|Дата перфорации|date|ISO-8601|project history|timestamp accuracy
COMPLETION_DIAMETER|Внутренний диаметр заканчивания|float|mm|0..1000|0.1..2 mm
TUBING_DEPTH|Глубина НКТ|float|m MD|0..20000|0.1..5 m
DAILY_OIL_RATE|Дебит нефти|series|m3/day|0..1e6|1..10 %
DAILY_WATER_RATE|Дебит воды|series|m3/day|0..1e6|1..15 %
DAILY_GAS_RATE|Дебит газа|series|m3/day|0..1e9|1..15 %
DAILY_INJECTION_RATE|Приёмистость|series|m3/day|0..1e6|1..15 %
WELL_WATER_CUT|Обводнённость скважины|series|fraction|0..1|0.01..0.1
BOTTOMHOLE_PRESSURE|Забойное давление|series|MPa|0..250|0.01..2 MPa
WELLHEAD_PRESSURE|Устьевое давление|series|MPa|0..100|0.01..1 MPa
WELL_TEMPERATURE|Температура скважины|series|degC|-50..350|0.1..3 degC
CHOKE_DIAMETER|Диаметр штуцера|series|mm|0..500|0.1..1 mm
LIFT_METHOD|Способ эксплуатации|categorical|none|flowing, ESP, gas lift, rod pump, injection|effective-dated
WORKOVER_EVENT|ГТМ / ремонт скважины|event|none|project event taxonomy|date and classification uncertainty
TRACER_RESPONSE|Отклик трассера|series|concentration|0..1e9|sampling and decay uncertainty
PLT_RATE_PROFILE|Профиль притока / приёмистости PLT|curve|m3/day/m|-1e6..1e6|tool and phase-allocation uncertainty
""", "LEVEL_WELL", "well_logs_core_tests_history", "S08", "legacy and modern logging tools, core laboratory, gauges, production allocation")

PARAMETERS += parse_rows("""
GRID_NAME|Имя сетки|string|none|unique in model version|duplicate forbidden
GRID_TYPE|Тип сетки|categorical|none|corner-point, Cartesian, unstructured, hybrid, radial|model-form choice
GRID_DIMENSION|Размерность сетки|categorical|none|2D, 2.5D, 3D, 4D|governed choice
GRID_NX|Число ячеек по I|integer|count|1..100000|exact
GRID_NY|Число ячеек по J|integer|count|1..100000|exact
GRID_NZ|Число слоёв K|integer|count|1..100000|exact
GRID_CELL_COUNT|Полное число ячеек|integer|count|1..1e10|exact
GRID_DX|Размер ячейки по X|distribution|m|0.01..100000|local variability
GRID_DY|Размер ячейки по Y|distribution|m|0.01..100000|local variability
GRID_DZ|Размер ячейки по Z|distribution|m|0.001..10000|local variability
CELL_VOLUME|Объём ячейки|float|m3|0..1e15|geometric tolerance
CELL_ACTIVE|Активность ячейки|boolean|none|true or false|exact rule-dependent
CELL_TOP_DEPTH|Глубина кровли ячейки|float|m TVDSS|-15000..500|geometric tolerance
CELL_BASE_DEPTH|Глубина подошвы ячейки|float|m TVDSS|-15000..500|geometric tolerance
CELL_THICKNESS|Мощность ячейки|float|m|0..10000|geometric tolerance
CELL_ASPECT_RATIO|Отношение сторон ячейки|float|dimensionless|1..1e6|quality threshold project-specific
CELL_MIN_ANGLE|Минимальный угол ячейки|float|degree|0..180|quality threshold project-specific
CELL_MAX_ANGLE|Максимальный угол ячейки|float|degree|0..180|quality threshold project-specific
CELL_CONCAVITY|Вогнутость ячейки|float|dimensionless|0..1|quality threshold project-specific
CELL_NEGATIVE_VOLUME|Признак отрицательного объёма|boolean|none|false required|exact
CELL_PINCHOUT|Признак выклинивания|boolean|none|true or false|algorithm dependent
PILLAR_CURVATURE|Кривизна пиллара|float|1/m|0..100|geometric tolerance
FAULT_I_INDEX|I-индекс разлома в сетке|integer|index|1..100000|exact
FAULT_J_INDEX|J-индекс разлома в сетке|integer|index|1..100000|exact
TRANSMISSIBILITY_X|Проводимость по X|float|project units|0..1e30|numerical precision
TRANSMISSIBILITY_Y|Проводимость по Y|float|project units|0..1e30|numerical precision
TRANSMISSIBILITY_Z|Проводимость по Z|float|project units|0..1e30|numerical precision
MULTX|Множитель проводимости X|float|dimensionless|0..1e12|scenario dependent
MULTY|Множитель проводимости Y|float|dimensionless|0..1e12|scenario dependent
MULTZ|Множитель проводимости Z|float|dimensionless|0..1e12|scenario dependent
ACTNUM|Активность ACTNUM|integer|code|0..1|exact
FACIES_CELL|Фация ячейки|categorical|code|project code list|posterior probability
LITHOLOGY_CELL|Литология ячейки|categorical|code|project code list|posterior probability
ROCKTYPE_CELL|Тип породы ячейки|categorical|code|project code list|posterior probability
PORO_CELL|Пористость ячейки PORO|float|fraction|0..1|realization uncertainty
PERMX_CELL|Проницаемость PERMX|float|mD|0..1e12|realization uncertainty
PERMY_CELL|Проницаемость PERMY|float|mD|0..1e12|realization uncertainty
PERMZ_CELL|Проницаемость PERMZ|float|mD|0..1e12|realization uncertainty
SWAT_CELL|Водонасыщенность SWAT|float|fraction|0..1|realization uncertainty
NTG_CELL|Песчанистость NTG|float|fraction|0..1|realization uncertainty
PVTNUM|Номер PVT-региона|integer|code|1..100000|exact mapping
SATNUM|Номер региона насыщения|integer|code|1..100000|exact mapping
EQLNUM|Номер региона равновесия|integer|code|1..100000|exact mapping
FIPNUM|Номер региона подсчёта|integer|code|1..100000|exact mapping
GRID_PORE_VOLUME|Поровый объём сетки|distribution|m3|0..1e15|upscaling and realization error
GRID_HCPV|Поровый объём УВ сетки|distribution|m3|0..1e15|upscaling and realization error
POROSITY_UPSCALE_ERROR|Ошибка апскейлинга пористости|float|fraction|-1..1|project acceptance policy
PERMEABILITY_UPSCALE_ERROR|Ошибка апскейлинга проницаемости|distribution|log10 ratio|-10..10|project acceptance policy
FACIES_PROPORTION_ERROR|Ошибка долей фаций|float|fraction|-1..1|project acceptance policy
VOLUME_CONSERVATION_ERROR|Ошибка сохранения объёма|float|fraction|-1..1|project acceptance policy
""", "LEVEL_GRID", "grid_and_upscaling", "S15", "geological grid, simulation grid and upscaling workflow")

PARAMETERS += parse_rows("""
SEISMIC_SURVEY_ID|Идентификатор сейсмической съёмки|string|none|unique survey identifier|duplicate forbidden
SEISMIC_DIMENSION|Размерность сейсмики|categorical|none|2D, 3D, 4D|exact
ACQUISITION_YEAR|Год сейсмической съёмки|integer|year|1900..current|exact or interval
BIN_SIZE_INLINE|Размер бина inline|float|m|0.1..1000|survey geometry accuracy
BIN_SIZE_CROSSLINE|Размер бина crossline|float|m|0.1..1000|survey geometry accuracy
INLINE_SPACING|Шаг inline|float|m|0.1..10000|survey geometry accuracy
CROSSLINE_SPACING|Шаг crossline|float|m|0.1..10000|survey geometry accuracy
SOURCE_INTERVAL|Шаг источников|float|m|0.1..10000|survey geometry accuracy
RECEIVER_INTERVAL|Шаг приёмников|float|m|0.1..10000|survey geometry accuracy
FOLD_COVERAGE|Кратность покрытия|float|count|1..100000|geometry dependent
SAMPLE_INTERVAL|Шаг дискретизации|float|ms|0.01..20|clock accuracy
RECORD_LENGTH|Длина записи|float|ms|1..60000|clock accuracy
DOMINANT_FREQUENCY|Доминирующая частота|float|Hz|0.1..1000|1..10 Hz
SEISMIC_BANDWIDTH|Полоса частот|interval|Hz|0..2000|processing dependent
VERTICAL_RESOLUTION|Вертикальная разрешённость|distribution|m|0.1..500|velocity and bandwidth dependent
HORIZONTAL_RESOLUTION|Горизонтальная разрешённость|distribution|m|0.1..5000|aperture dependent
SIGNAL_TO_NOISE|Отношение сигнал/шум|float|dB|-100..100|window dependent
STATIC_CORRECTION|Статическая поправка|field|ms|-10000..10000|near-surface uncertainty
NMO_VELOCITY|Скорость NMO|field|m/s|100..10000|pick uncertainty
INTERVAL_VELOCITY|Интервальная скорость|field|m/s|100..15000|model uncertainty
RMS_VELOCITY|Среднеквадратичная скорость|field|m/s|100..15000|pick uncertainty
ANISOTROPY_EPSILON|Параметр анизотропии epsilon|field|dimensionless|-1..1|inversion uncertainty
ANISOTROPY_DELTA|Параметр анизотропии delta|field|dimensionless|-1..1|inversion uncertainty
ANISOTROPY_THETA|Наклон оси анизотропии|field|degree|0..180|inversion uncertainty
ANISOTROPY_PHI|Азимут оси анизотропии|field|degree|0..360|inversion uncertainty
MIGRATION_APERTURE|Апертура миграции|float|m|0..100000|processing sensitivity
SEISMIC_PHASE|Фаза сейсмического сигнала|float|degree|-180..180|5..30 degree
SEISMIC_POLARITY|Полярность сейсмики|categorical|none|SEG normal, reverse|must be verified
TIME_SHIFT_4D|Временной сдвиг 4D|field|ms|-1000..1000|repeatability uncertainty
NRMS_4D|Нормированная RMS-разница 4D|field|fraction|0..10|repeatability benchmark
SEISMIC_AMPLITUDE|Амплитуда сейсмики|field|project units|-1e30..1e30|processing dependent
ACOUSTIC_IMPEDANCE|Акустический импеданс|field|kg/m2/s|0..1e9|inversion uncertainty
SHEAR_IMPEDANCE|Сдвиговый импеданс|field|kg/m2/s|0..1e9|inversion uncertainty
VP_VS_RATIO|Отношение Vp/Vs|field|dimensionless|0.5..5|inversion uncertainty
SEISMIC_POROSITY|Пористость по сейсмической инверсии|field|fraction|0..0.7|posterior uncertainty
SEISMIC_FACIES|Сейсмофация|categorical_field|none|project hierarchy|posterior probability
FAULT_PROBABILITY_VOLUME|Куб вероятности разломов|field|fraction|0..1|calibration uncertainty
HORIZON_PICK_CONFIDENCE|Доверие к пикировке горизонта|field|fraction|0..1|interpreter and algorithm dependent
DEPTH_VELOCITY_MODEL|Глубинно-скоростная модель|model|m/s|100..15000|posterior ensemble
SEISMIC_DATUM|Датум сейсмики|float|m|-1000..10000|0.01..1 m
""", "LEVEL_FIELD", "seismic_and_structural", "S06", "SEG-Y and vendor seismic volumes, navigation and velocity models")

PARAMETERS += parse_rows("""
PVT_REGION_ID|Идентификатор PVT-региона|string|none|unique in model|exact mapping
FLUID_SYSTEM|Тип флюидной системы|categorical|none|black-oil, volatile-oil, dry-gas, wet-gas, compositional, thermal|model-form uncertainty
EOS_MODEL|Уравнение состояния|categorical|none|PR, SRK, CPA, project-specific|model-form uncertainty
COMPONENT_FRACTION|Мольная доля компонента|array|fraction|0..1|closure and laboratory error
OIL_DENSITY_STOCK|Плотность дегазированной нефти|float|kg/m3|400..1200|0.5..10 kg/m3
GAS_DENSITY_STANDARD|Плотность газа при стандартных условиях|float|kg/m3|0.1..10|0.005..0.1 kg/m3
WATER_DENSITY_STANDARD|Плотность воды при стандартных условиях|float|kg/m3|800..1300|0.5..10 kg/m3
OIL_VISCOSITY|Вязкость нефти|function|cP|0.01..1e7|laboratory and fit uncertainty
GAS_VISCOSITY|Вязкость газа|function|cP|0.001..10|laboratory and fit uncertainty
WATER_VISCOSITY|Вязкость воды|function|cP|0.01..100|laboratory and fit uncertainty
OIL_FVF|Объёмный коэффициент нефти Bo|function|rm3/sm3|0.5..10|laboratory and fit uncertainty
GAS_FVF|Объёмный коэффициент газа Bg|function|rm3/sm3|1e-5..10|laboratory and fit uncertainty
WATER_FVF|Объёмный коэффициент воды Bw|function|rm3/sm3|0.5..2|laboratory and fit uncertainty
SOLUTION_GOR|Газосодержание Rs|function|sm3/sm3|0..1e6|laboratory and fit uncertainty
VAPORIZED_OIL_RATIO|Содержание испарённой нефти Rv|function|sm3/sm3|0..10|laboratory and fit uncertainty
BUBBLE_POINT|Давление насыщения нефти|float|MPa|0..250|0.1..5 MPa
DEW_POINT|Давление точки росы|float|MPa|0..250|0.1..5 MPa
OIL_COMPRESSIBILITY|Сжимаемость нефти|function|1/MPa|0..1|laboratory and fit uncertainty
GAS_COMPRESSIBILITY|Сжимаемость газа|function|1/MPa|0..10|laboratory and fit uncertainty
WATER_COMPRESSIBILITY|Сжимаемость воды|function|1/MPa|0..1|laboratory and fit uncertainty
ROCK_COMPRESSIBILITY|Сжимаемость породы|function|1/MPa|0..1|laboratory and scale uncertainty
WATER_SALINITY|Минерализация воды|float|g/L|0..500|0.1..10 g/L
WATER_FORMATION_VOLUME_FACTOR|Объёмный коэффициент пластовой воды|function|rm3/sm3|0.5..2|fit uncertainty
FLASH_SEPARATOR_STAGE|Ступень сепарации|categorical|none|laboratory or facility stage|condition uncertainty
REFERENCE_PRESSURE|Референсное давление PVT|float|MPa|0..250|0.01..1 MPa
REFERENCE_TEMPERATURE|Референсная температура PVT|float|degC|-50..350|0.1..2 degC
""", "LEVEL_RESERVOIR", "pvt_and_saturation", "S12", "PVT and SCAL laboratory, EOS tuning and fluid sampling")

PARAMETERS += parse_rows("""
OVERBURDEN_STRESS|Вертикальное напряжение Sv|field|MPa|0..1000|1..20 MPa
MAX_HORIZONTAL_STRESS|Максимальное горизонтальное напряжение SHmax|field|MPa|0..1000|2..30 MPa
MIN_HORIZONTAL_STRESS|Минимальное горизонтальное напряжение Shmin|field|MPa|0..1000|1..20 MPa
PORE_PRESSURE|Поровое давление|field|MPa|0..500|0.1..10 MPa
EFFECTIVE_STRESS|Эффективное напряжение|field|MPa|-500..1000|model dependent
YOUNGS_MODULUS_STATIC|Статический модуль Юнга|field|GPa|0..200|5..30 %
YOUNGS_MODULUS_DYNAMIC|Динамический модуль Юнга|field|GPa|0..200|5..20 %
POISSON_RATIO_STATIC|Статический коэффициент Пуассона|field|fraction|-1..0.5|0.01..0.1
POISSON_RATIO_DYNAMIC|Динамический коэффициент Пуассона|field|fraction|-1..0.5|0.01..0.1
SHEAR_MODULUS|Модуль сдвига|field|GPa|0..200|5..30 %
BULK_MODULUS|Модуль объёмного сжатия|field|GPa|0..300|5..30 %
UNIAXIAL_COMPRESSIVE_STRENGTH|Предел прочности при одноосном сжатии UCS|field|MPa|0..1000|10..30 %
TENSILE_STRENGTH|Прочность на растяжение|field|MPa|0..100|10..40 %
COHESION|Сцепление|field|MPa|0..500|10..40 %
FRICTION_ANGLE|Угол внутреннего трения|field|degree|0..90|2..10 degree
BIOT_COEFFICIENT|Коэффициент Био|field|fraction|0..1.5|0.05..0.2
STRESS_REGIME|Режим напряжений|categorical|none|normal, strike-slip, reverse, mixed|classification probability
BREAKOUT_AZIMUTH|Азимут вывалов|observation|degree|0..360|5..20 degree
DITF_AZIMUTH|Азимут индуцированных трещин|observation|degree|0..360|5..20 degree
MUD_WEIGHT|Плотность бурового раствора|series|g/cm3|0.5..3|0.005..0.05 g/cm3
LEAKOFF_PRESSURE|Давление leak-off|observation|MPa|0..500|0.1..5 MPa
FRACTURE_GRADIENT|Градиент гидроразрыва|field|MPa/km|0..50|0.2..3 MPa/km
SAFE_MUD_WINDOW_LOW|Нижняя граница безопасного окна бурения|field|g/cm3|0.5..3|scenario uncertainty
SAFE_MUD_WINDOW_HIGH|Верхняя граница безопасного окна бурения|field|g/cm3|0.5..3|scenario uncertainty
COMPACTION_COEFFICIENT|Коэффициент уплотнения|function|1/MPa|0..1|laboratory and scale uncertainty
SUBSIDENCE|Оседание поверхности|field|m|-100..100|geodetic and model uncertainty
FAULT_REACTIVATION_RISK|Риск реактивации разлома|float|fraction|0..1|posterior probability
SANDING_RISK|Риск пескопроявления|float|fraction|0..1|posterior probability
CAPROCK_INTEGRITY_RISK|Риск нарушения покрышки|float|fraction|0..1|posterior probability
""", "LEVEL_RESERVOIR", "geomechanics", "S13", "logs, core mechanics, LOT/XLOT, image logs, pressure and stress models")

PARAMETERS += parse_rows("""
MODEL_VALID_TIME|Момент валидности модели|dateTime|ISO-8601|project history|timestamp and timezone governed
MODEL_TRANSACTION_TIME|Момент регистрации версии|dateTime|ISO-8601|repository history|system timestamp
MODEL_VERSION_ID|Идентификатор версии модели|string|none|immutable unique ID|exact
MODEL_PARENT_VERSION|Родительская версия модели|string|none|existing version ID|exact
DATA_CUTOFF_DATE|Дата отсечения входных данных|dateTime|ISO-8601|project history|exact or interval
TECHNOLOGY_GENERATION|Поколение технологии|categorical|none|analog, digitized, workstation, integrated, automated, semantic-agent|classification governed
EQUIPMENT_MODEL|Модель оборудования|string|none|manufacturer registry|unknown explicitly represented
EQUIPMENT_SERIAL|Серийный номер оборудования|string|none|manufacturer registry|unknown explicitly represented
CALIBRATION_DATE|Дата калибровки оборудования|date|ISO-8601|equipment history|record confidence
ACQUISITION_METHOD|Метод получения|string|none|controlled method vocabulary|classification governed
PROCESSING_SOFTWARE_VERSION|Версия ПО обработки|string|none|semantic version or vendor build|exact when available
INTERPRETER_ID|Идентификатор интерпретатора|string|none|project role registry|privacy governed
SOURCE_LICENSE|Лицензия источника|string|none|SPDX or project policy|legal review
CONFIDENCE_LEVEL|Уровень доверия|float|fraction|0..1|calibration required
CONFIDENCE_INTERVAL_LOW|Нижняя граница доверительного интервала|float|parameter unit|parameter domain|method dependent
CONFIDENCE_INTERVAL_HIGH|Верхняя граница доверительного интервала|float|parameter unit|parameter domain|method dependent
UNCERTAINTY_DISTRIBUTION|Распределение неопределённости|distribution|none|normal, lognormal, triangular, empirical, categorical|fit and model-form uncertainty
UNCERTAINTY_CORRELATION_ID|Идентификатор корреляции неопределённости|string|none|copula or correlation group|model dependent
MEASUREMENT_QUALITY_FLAG|Флаг качества измерения|categorical|none|accepted, conditional, rejected, unknown|policy governed
LINEAGE_COMPLETENESS|Полнота происхождения данных|float|fraction|0..1|metadata audit
""", "LEVEL_TIME", "provenance_and_evolution", "S18", "data catalog, archive, equipment registry and model repository")

parameter_rows: list[dict[str, str]] = []
for row in PARAMETERS:
    pid = "PARAM_" + safe(row["code"])
    qid = "QUALITY_" + safe(row["code"])
    tid = "TECHMETA_" + safe(row["code"])
    uid = "UNCERTAINTY_" + safe(row["code"])
    individual("16_data_ontology", pid, "ParameterDefinition", row["name"], row["code"])
    add_l("16_data_ontology", pid, "parameterCode", row["code"])
    add_l("16_data_ontology", pid, "dataType", row["data_type"])
    add_l("16_data_ontology", pid, "unitSymbolV4", row["unit"])
    add_l("16_data_ontology", pid, "typicalRange", row["typical_range"])
    add_l("16_data_ontology", pid, "typicalUncertainty", row["typical_error"])
    add_l("16_data_ontology", pid, "sourceTheme", row["domain"])
    add_i("16_data_ontology", pid, "appliesToLevel", row["level"])
    add_i("16_data_ontology", pid, "supportsProcessDomain", stage_nodes[row["stage"]])
    individual("16_data_ontology", qid, "ParameterQualityProfile", f"Профиль качества: {row['name']}")
    add_l("16_data_ontology", qid, "typicalRange", row["typical_range"])
    add_l("16_data_ontology", qid, "typicalUncertainty", row["typical_error"])
    add_l("16_data_ontology", qid, "normalizationRequirement", "Привести datum/CRS, единицы, знак, support и временную привязку к политике проекта; исходное значение не перезаписывать.", lang="ru")
    individual("16_data_ontology", tid, "TechnologyMetadataProfile", f"Технологические метаданные: {row['name']}")
    add_l("16_data_ontology", tid, "acquisitionYearRequired", True, datatype=XSD + "boolean")
    add_l("16_data_ontology", tid, "equipmentMetadataRequired", True, datatype=XSD + "boolean")
    add_l("16_data_ontology", tid, "technologyGenerationRequired", True, datatype=XSD + "boolean")
    add_l("16_data_ontology", tid, DCT + "description", f"Требуются дата/интервал получения, оборудование, серийный номер при наличии, метод, исходный формат, ПО и версия обработки. Типичные источники: {row['equipment']}.", lang="ru")
    individual("16_data_ontology", uid, "UncertaintyProfile", f"Профиль неопределённости: {row['name']}")
    add_l("16_data_ontology", uid, "uncertaintyModel", "Хранить value, unit, support, distribution/interval, confidence, bias, correlation group, aleatory/epistemic class and provenance.")
    add_i("16_data_ontology", pid, "hasQualityProfile", qid)
    add_i("16_data_ontology", pid, "hasTechnologyMetadataProfile", tid)
    add_i("16_data_ontology", pid, "hasUncertaintyProfile", uid)
    add_i("16_data_ontology", stage_last_activity[row["stage"]], "passesParameter", pid)
    parameter_rows.append({**row, "node": pid, "quality_profile": qid, "technology_profile": tid, "uncertainty_profile": uid})

# The ranges above are screening defaults, never universal acceptance limits.
individual("01_governance", "POLICY_PROJECT_PARAMETER_OVERRIDES", "Policy", "Политика проектного переопределения диапазонов и допусков", description="Типовые диапазоны служат обнаружению аномалий. Утверждённая проектная политика, тип залежи, метод измерения и стадия жизненного цикла имеют приоритет; каждое переопределение версионируется.")
for row in parameter_rows:
    add_i("16_data_ontology", row["node"], "governedBy", "POLICY_PROJECT_PARAMETER_OVERRIDES")


# ---------------------------------------------------------------------------
# QA/QC knowledge: imported checklist, historical checks and escalation
# ---------------------------------------------------------------------------

ESCALATION_ROUTES = {
    "S02": ("DATA_STEWARD", "Куратор данных"),
    "S03": ("REGIONAL_GEOLOGIST", "Региональный геолог"),
    "S04": ("STRATIGRAPHER", "Стратиграф"),
    "S05": ("SEDIMENTOLOGIST", "Седиментолог"),
    "S06": ("GEOPHYSICIST", "Геофизик"),
    "S07": ("STRUCTURAL_MODELER", "Специалист структурного моделирования"),
    "S08": ("PETROPHYSICIST", "Петрофизик"),
    "S09": ("RESERVOIR_GEOLOGIST", "Геолог по коллектору"),
    "S10": ("FACIES_MODELER", "Специалист фациального моделирования"),
    "S11": ("WELLTEST_ENGINEER", "Специалист ГДИС"),
    "S12": ("PVT_SCAL_ENGINEER", "Специалист PVT/SCAL"),
    "S13": ("GEOMECHANICS_ENGINEER", "Геомеханик"),
    "S14": ("GEOSTATISTICIAN", "Геостатистик"),
    "S15": ("GRID_RESERVES_ENGINEER", "Специалист по сеткам и запасам"),
    "S16": ("UNCERTAINTY_LEAD", "Эксперт по неопределённостям"),
    "S17": ("RESERVOIR_ENGINEER", "Инженер по разработке / ГДМ"),
    "S18": ("MODEL_CUSTODIAN", "Хранитель эволюционной модели"),
}
individual("17_qaqc_rules", "ROLE_QAQC_AGENT", "AgentRole", "Агент QA/QC")
for code, (role_code, label) in ESCALATION_ROUTES.items():
    role_id = "ROLE_" + role_code
    route_id = "ESCALATE_" + code
    individual("17_qaqc_rules", role_id, "AgentRole", label)
    individual("17_qaqc_rules", route_id, "EscalationRoute", f"Маршрут эскалации: {label}")
    add_i("17_qaqc_rules", route_id, "escalatesTo", role_id)
    add_i("17_qaqc_rules", route_id, "escalatesTo", "ROLE_QAQC_AGENT")
    add_i("17_qaqc_rules", route_id, "targetsNode", stage_nodes[code])

QUALITY_POLICY_VERSIONS = [
    ("QCV_1960_1975", "Критерии качества аналоговой эпохи", "ERA_1960_1975", "Читаемость, первичные носители, ручная метрология, журнал калибровки и двойная оцифровка."),
    ("QCV_1976_1990", "Критерии качества ранней цифровизации", "ERA_1976_1990", "Контроль формата, разрядности, кодировок, склейки оцифрованных кривых и datum."),
    ("QCV_1991_2004", "Критерии качества 3D и рабочих станций", "ERA_1991_2004", "CRS, well tie, grid topology, project database lineage и воспроизводимость интерпретации."),
    ("QCV_2005_2014", "Критерии интегрированной статико-динамической модели", "ERA_2005_2014", "Междисциплинарные балансы, стандартизованный обмен, ансамбли и history-match evidence."),
    ("QCV_2015_2024", "Критерии 4D и автоматизированных потоков", "ERA_2015_2024", "Cross-equalization винтажей, streaming lineage, schema validation и повторяемые pipelines."),
    ("QCV_2025_PLUS", "Критерии семантической и агентной эпохи", "ERA_2025_PLUS", "SHACL, доказательность правила, capability check, uncertainty-aware decision и обязательный fallback."),
]
previous_qcv = None
for qcv, label, era, description in QUALITY_POLICY_VERSIONS:
    individual("17_qaqc_rules", qcv, "QualityCriterionVersion", label, description=description)
    add_i("17_qaqc_rules", qcv, "appliesDuring", era)
    if previous_qcv:
        add_i("17_qaqc_rules", qcv, "supersedes", previous_qcv)
    previous_qcv = qcv


def map_block_to_stage(text: object) -> str:
    value = str(text or "").lower()
    patterns = [
        ("S18", ["эволюц", "архив", "верси", "поздн"]),
        ("S17", ["гдм", "динамич", "history", "адаптац"]),
        ("S16", ["неопредел", "допущ", "аналог", "ансамб"]),
        ("S15", ["сетка", "апскейл", "запас", "объём"]),
        ("S14", ["проницаем", "порист", "геостат", "вариограм"]),
        ("S13", ["геомехан", "напряж", "трещин"]),
        ("S12", ["насыщ", "pvt", "флюид", "контакт", "капил"]),
        ("S11", ["давлен", "гдис", "приток", "квд", "кпд"]),
        ("S10", ["фаци"]),
        ("S09", ["литолог", "коллектор", "тип пород"]),
        ("S08", ["петроф", "гис", "керн", "интерпретац крив"]),
        ("S07", ["структур", "разлом", "горизонт", "глубин"]),
        ("S06", ["сейсм", "геофиз"]),
        ("S05", ["седимент", "обстанов", "палеогеог"]),
        ("S04", ["стратиг", "корреляц"]),
        ("S03", ["регион", "play", "бассейн"]),
    ]
    for stage, words in patterns:
        if any(word in value for word in words):
            return stage
    return "S02"


def cell_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


qaqc_rows: list[dict[str, str]] = []
qa_book_path = TASK3 / "QAQC и проверки данных — копия" / "QA_QC_чеклист.xlsx"
wb = openpyxl.load_workbook(qa_book_path, read_only=True, data_only=False)
ws = wb["Чек-лист"]
headers = [cell_text(cell.value) for cell in next(ws.iter_rows(min_row=4, max_row=4))]
if "ID проверки / пункта" not in headers:
    raise RuntimeError("QA/QC checklist header not found")
for excel_row, values in enumerate(ws.iter_rows(min_row=5, values_only=True), start=5):
    record = {headers[index]: cell_text(value) for index, value in enumerate(values) if index < len(headers)}
    raw_id = record.get("ID проверки / пункта", "")
    check = record.get("Проверка", "")
    if not raw_id or not check:
        continue
    stage = map_block_to_stage(" ".join([record.get("Рабочий слой", ""), record.get("Обязательная область ГПН / блок", ""), check]))
    node = "QA_" + safe(raw_id, 110)
    condition = "; ".join(filter(None, [record.get("Что именно проверяется", ""), record.get("Входные данные", ""), record.get("Критерий прохождения", "")]))
    action = "; ".join(filter(None, [record.get("Метод / формула", ""), record.get("Что выдаёт проверка", ""), record.get("Что осталось сделать", "")]))
    if not condition:
        condition = check
    if not action:
        action = "Зафиксировать результат, доказательство и статус; при непрохождении остановить передачу и эскалировать владельцу домена."
    rule_type = "HistoricalQAQCRule" if any(token in (record.get("Тип записи", "").lower()) for token in ["истор", "ниокр"]) else "QAQCRule"
    if any(token in check.lower() for token in ["согласован", "сопостав", "междисцип", "кросс"]):
        rule_type = "CrossDisciplineRule"
    individual("17_qaqc_rules", node, rule_type, check)
    add_l("17_qaqc_rules", node, "conditionText", condition)
    add_l("17_qaqc_rules", node, "actionText", action)
    add_l("17_qaqc_rules", node, "qualityRuleText", f"Правило QAQC: [{condition}] -> [{action}] -> [{stage_nodes[stage]}]")
    add_l("17_qaqc_rules", node, "evidenceStatus", record.get("Состояние", "unknown") or "unknown")
    add_l("17_qaqc_rules", node, "criterionVersion", "QCV_2025_PLUS; source criterion preserved verbatim")
    add_i("17_qaqc_rules", node, "governedBy", "QCV_2025_PLUS")
    add_l("17_qaqc_rules", node, "sourcePath", str(qa_book_path.relative_to(ROOT)))
    add_l("17_qaqc_rules", node, "sourceRow", excel_row, datatype=XSD + "integer")
    for prop, key in [("recordType", "Тип записи"), ("workingLayer", "Рабочий слой"), ("qualityBlock", "Обязательная область ГПН / блок"), ("mechanism", "Механизм"), ("responsibleRole", "Кто делает"), ("evidenceText", "Доказательство и связи с источниками")]:
        if record.get(key):
            add_l("17_qaqc_rules", node, prop, record[key])
    add_i("17_qaqc_rules", node, "targetsNode", stage_nodes[stage])
    add_i("17_qaqc_rules", node, "hasEscalationRoute", "ESCALATE_" + stage)
    add_i("17_qaqc_rules", stage_nodes[stage], "hasRule", node)
    qaqc_rows.append({"node": node, "id": raw_id, "rule_type": rule_type, "stage": stage, "condition": condition, "action": action, "target": stage_nodes[stage], "state": record.get("Состояние", ""), "source_row": str(excel_row)})
wb.close()

# Additional historical production-data anomaly rules from the dedicated workbook.
problems_path = TASK3 / "QAQC и проверки данных — копия" / "Проблемы исходных данных (5).xlsx"
wb = openpyxl.load_workbook(problems_path, read_only=True, data_only=False)
for sheet in wb.worksheets:
    for excel_row, values in enumerate(sheet.iter_rows(values_only=True), start=1):
        parts = [cell_text(value) for value in values if cell_text(value)]
        if excel_row == 1 or len(parts) < 2:
            continue
        label = parts[0][:240]
        condition = "; ".join(parts)
        node = f"QA_HIST_{safe(sheet.title)}_{excel_row:03d}"
        action = "Проверить временную согласованность, способ замера, datum и соседние события; пометить выброс либо направить инженеру по разработке."
        individual("17_qaqc_rules", node, "HistoricalQAQCRule", label)
        add_l("17_qaqc_rules", node, "conditionText", condition)
        add_l("17_qaqc_rules", node, "actionText", action)
        add_l("17_qaqc_rules", node, "qualityRuleText", f"Правило QAQC: [{condition}] -> [{action}] -> [{stage_nodes['S11']}]")
        add_l("17_qaqc_rules", node, "evidenceStatus", "curated historical data heuristic")
        add_l("17_qaqc_rules", node, "criterionVersion", "QCV_1960_1975..QCV_2025_PLUS; select by effective date")
        add_i("17_qaqc_rules", node, "governedBy", "QCV_2025_PLUS")
        add_l("17_qaqc_rules", node, "sourcePath", str(problems_path.relative_to(ROOT)))
        add_l("17_qaqc_rules", node, "sourceRow", excel_row, datatype=XSD + "integer")
        add_i("17_qaqc_rules", node, "targetsNode", stage_nodes["S11"])
        add_i("17_qaqc_rules", node, "hasEscalationRoute", "ESCALATE_S11")
        add_i("17_qaqc_rules", stage_nodes["S11"], "hasRule", node)
        qaqc_rows.append({"node": node, "id": f"{sheet.title}:{excel_row}", "rule_type": "HistoricalQAQCRule", "stage": "S11", "condition": condition, "action": action, "target": stage_nodes["S11"], "state": "curated heuristic", "source_row": str(excel_row)})
wb.close()


# ---------------------------------------------------------------------------
# Software bridge: abstract operations, versioned bindings and tNavigator calls
# ---------------------------------------------------------------------------

SOFTWARE = [
    ("SW_TNAV", "tNavigator", "SWVER_TNAV_2026_2", "2026.2 / July 2026 manuals", "RFD internal manuals; verify installed license and build"),
    ("SW_PETREL", "Petrel", "SWVER_PETREL_2024_8", "2024.8 reference capability profile", "SLB documented workflows; exact Ocean API binding is project plug-in dependent"),
    ("SW_GEOVATION", "GeoVation", "SWVER_GEOVATION_2026", "current capability profile 2026", "Viridien documented seismic processing/imaging platform; batch-module locator requires local installation"),
]
for sw, name, version, version_text, status in SOFTWARE:
    individual("18_software_bridge", sw, "SoftwareProduct", name)
    add_l("18_software_bridge", sw, "softwareName", name)
    individual("18_software_bridge", version, "SoftwareVersion", f"{name}: {version_text}")
    add_l("18_software_bridge", version, "softwareVersionText", version_text)
    add_l("18_software_bridge", version, "bindingStatus", status)
    add_i("18_software_bridge", version, "isVersionOf", sw)

individual("18_software_bridge", "POLICY_SOFTWARE_BINDING_EVOLUTION", "DeprecationPolicy", "Политика версий и устаревания программных привязок", description="Абстрактная операция стабильна; реализация привязана к продукту, версии, лицензии и locator. Перед вызовом агент проверяет capability, сигнатуру и units; deprecated binding не удаляется, а получает замену и альтернативу.")

software_mapping_rows: list[dict[str, str]] = []
operation_by_stage: dict[str, list[str]] = defaultdict(list)
for row in activity_rows:
    code = row["substage"].split("_")[1]
    if not row["task"].startswith("Собрать"):
        continue
    op_id = "OP_" + row["substage"]
    operation_by_stage[code].append(op_id)
    individual("18_software_bridge", op_id, "AbstractSoftwareOperation", row["substage_label"])
    add_i("18_software_bridge", op_id, "targetsNode", row["substage"])
    add_i("18_software_bridge", row["method"], "implementsOperation", op_id)
    add_i("18_software_bridge", op_id, "governedBy", "POLICY_SOFTWARE_BINDING_EVOLUTION")

    targets = [("SW_TNAV", "SWVER_TNAV_2026_2", "workflow/API candidate resolved by capability registry", "conceptual binding; exact callable selected from manual index")]
    if code not in {"S01", "S02", "S18"}:
        targets.append(("SW_PETREL", "SWVER_PETREL_2024_8", "Ocean/workflow command resolved by installed plug-in", "documented product workflow; API locator requires project implementation"))
    if code in {"S06", "S07"}:
        targets.append(("SW_GEOVATION", "SWVER_GEOVATION_2026", "batch processing/imaging module resolved by local catalogue", "documented product capability; module locator requires local installation"))
    for sw, version, locator, status in targets:
        bid = f"BIND_{safe(op_id)}_{safe(sw)}"
        individual("18_software_bridge", bid, "SoftwareBinding", f"Привязка {row['substage_label']} -> {sw}")
        add_i("18_software_bridge", bid, "implementsOperation", op_id)
        add_i("18_software_bridge", bid, "targetsSoftware", sw)
        add_i("18_software_bridge", bid, "targetsVersion", version)
        add_l("18_software_bridge", bid, "implementationLocator", locator)
        add_l("18_software_bridge", bid, "bindingStatus", status)
        add_l("18_software_bridge", bid, "deprecationStatus", "active; reevaluate on version change")
        software_mapping_rows.append({"method": row["substage_label"], "operation_node": op_id, "binding_node": bid, "target_software": sw, "target_version": version, "locator": locator, "status": status, "mapping_text": f"Метод: [{row['substage_label']}] -> [{op_id}] -> [{sw}/{version}]"})

# Software alternatives are explicit and navigable.
bindings_by_op: dict[str, list[str]] = defaultdict(list)
for mapping in software_mapping_rows:
    bindings_by_op[mapping["operation_node"]].append(mapping["binding_node"])
for binding_ids in bindings_by_op.values():
    for source in binding_ids:
        for alternative in binding_ids:
            if source != alternative:
                add_i("18_software_bridge", source, "hasAlternativeBinding", alternative)


def tnav_stage_for_function(name: str) -> str:
    value = name.lower()
    mapping = [
        ("S13", ["geomech", "pore_pressure", "stress", "fracture"]),
        ("S11", ["ipr", "welltest", "pressure", "rate_transient", "well_interference"]),
        ("S12", ["pvt", "fluid", "saturation", "relperm", "capillary"]),
        ("S15", ["grid", "upscale", "volume", "cell", "property"]),
        ("S14", ["variogram", "kriging", "populate", "interpol", "random"]),
        ("S10", ["facies", "object", "channel", "polygon"]),
        ("S08", ["well_log", "las", "curve", "petroph"]),
        ("S07", ["surface", "horizon", "fault", "depth"]),
        ("S06", ["seismic", "velocity", "attribute"]),
        ("S17", ["history", "forecast", "simulat", "well_control", "schedule"]),
        ("S02", ["project", "import", "export", "open", "copy", "create"]),
    ]
    for code, words in mapping:
        if any(word.strip() in value for word in words):
            return code
    return "S18"


def tnav_operation_for_function(name: str, stage: str) -> tuple[str, str]:
    """Resolve a stable abstract operation from lexical function evidence."""
    value = name.lower()
    semantic_targets = [
        (["import", "load", "read"], "S02", 0), (["export", "save", "write"], "S02", 8),
        (["fault"], "S07", 0), (["horizon", "surface", "depth"], "S07", 6),
        (["seismic", "velocity", "attribute"], "S06", 8),
        (["facies", "polygon", "channel", "object"], "S10", 8),
        (["log", "curve", "las", "petroph"], "S08", 3),
        (["pvt", "fluid", "eos"], "S12", 1), (["saturation", "relperm", "capillary"], "S12", 7),
        (["pressure", "ipr", "welltest", "interference"], "S11", 3),
        (["geomech", "stress", "pore_pressure"], "S13", 10),
        (["variogram", "kriging", "interpol", "populate", "random"], "S14", 8),
        (["grid", "cell", "upscale", "volume"], "S15", 5),
        (["history", "forecast", "simulate", "schedule", "well_control"], "S17", 7),
    ]
    for words, target_stage, index in semantic_targets:
        if any(word in value for word in words) and operation_by_stage.get(target_stage):
            options = operation_by_stage[target_stage]
            return options[min(index, len(options) - 1)], "lexical-domain mapping"
    options = operation_by_stage.get(stage) or operation_by_stage["S18"]
    return options[hashlib.sha1(name.encode("utf-8")).digest()[0] % len(options)], "stage fallback; specialist verification required"


tnav_function_rows: list[dict[str, str]] = []
tnav_csv = CORPUS_DIR / "tnav_function_candidates.csv"
with tnav_csv.open("r", encoding="utf-8-sig", newline="") as handle:
    for record in csv.DictReader(handle):
        name = cell_text(record.get("function_name"))
        if not name:
            continue
        manual = cell_text(record.get("manual"))
        pages = cell_text(record.get("pages"))
        stage = tnav_stage_for_function(name)
        node = "TNAV_CALL_" + safe(name, 100)
        individual("11_tnavigator", node, "TNavigatorCallableCandidate", name)
        add_l("11_tnavigator", node, "apiName", name)
        add_l("11_tnavigator", node, "manualPage", pages)
        add_l("11_tnavigator", node, "evidenceStatus", "detected in vendor manual; verify signature, context, license and installed version before execution")
        add_l("11_tnavigator", node, "bindingStatus", "callable candidate")
        add_i("11_tnavigator", node, "detectedInManual", "SOURCE_MANUAL_" + safe(manual))
        add_i("11_tnavigator", node, "supportsProcessDomain", stage_nodes[stage])
        op_id, mapping_basis = tnav_operation_for_function(name, stage)
        add_i("11_tnavigator", node, "implementsOperation", op_id)
        add_l("11_tnavigator", node, "mappingBasis", mapping_basis)
        tnav_function_rows.append({"node": node, "function": name, "manual": manual, "pages": pages, "stage": stage, "operation": op_id, "mapping_basis": mapping_basis, "status": "candidate; verify installed version"})

# Named manual resources support candidate calls.
for manual in sorted({row["manual"] for row in tnav_function_rows}):
    mid = "SOURCE_MANUAL_" + safe(manual)
    individual("19_sources_alignments", mid, "SourceArtifact", manual)
    add_l("19_sources_alignments", mid, "sourcePath", f"Справочные материалы/Мануалы_тнав/{manual}")
    add_l("19_sources_alignments", mid, "evidenceStatus", "local vendor documentation indexed page-by-page")


# ---------------------------------------------------------------------------
# Evidence corpus, exact duplicates and official semantic/industry standards
# ---------------------------------------------------------------------------

THEME_MODULE = {
    "qaqc": "17_qaqc_rules", "regional_play": "13_regional_play",
    "stratigraphy": "03_stratigraphy", "sedimentology_facies": "05_facies",
    "seismic_structural": "04_structural", "petrophysics_logs": "06_petrophysics",
    "geostatistics_grid": "07_geostatistics", "pressure_welltest": "14_pressure_welltest",
    "geomechanics": "15_geomechanics", "uncertainty": "09_uncertainty",
    "dynamic_history": "10_dynamic_handoff", "software_tnavigator": "11_tnavigator",
    "software_petrel": "18_software_bridge", "standards_units": "19_sources_alignments",
}
source_rows: list[dict[str, str]] = []
hash_canonical: dict[str, str] = {}
corpus_csv = CORPUS_DIR / "corpus_inventory.csv"
with corpus_csv.open("r", encoding="utf-8-sig", newline="") as handle:
    for record in csv.DictReader(handle):
        sid = record["source_id"]
        label = Path(record["relative_path"]).name
        individual("19_sources_alignments", sid, "SourceArtifact", label)
        add_l("19_sources_alignments", sid, "sourcePath", record["relative_path"])
        add_l("19_sources_alignments", sid, "sourceSha256", record["sha256"])
        add_l("19_sources_alignments", sid, "sourceTheme", record["primary_theme"])
        add_l("19_sources_alignments", sid, "sourceModified", record["modified_utc"])
        add_l("19_sources_alignments", sid, "evidenceStatus", record["extract_status"])
        add_l("19_sources_alignments", sid, "fileExtension", record["extension"])
        add_l("19_sources_alignments", sid, "byteSize", record["bytes"], datatype=XSD + "integer")
        canonical = hash_canonical.get(record["sha256"])
        if canonical:
            add_i("19_sources_alignments", sid, "exactDuplicateOf", canonical)
        else:
            hash_canonical[record["sha256"]] = sid
        target_module = THEME_MODULE.get(record["primary_theme"], "19_sources_alignments")
        add_i("19_sources_alignments", sid, "supportsModule", ONT + target_module)
        source_rows.append({"node": sid, "path": record["relative_path"], "sha256": record["sha256"], "theme": record["primary_theme"], "status": record["extract_status"], "canonical": canonical or sid})

WEB_SOURCES = [
    ("STD_OWL2", "W3C OWL 2 Web Ontology Language", "https://www.w3.org/TR/owl2-overview/", "OWL 2 Recommendation", "formal ontology semantics"),
    ("STD_PROVO", "W3C PROV-O", "https://www.w3.org/TR/prov-o/", "W3C Recommendation", "provenance and revision history"),
    ("STD_SHACL12", "W3C SHACL 1.2 Core", "https://www.w3.org/TR/shacl12-core/", "Recommendation 2026-08", "machine validation constraints"),
    ("STD_GEOSPARQL11", "OGC GeoSPARQL 1.1", "https://www.ogc.org/standards/geosparql/", "1.1", "spatial features, geometries and spatial query"),
    ("STD_RESQML22", "Energistics RESQML", "https://energistics.org/resqml-developers-users", "2.2 with Energistics common 2.3", "earth model interchange and EPC packaging"),
    ("STD_WITSML21", "Energistics WITSML", "https://energistics.org/witsml-developers-users", "2.1; ETP 1.2", "well and drilling data exchange"),
    ("STD_SEGY21", "SEG-Y Data Exchange Format", "https://seg.org/wp-content/uploads/2025/11/seg_y_rev2_1-oct2023.pdf", "Revision 2.1", "seismic data exchange"),
    ("STD_LAS20", "CWLS Log ASCII Standard", "https://www.cwls.org/products", "LAS 2.0 reference", "well-log curve exchange"),
    ("STD_ISO19115_1", "ISO 19115-1 Geographic information — Metadata", "https://www.iso.org/standard/53798.html", "ISO 19115-1:2014", "dataset identity, extent, quality and temporal metadata"),
    ("STD_QUDT", "QUDT Units and Quantity Kinds", "https://www.qudt.org/catalog/qudt-catalog.html", "catalog 3.5.1 (2026-08)", "units and quantity semantics"),
    ("STD_OSDU", "OSDU Data Platform data model", "https://community.opengroup.org/groups/osdu/platform/-/wikis/OSDU-Data-Platform-Data-Loading-Quick-Start-Guide", "versioned schemas", "master data, work products, components and datasets"),
    ("STD_PRMS", "SPE Petroleum Resources Management System", "https://jpt.spe.org/2018-prms-update-completed", "PRMS 2018 and 2022 application guidance", "resource classification and uncertainty"),
    ("SRC_PETREL", "SLB Petrel subsurface software features", "https://www.slb.com/products-and-services/delivering-digital-at-scale/software/petrel-subsurface-software/petrel-features", "capability profile accessed 2026-09", "geology, geophysics, geomechanics and uncertainty workflows"),
    ("SRC_OCEAN", "SLB Ocean software development framework", "https://www.slb.com/products-and-services/delivering-digital-at-scale/software/ocean", "capability profile accessed 2026-09", "Petrel extension interface"),
    ("SRC_GEOVATION", "Viridien GeoVation seismic imaging platform", "https://www.viridiengroup.com/expertise/subsurface-imaging/geovation", "capability profile accessed 2026-09", "2D/3D/4D seismic processing, imaging and QC"),
]
for sid, label, url, version, purpose in WEB_SOURCES:
    individual("19_sources_alignments", sid, "ExternalKnowledgeResource", label, description=purpose)
    add_l("19_sources_alignments", sid, "sourceUrl", url)
    add_l("19_sources_alignments", sid, "version", version)
    add_l("19_sources_alignments", sid, "evidenceStatus", "official primary source")
    source_rows.append({"node": sid, "path": url, "sha256": "", "theme": "official_standard_or_vendor", "status": "official primary source", "canonical": sid})

# Alignment statements remain loose to avoid importing very large external ontologies.
for local, external in [
    ("ParameterDefinition", QUDT + "Quantity"), ("Region", GEO + "Feature"),
    ("Field", GEO + "Feature"), ("Well", GEO + "Feature"),
    ("SourceArtifact", PROV + "Entity"), ("ProcessStage", PROV + "Activity"),
]:
    add_i("19_sources_alignments", local, RDFS + "subClassOf", external)


# ---------------------------------------------------------------------------
# BDI agent knowledge: preserve v3 rules and add a decision gate at each substage
# ---------------------------------------------------------------------------

old_bdi_path = V3_DIR / "bdi_knowledge" / "BDI_DecisionOntology_AllInOne.rdf"
for line in old_bdi_path.read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.startswith(f"<{OLD_BDI_ONT}"):
        continue
    mapped = line.replace(OLD_BDI_BASE, BDI_BASE).replace(V3_ONT, ONT).replace(V3_BASE, BASE)
    graphs["20_agent_knowledge"].add(mapped)

for code, label, vtype in [
    ("input_completeness", "Полнота обязательных входов", "fraction"),
    ("critical_qc_passed", "Критические проверки пройдены", "boolean"),
    ("contradiction_count", "Число нерешённых междисциплинарных противоречий", "integer"),
    ("conceptual_uncertainty", "Уровень концептуальной неопределённости", "ordinal"),
    ("data_density", "Достаточность пространственных данных", "ordinal"),
    ("new_vintage_impact", "Влияние нового винтажа", "ordinal"),
    ("acceptance_criteria_met_v4", "Выполнение актуальной версии критериев приёмки", "boolean"),
]:
    bid = BDI_BASE + "BELIEF_EV_" + safe(code)
    individual("20_agent_knowledge", bid, BDI_BASE + "BeliefVariable", label)
    add_l("20_agent_knowledge", bid, BDI_BASE + "beliefCode", code)
    add_l("20_agent_knowledge", bid, BDI_BASE + "variableType", vtype)

decision_rows: list[dict[str, str]] = []
assumption_rows: list[dict[str, str]] = []
for stage_order, (stage_code, module, stage_label, _legacy, _lc, substage_text) in enumerate(STAGES, start=1):
    kb = BDI_BASE + "KB_EV_" + stage_code
    individual("20_agent_knowledge", kb, BDI_BASE + "AgentKnowledgeBase", f"База знаний агента: {stage_label}")
    add_i("20_agent_knowledge", kb, "supportsProcessDomain", stage_nodes[stage_code])
    role_id = "ROLE_" + ESCALATION_ROUTES.get(stage_code, ("MODEL_CUSTODIAN", ""))[0]
    add_i("20_agent_knowledge", kb, BDI_BASE + "ownedByRole", role_id)

    assumption = f"ASSUMPTION_REGISTER_{stage_code}"
    uncertainty = f"UNCERTAINTY_REGISTER_{stage_code}"
    individual("20_agent_knowledge", assumption, "AssumptionRegisterEntry", f"Реестр допущений: {stage_label}", description="Хранит формулировку, автора, дату, область применимости, основание, влияние, срок пересмотра и опровергающее свидетельство.")
    individual("20_agent_knowledge", uncertainty, "UncertaintyRegisterEntry", f"Реестр неопределённостей: {stage_label}", description="Хранит источник, aleatory/epistemic класс, распределение, корреляции, влияние на решения, план снижения и posterior update.")
    add_i("20_agent_knowledge", kb, "hasAssumptionEntry", assumption)
    add_i("20_agent_knowledge", kb, "hasUncertaintyEntry", uncertainty)
    assumption_rows.extend([
        {"stage": stage_code, "register": assumption, "kind": "assumption", "required_fields": "statement; owner; created_at; valid_scope; evidence; impact; review_date; falsifier; status"},
        {"stage": stage_code, "register": uncertainty, "kind": "uncertainty", "required_fields": "source; aleatory_or_epistemic; distribution; correlation; decision_impact; mitigation; posterior; status"},
    ])

    substages = substage_text.split("|")
    for sub_index, sub_label in enumerate(substages, start=1):
        sub_id = f"SUB_{stage_code}_{sub_index:02d}"
        branch = BDI_BASE + f"BR_EV_{stage_code}_{sub_index:02d}"
        individual("20_agent_knowledge", branch, BDI_BASE + "BranchPoint", f"Решение о переходе: {sub_label}")
        add_i("20_agent_knowledge", kb, BDI_BASE + "hasBranchPoint", branch)
        add_i("20_agent_knowledge", branch, BDI_BASE + "governsActivity", sub_id)
        add_l("20_agent_knowledge", branch, BDI_BASE + "hitPolicy", "PRIORITY")
        rules = [
            (10, "critical_qc_passed = false", "Заблокировать переход; выполнить corrective action из QAQC и вернуть владельцу данных", "Исправить критическую ошибку", True, "S02", "Невалидные данные не должны переходить дальше."),
            (20, "input_completeness < project_minimum", "Запросить недостающие обязательные данные либо утвердить документированное исключение", "Закрыть пробел входных данных", True, "S02", "Полнота оценивается относительно цели модели, а не абсолютным списком."),
            (30, "contradiction_count > 0", "Создать contradiction case, сохранить обе версии и эскалировать затронутым дисциплинам", "Разрешить междисциплинарное противоречие", True, stage_code, "Противоречие нельзя скрывать усреднением."),
            (40, "new_vintage_impact = high", "Выполнить impact analysis и перестроить только затронутую зависимостями часть ансамбля", "Обновить эволюционную модель", False, "S18", "Новый винтаж должен сохранять происхождение и различия версий."),
            (50, "conceptual_uncertainty = high ANY data_density = sparse", "Построить альтернативные концепции и стохастический/analog-informed ensemble; запросить экспертный review", "Сохранить множественность допустимых моделей", True, stage_code, "Одна детерминированная модель не представляет model-form uncertainty."),
            (60, "critical_qc_passed = true ALL contradiction_count = 0 ALL acceptance_criteria_met_v4 = true", "Зафиксировать evidence package, параметры, версию критерия и передать следующему подэтапу", "Продолжить процесс", False, stage_code, "Переход воспроизводим и аудируем."),
            (99, "otherwise", "Остановить автоматическое решение и запросить владельца домена", "Ручное разрешение неполного состояния", True, stage_code, "Fallback обязателен для неполных или неизвестных belief values."),
        ]
        for priority, guard, outcome, intention, approval, return_stage, rationale in rules:
            if priority == 40 and (stage_code in {"S01", "S02", "S03", "S04", "S05"} or (stage_code == "S06" and sub_index <= 10)):
                continue
            rid = BDI_BASE + f"RULE_EV_{stage_code}_{sub_index:02d}_{priority:02d}"
            individual("20_agent_knowledge", rid, BDI_BASE + "DecisionRule", f"{sub_label}: {intention}")
            add_i("20_agent_knowledge", branch, BDI_BASE + "hasRule", rid)
            add_l("20_agent_knowledge", rid, BDI_BASE + "priority", priority, datatype=XSD + "integer")
            add_l("20_agent_knowledge", rid, BDI_BASE + "guardExpression", guard)
            add_l("20_agent_knowledge", rid, BDI_BASE + "outcomeText", outcome)
            add_l("20_agent_knowledge", rid, BDI_BASE + "intentionText", intention)
            add_l("20_agent_knowledge", rid, BDI_BASE + "requiresHumanApproval", approval, datatype=XSD + "boolean")
            add_l("20_agent_knowledge", rid, BDI_BASE + "rationale", rationale)
            add_i("20_agent_knowledge", rid, BDI_BASE + "returnActivity", stage_nodes[return_stage])
            add_i("20_agent_knowledge", rid, "hasEscalationRoute", "ESCALATE_" + stage_code)
            decision_rows.append({"knowledge_base": kb.rsplit("#", 1)[-1], "branch_id": branch.rsplit("#", 1)[-1], "branch": f"Решение о переходе: {sub_label}", "activity": sub_id, "hit_policy": "PRIORITY", "rule_id": rid.rsplit("#", 1)[-1], "priority": str(priority), "guard": guard, "outcome": outcome, "intention": intention, "requires_human_approval": str(approval).lower(), "return_stage": return_stage, "rationale": rationale})

# Link the proven v3 specialist decision bases to the expanded v4 stages.
for old_kb, stages in {
    "KB_GOVERNANCE_DATA": ["S01", "S02"], "KB_STRAT_STRUCTURE": ["S04", "S06", "S07"],
    "KB_FACIES": ["S05", "S10"], "KB_PETRO": ["S08", "S09", "S12"],
    "KB_GEOSTAT": ["S14"], "KB_GRID_VOL": ["S15"], "KB_UQ_ASSURANCE": ["S16"],
    "KB_DYNAMIC": ["S11", "S17"], "KB_TNAV_EXECUTION": ["S18"],
}.items():
    for stage in stages:
        add_i("20_agent_knowledge", BDI_BASE + old_kb, "supportsProcessDomain", stage_nodes[stage])


# ---------------------------------------------------------------------------
# Serialization, human-readable catalogs and machine validation assets
# ---------------------------------------------------------------------------

def ontology_header(module: str, title: str) -> set[str]:
    subject = ONT + module
    result = {
        f"{iri(subject)} {iri(RDF + 'type')} {iri(OWL + 'Ontology')} .",
        f"{iri(subject)} {iri(RDFS + 'label')} {literal(title, lang='ru')} .",
        f"{iri(subject)} {iri(OWL + 'versionInfo')} {literal('4.0.0')} .",
        f"{iri(subject)} {iri(DCT + 'modified')} {literal(date.today().isoformat(), datatype=XSD + 'date')} .",
    }
    for imported in IMPORTS[module]:
        result.add(f"{iri(subject)} {iri(OWL + 'imports')} {iri(ONT + imported)} .")
    return result


def write_nt(path: Path, triples: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sorted(triples)) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


MODULE_DIR.mkdir(parents=True, exist_ok=True)
all_triples: set[str] = set()
for module, title in MODULES.items():
    module_triples = set(graphs[module]) | ontology_header(module, title)
    write_nt(MODULE_DIR / f"{module}.rdf", module_triples)
    all_triples.update(module_triples)

all_header = {
    f"{iri(ONT + 'all')} {iri(RDF + 'type')} {iri(OWL + 'Ontology')} .",
    f"{iri(ONT + 'all')} {iri(RDFS + 'label')} {literal('Эволюционная онтология комплексного геологического моделирования v4', lang='ru')} .",
    f"{iri(ONT + 'all')} {iri(OWL + 'versionInfo')} {literal('4.0.0')} .",
    f"{iri(ONT + 'all')} {iri(PROV + 'wasRevisionOf')} {iri(V3_ONT + 'all')} .",
}
write_nt(HERE / "GeoModelingEvolutionOntology_v4_AllInOne.rdf", all_triples | all_header)

# Separate agent ontology is a first-class deliverable, while remaining imported by the main ontology.
bdi_dir = HERE / "bdi_knowledge"
bdi_module_dir = bdi_dir / "modules"
bdi_triples = set(graphs["20_agent_knowledge"]) | ontology_header("20_agent_knowledge", MODULES["20_agent_knowledge"])
write_nt(bdi_module_dir / "20_agent_knowledge.rdf", bdi_triples)
write_nt(bdi_dir / "BDI_KnowledgeBase_v4_AllInOne.rdf", bdi_triples | {
    f"{iri(ONT + 'bdi-all')} {iri(RDF + 'type')} {iri(OWL + 'Ontology')} .",
    f"{iri(ONT + 'bdi-all')} {iri(OWL + 'imports')} {iri(ONT + '20_agent_knowledge')} .",
})

write_csv(HERE / "process_catalog.csv", activity_rows)
write_csv(HERE / "data_parameter_catalog.csv", parameter_rows)
write_csv(HERE / "qaqc_rules.csv", qaqc_rows)
write_csv(HERE / "tnavigator_functions.csv", tnav_function_rows)
write_csv(HERE / "software_mappings.csv", software_mapping_rows)
write_csv(HERE / "source_register.csv", source_rows)
write_csv(bdi_dir / "decision_tables.csv", decision_rows)
write_csv(bdi_dir / "assumption_uncertainty_registers.csv", assumption_rows)

catalog_lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">']
for module in MODULES:
    catalog_lines.append(f'  <uri name="{xml_escape(ONT + module)}" uri="modules/{module}.rdf"/>')
catalog_lines.append('</catalog>')
(HERE / "catalog-v001.xml").write_text("\n".join(catalog_lines) + "\n", encoding="utf-8")

shacl_text = f'''@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix gm: <{BASE}> .
@prefix bdi: <{BDI_BASE}> .
@prefix xsd: <{XSD}> .

gm:ParameterDefinitionShape a sh:NodeShape ;
  sh:targetClass gm:ParameterDefinition ;
  sh:property [ sh:path gm:dataType ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:unitSymbolV4 ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:typicalRange ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:typicalUncertainty ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:hasTechnologyMetadataProfile ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:hasUncertaintyProfile ; sh:minCount 1 ] .

gm:QAQCRuleShape a sh:NodeShape ;
  sh:targetClass gm:QAQCRule ;
  sh:property [ sh:path gm:conditionText ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:actionText ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:targetsNode ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:hasEscalationRoute ; sh:minCount 1 ] .

gm:SoftwareBindingShape a sh:NodeShape ;
  sh:targetClass gm:SoftwareBinding ;
  sh:property [ sh:path gm:implementsOperation ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:targetsVersion ; sh:minCount 1 ] ;
  sh:property [ sh:path gm:bindingStatus ; sh:minCount 1 ] .

gm:BDIRuleShape a sh:NodeShape ;
  sh:targetClass bdi:DecisionRule ;
  sh:property [ sh:path bdi:guardExpression ; sh:minCount 1 ] ;
  sh:property [ sh:path bdi:outcomeText ; sh:minCount 1 ] ;
  sh:property [ sh:path bdi:requiresHumanApproval ; sh:minCount 1 ] .
'''
(HERE / "GeoModelingEvolutionOntology_v4_SHACL.ttl").write_text(shacl_text, encoding="utf-8")

queries = f'''PREFIX gm: <{BASE}>
PREFIX bdi: <{BDI_BASE}>
PREFIX rdfs: <{RDFS}>

# 1. Drill down from a process stage to substages and handoff parameters.
SELECT ?stage ?substage ?label ?parameter WHERE {{
  ?stage a gm:ProcessStage ; gm:hasSubstage ?substage .
  ?substage rdfs:label ?label .
  OPTIONAL {{ ?activity gm:refinesSubstage ?substage ; gm:passesParameter ?parameter }}
}}

# 2. QA/QC rules, criteria and escalation routes for an ontology node.
SELECT ?rule ?condition ?action ?route WHERE {{
  ?rule gm:targetsNode ?target ; gm:conditionText ?condition ; gm:actionText ?action ; gm:hasEscalationRoute ?route .
}}

# 3. Versioned software implementation alternatives for an abstract operation.
SELECT ?operation ?binding ?software ?version ?locator ?status WHERE {{
  ?binding a gm:SoftwareBinding ; gm:implementsOperation ?operation ; gm:targetsSoftware ?software ;
    gm:targetsVersion ?version ; gm:implementationLocator ?locator ; gm:bindingStatus ?status .
}}

# 4. Ordered BDI rules and their explicit human-approval requirements.
SELECT ?branch ?rule ?priority ?guard ?outcome ?approval WHERE {{
  ?branch a bdi:BranchPoint ; bdi:hasRule ?rule .
  ?rule bdi:priority ?priority ; bdi:guardExpression ?guard ; bdi:outcomeText ?outcome ; bdi:requiresHumanApproval ?approval .
}} ORDER BY ?branch ?priority
'''
(HERE / "GeoModelingEvolutionOntology_v4_queries.rq").write_text(queries, encoding="utf-8")

iri_pattern = re.compile(r"<([^>]+)>")
local_resources: set[str] = set()
for triple in all_triples | all_header:
    for found in iri_pattern.findall(triple):
        if found.startswith(BASE) or found.startswith(BDI_BASE):
            local_resources.add(found)
typed_local_nodes = {
    iri_pattern.findall(triple)[0]
    for triple in all_triples | all_header
    if f"{iri(RDF + 'type')}" in triple
    and iri_pattern.findall(triple)
    and iri_pattern.findall(triple)[0].startswith((BASE, BDI_BASE))
}

class_counts = {}
for class_name in ["ProcessStage", "ProcessSubstage", "AtomicModelingTask", "ParameterDefinition", "QAQCRule", "HistoricalQAQCRule", "SoftwareBinding", "TNavigatorCallableCandidate", "SourceArtifact"]:
    marker = f"{iri(RDF + 'type')} {iri(class_name)}"
    class_counts[class_name] = sum(1 for line in all_triples if marker in line)
class_counts["BDI_BranchPoint"] = sum(1 for line in all_triples if f"{iri(RDF + 'type')} {iri(BDI_BASE + 'BranchPoint')}" in line)
class_counts["BDI_DecisionRule"] = sum(1 for line in all_triples if f"{iri(RDF + 'type')} {iri(BDI_BASE + 'DecisionRule')}" in line)

manifest = {
    "ontology": "GeoModelingEvolutionOntology_v4",
    "version": "4.0.0",
    "generated": date.today().isoformat(),
    "modules": len(MODULES),
    "triples_all_in_one": len(all_triples | all_header),
    "distinct_local_nodes": len(typed_local_nodes),
    "distinct_local_resources_including_predicates": len(local_resources),
    "process_stages": len(STAGES),
    "process_substages": sum(len(row[5].split("|")) for row in STAGES),
    "atomic_process_activities": len(activity_rows),
    "data_parameter_definitions": len(parameter_rows),
    "qaqc_rules_imported": len(qaqc_rows),
    "tnavigator_callable_candidates": len(tnav_function_rows),
    "software_bindings": len(software_mapping_rows),
    "local_and_web_sources": len(source_rows),
    "bdi_transition_rules_added": len(decision_rows),
    "class_counts": class_counts,
    "node_target": "8000..20000",
    "warnings": [
        "Typical ranges are anomaly-screening defaults, not universal acceptance criteria.",
        "tNavigator callable candidates require signature, license and installed-version verification before execution.",
        "Petrel/Ocean and GeoVation bindings are capability-level unless a local API/module locator is provided.",
        "QA/QC checklist evidenceStatus is preserved; candidate rules are not silently promoted to verified rules."
    ],
}
(HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False, indent=2))
