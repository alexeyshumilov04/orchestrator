(function () {
  "use strict";

  const NS = {
    rdf: "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    rdfs: "http://www.w3.org/2000/01/rdf-schema#",
    dct: "http://purl.org/dc/terms/",
    owl: "http://www.w3.org/2002/07/owl#",
    gm: "https://example.org/geomodel/evolution/v4#",
    bdi: "https://example.org/geomodel/evolution/v4/bdi#"
  };

  const P = {
    type: NS.rdf + "type",
    label: NS.rdfs + "label",
    description: NS.dct + "description",
    title: NS.dct + "title",
    hasStage: NS.gm + "hasStage",
    hasSubstage: NS.gm + "hasSubstage",
    hasActivity: NS.gm + "hasActivity",
    belongsToStage: NS.gm + "belongsToStage",
    belongsToKnowledgeBase: NS.bdi + "belongsToKnowledgeBase",
    hasBranchPoint: NS.bdi + "hasBranchPoint",
    hasRule: NS.bdi + "hasRule",
    appliesToActivity: NS.bdi + "appliesToActivity",
    governsActivity: NS.bdi + "governsActivity",
    order: NS.gm + "order"
  };

  const CATEGORY = {
    process: { label: "Процесс", color: "--amber" },
    stage: { label: "Стадия", color: "--accent" },
    substage: { label: "Подэтап", color: "--cyan" },
    activity: { label: "Действие", color: "--green" },
    artifact: { label: "Артефакт", color: "--blue" },
    method: { label: "Метод", color: "--purple" },
    parameterObject: { label: "Объект параметров", color: "--yellow" },
    parameter: { label: "Параметр", color: "--yellow" },
    function: { label: "Функция tNavigator", color: "--accent" },
    software: { label: "ПО / привязка", color: "--cyan" },
    transition: { label: "Условие перехода", color: "--orange" },
    contract: { label: "Контракт данных", color: "--blue" },
    lifecycle: { label: "Стадия жизненного цикла", color: "--amber" },
    knowledgeBase: { label: "База знаний BDI", color: "--cyan" },
    branch: { label: "Точка ветвления", color: "--orange" },
    rule: { label: "Правило решения", color: "--lime" },
    conditionGroup: { label: "Группа условий", color: "--faint" },
    condition: { label: "Условие", color: "--yellow" },
    outcome: { label: "Результат решения", color: "--green" },
    belief: { label: "Убеждение агента", color: "--blue" },
    desire: { label: "Цель агента", color: "--purple" },
    intention: { label: "Намерение агента", color: "--rose" },
    evidence: { label: "Требование к evidence", color: "--amber" },
    guard: { label: "Ограничение исполнения", color: "--red" },
    trace: { label: "Трасса решения", color: "--muted" },
    qc: { label: "Контроль качества", color: "--rose" },
    uncertainty: { label: "Неопределённость", color: "--red" },
    practice: { label: "Лучшая практика", color: "--green" },
    failure: { label: "Типовая ошибка", color: "--red" },
    role: { label: "Роль", color: "--blue" },
    agentProfile: { label: "Профиль BDI-агента", color: "--cyan" },
    runtimeModule: { label: "Модуль TypicalAgentRuntime", color: "--purple" },
    capability: { label: "Capability", color: "--green" },
    handoff: { label: "Межагентный контракт", color: "--orange" },
    autonomy: { label: "Политика автономии", color: "--rose" },
    source: { label: "Источник", color: "--muted" },
    geology: { label: "Геологическое понятие", color: "--amber" },
    class: { label: "Класс", color: "--faint" },
    property: { label: "Отношение", color: "--faint" },
    other: { label: "Сущность", color: "--muted" }
  };

  const TYPE_TO_CATEGORY = new Map([
    ["ModelingProcess", "process"], ["IntegratedGeomodelingProcess", "process"], ["ProcessStage", "stage"],
    ["ProcessSubstage", "substage"], ["AtomicModelingTask", "activity"],
    ["DecisionGate", "activity"], ["Dataset", "artifact"], ["Artifact", "artifact"],
    ["Interpretation", "artifact"], ["Representation", "artifact"], ["Model", "artifact"],
    ["Grid", "artifact"], ["Realization", "artifact"], ["Report", "artifact"], ["Register", "artifact"],
    ["Method", "method"], ["ModelingParameter", "parameter"], ["FunctionParameter", "parameter"],
    ["Parameter", "parameter"], ["ParameterDefinition", "parameter"], ["TNavigatorParameterObject", "parameterObject"],
    ["TNavigatorFunction", "function"], ["TNavigatorCallableCandidate", "function"],
    ["QualityControl", "qc"], ["AcceptanceCriterion", "qc"], ["QAQCRule", "qc"],
    ["CrossDisciplineRule", "qc"], ["HistoricalQAQCRule", "qc"], ["QualityCriterionVersion", "qc"],
    ["SoftwareProduct", "software"], ["SoftwareVersion", "software"], ["SoftwareBinding", "software"],
    ["AbstractSoftwareOperation", "software"], ["TransitionCondition", "transition"], ["DataContract", "contract"],
    ["LifecycleStage", "lifecycle"], ["TechnologyEra", "lifecycle"],
    ["AgentKnowledgeBase", "knowledgeBase"], ["BranchPoint", "branch"], ["DecisionRule", "rule"],
    ["ConditionGroup", "conditionGroup"], ["AtomicCondition", "condition"],
    ["DecisionOutcome", "outcome"], ["BeliefVariable", "belief"], ["Desire", "desire"],
    ["Intention", "intention"], ["EvidenceRequirement", "evidence"],
    ["ExecutionGuard", "guard"], ["DecisionTrace", "trace"],
    ["DomainAgentProfile", "agentProfile"], ["TypicalAgentRuntime", "agentProfile"],
    ["RuntimeModule", "runtimeModule"], ["Capability", "capability"],
    ["HandoffContract", "handoff"], ["AutonomyPolicy", "autonomy"], ["OperationMode", "autonomy"],
    ["Uncertainty", "uncertainty"], ["Risk", "uncertainty"], ["BestPractice", "practice"],
    ["FailureMode", "failure"], ["Role", "role"], ["Source", "source"], ["Standard", "source"],
    ["LiteratureSource", "source"], ["ManualSource", "source"], ["DiagramSource", "source"],
    ["GeologicFeature", "geology"], ["GeologicUnit", "geology"], ["GeologicStructure", "geology"],
    ["DepositionalEnvironment", "geology"], ["DepositionalElement", "geology"], ["Facies", "geology"],
    ["FaciesAssociation", "geology"], ["RockType", "geology"], ["PetrophysicalRockType", "geology"],
    ["HydraulicFlowUnit", "geology"], ["Property", "geology"], ["Class", "class"],
    ["ObjectProperty", "property"], ["DatatypeProperty", "property"]
  ]);

  const PREDICATE_LABELS = {
    hasStage: "Стадии", hasSubstage: "Подэтапы", hasActivity: "Действия", belongsToStage: "Стадия",
    precedes: "Следующий шаг", dependsOn: "Зависит от", hasInput: "Входы",
    hasOutput: "Результаты", performedBy: "Роли", usesMethod: "Методы",
    usesSoftware: "Модули ПО", automatedBy: "Функции tNavigator",
    automatesActivity: "Автоматизирует действия", hasQualityControl: "Контроль качества",
    hasAcceptanceCriterion: "Критерии приёмки", addressesUncertainty: "Неопределённости",
    hasFailureMode: "Типовые ошибки", mitigatedBy: "Снижается практикой",
    implementsPractice: "Лучшие практики", supportedBy: "Источники",
    supportsModule: "Поддерживает модули", derivedFrom: "Произведено из",
    hasScenario: "Сценарии", hasRealization: "Реализации", representsFeature: "Представляет объект",
    interpretsFeature: "Интерпретирует объект", hasProperty: "Свойства",
    hasCoordinateReferenceSystem: "Система координат", hasUnit: "Единица измерения",
    hasLicenseFeature: "Лицензии", hasParameterObject: "Объекты параметров",
    hasParameter: "Параметры", closeToLegacyTerm: "Термин предыдущей версии",
    equivalentClass: "Эквивалентный класс", closeMatch: "Близкое соответствие", seeAlso: "См. также",
    hasKnowledgeBase: "Базы знаний", hasBranchPoint: "Точки ветвления",
    belongsToKnowledgeBase: "База знаний", hasRule: "Правила решения",
    hasFallbackRule: "Безопасное правило по умолчанию", hasConditionGroup: "Группа условий",
    hasCondition: "Условия", evaluatesBelief: "Проверяемые убеждения",
    concludesOutcome: "Результат", setsIntention: "Намерение", supportsDesire: "Цель агента",
    appliesToActivity: "Точка процесса", advancesToActivity: "Следующий шаг",
    returnsToActivity: "Возврат к шагу", selectsMethod: "Выбранный метод",
    selectsFunction: "Вызов tNavigator", requiresEvidence: "Обязательные свидетельства",
    evidenceArtifact: "Артефакт-свидетельство", assignedRole: "Роли агента",
    hasExecutionGuard: "Ограничения исполнения"
    ,hasTransitionCondition: "Условия перехода", hasDataContract: "Контракты данных",
    passesParameter: "Передаваемые параметры", hasQualityProfile: "Профиль качества",
    hasTechnologyMetadataProfile: "Метаданные технологии", hasUncertaintyProfile: "Профиль неопределённости",
    hasRule: "Правила", targetsNode: "Целевой узел", hasEscalationRoute: "Маршрут эскалации",
    implementsOperation: "Абстрактная операция", targetsSoftware: "Целевое ПО", targetsVersion: "Версия ПО",
    hasAlternativeBinding: "Альтернативные реализации", detectedInManual: "Руководство",
    supportsProcessDomain: "Домен процесса", governsActivity: "Управляет подэтапом",
    usesRuntime: "Использует runtime", belongsToAgentGroup: "Группа агентов",
    ownsProcessStage: "Владеет стадией", usesKnowledgeBase: "Использует БЗ",
    hasRuntimeModule: "Модули runtime", feedsModule: "Передаёт следующему модулю",
    invokesCapability: "Вызывает capability", hasHandoffContract: "Контракты передачи",
    handoffFrom: "Передаёт агент", handoffTo: "Принимает агент", requiresGate: "Контрольный gate"
  };

  const INVERSE_LABELS = {
    hasInput: "Используется как вход", hasOutput: "Создаётся действиями", performedBy: "Действия роли",
    usesMethod: "Применяется в действиях", usesSoftware: "Используется в действиях",
    automatedBy: "Автоматизируемые действия", automatesActivity: "Автоматизируется функциями",
    hasQualityControl: "Проверяет действия", addressesUncertainty: "Учитывается в действиях",
    implementsPractice: "Реализуется действиями", supportedBy: "Поддерживает знания",
    hasParameter: "Параметр для", hasParameterObject: "Используется функциями",
    hasLicenseFeature: "Требуется функциями", belongsToStage: "Содержит действия",
    hasActivity: "Принадлежит стадии", hasStage: "Принадлежит процессу",
    hasKnowledgeBase: "Назначено ролям", hasBranchPoint: "Входит в базу знаний",
    belongsToKnowledgeBase: "Содержит точки ветвления", hasRule: "Правило точки ветвления",
    hasFallbackRule: "Является fallback для", hasConditionGroup: "Условия правила",
    hasCondition: "Входит в группу", evaluatesBelief: "Проверяется условиями",
    concludesOutcome: "Формируется правилами", setsIntention: "Устанавливается результатом или правилом",
    supportsDesire: "Поддерживается базами знаний", appliesToActivity: "Имеет решения BDI",
    advancesToActivity: "Выбрано как следующий шаг", returnsToActivity: "Выбрано для возврата",
    selectsMethod: "Выбирается правилами", selectsFunction: "Вызывается правилами",
    requiresEvidence: "Требуется точками ветвления", evidenceArtifact: "Указан как evidence",
    assignedRole: "Использует базу знаний", hasExecutionGuard: "Ограничивает базу исполнения"
  };

  const LITERAL_LABELS = {
    order: "Порядок", apiName: "API", manualSection: "Раздел руководства", manualPage: "Страницы руководства",
    manualVersion: "Версия руководства", licenseCode: "Код лицензии", executionMode: "Режим запуска",
    localPath: "Локальный источник", sourceLocator: "Место в источнике", status: "Статус",
    seed: "Seed", version: "Версия", criterionText: "Критерий",
    rationale: "Обоснование", evidenceLevel: "Уровень свидетельства", notation: "Код",
    parameterType: "Тип", unitSymbol: "Единица", defaultValue: "По умолчанию",
    allowedRange: "Допустимый диапазон", created: "Создано", format: "Формат",
    versionInfo: "Версия онтологии", questionText: "Вопрос решения", ruleCode: "Код правила",
    rulePriority: "Приоритет", hitPolicy: "Hit policy", logicalOperator: "Логика группы",
    comparator: "Сравнение", expectedValue: "Ожидаемое значение", guardExpression: "Критерий",
    outcomeCode: "Код результата", intentionCode: "Код намерения", beliefCode: "Код убеждения",
    variableType: "Тип переменной", allowedValues: "Допустимые значения", isDefault: "Fallback",
    requiresHumanApproval: "Подтверждение эксперта", missingDataPolicy: "Если данных нет",
    conflictPolicy: "При конфликте", completenessStatus: "Полнота таблицы",
    traceTemplate: "Трасса решения", expectedArtifactCode: "Ожидаемый артефакт",
    requestedFunctionCode: "Запрошенная функция", dataType: "Тип данных", unitSymbolV4: "Единица",
    typicalRange: "Типовой диапазон", typicalUncertainty: "Типовая погрешность",
    uncertaintyModel: "Модель неопределённости", normalizationRequirement: "Нормировка",
    acquisitionYearRequired: "Обязателен год получения", equipmentMetadataRequired: "Обязательны данные оборудования",
    technologyGenerationRequired: "Обязательно поколение технологии", conditionText: "Условие QA/QC",
    actionText: "Действие QA/QC", qualityRuleText: "Формализованное правило", criterionVersion: "Версия критерия",
    evidenceStatus: "Статус доказательства", bindingStatus: "Статус привязки", implementationLocator: "Точка вызова",
    deprecationStatus: "Статус устаревания", mappingBasis: "Основание сопоставления", outcomeText: "Результат",
    intentionText: "Намерение", priority: "Приоритет", transitionExpression: "Условие перехода",
    iterationExpression: "Условие итерации", sourcePath: "Локальный источник", sourceTheme: "Тема источника"
  };

  const RELATION_ORDER = [
    "hasStage", "hasSubstage", "hasActivity", "belongsToStage", "precedes", "hasInput", "hasOutput",
    "usesMethod", "hasParameterObject", "hasParameter", "performedBy", "hasQualityControl",
    "hasAcceptanceCriterion", "addressesUncertainty", "implementsPractice", "hasFailureMode",
    "automatedBy", "automatesActivity", "usesSoftware", "hasLicenseFeature", "supportedBy",
    "derivedFrom", "hasScenario", "hasRealization", "representsFeature", "interpretsFeature",
    "hasProperty", "hasCoordinateReferenceSystem", "hasUnit", "supportsModule", "seeAlso",
    "closeMatch", "equivalentClass", "closeToLegacyTerm", "hasKnowledgeBase", "hasBranchPoint",
    "belongsToKnowledgeBase", "appliesToActivity", "hasRule", "hasFallbackRule", "hasConditionGroup",
    "hasCondition", "evaluatesBelief", "concludesOutcome", "setsIntention", "supportsDesire",
    "requiresEvidence", "evidenceArtifact", "assignedRole", "advancesToActivity", "returnsToActivity",
    "selectsMethod", "selectsFunction", "hasExecutionGuard", "hasTransitionCondition", "hasDataContract",
    "passesParameter", "hasQualityProfile", "hasTechnologyMetadataProfile", "hasUncertaintyProfile",
    "targetsNode", "hasEscalationRoute", "implementsOperation", "targetsSoftware", "targetsVersion",
    "hasAlternativeBinding", "detectedInManual", "supportsProcessDomain", "governsActivity"
  ];

  const GRAPH_PREDICATES = new Set([
    "hasStage", "hasSubstage", "hasActivity", "belongsToStage", "precedes", "dependsOn", "hasInput", "hasOutput",
    "performedBy", "usesMethod", "usesSoftware", "automatedBy", "automatesActivity",
    "hasQualityControl", "hasAcceptanceCriterion", "addressesUncertainty", "hasFailureMode",
    "mitigatedBy", "implementsPractice", "supportedBy", "hasParameterObject", "hasParameter",
    "hasLicenseFeature", "hasScenario", "hasRealization", "representsFeature", "interpretsFeature",
    "hasKnowledgeBase", "hasBranchPoint", "belongsToKnowledgeBase", "appliesToActivity", "hasRule",
    "hasFallbackRule", "hasConditionGroup", "hasCondition", "evaluatesBelief", "concludesOutcome",
    "setsIntention", "supportsDesire", "requiresEvidence", "evidenceArtifact", "assignedRole",
    "advancesToActivity", "returnsToActivity", "selectsMethod", "selectsFunction", "hasExecutionGuard",
    "hasTransitionCondition", "hasDataContract", "passesParameter", "targetsNode", "hasEscalationRoute",
    "implementsOperation", "targetsSoftware", "targetsVersion", "hasAlternativeBinding", "supportsProcessDomain", "governsActivity"
  ]);

  const els = {
    datasetName: document.getElementById("dataset-name"), search: document.getElementById("global-search"),
    searchResults: document.getElementById("search-results"), fileInput: document.getElementById("rdf-files"),
    loadFiles: document.getElementById("load-files"), loadDefault: document.getElementById("load-default"),
    tabs: Array.from(document.querySelectorAll(".view-tab")), graphControl: document.getElementById("graph-control"),
    graphDepth: document.getElementById("graph-depth"), graphFit: document.getElementById("graph-fit"),
    stats: document.getElementById("top-stats"), tree: document.getElementById("ontology-tree"),
    collapseTree: document.getElementById("collapse-tree"), breadcrumbs: document.getElementById("breadcrumbs"),
    historyBack: document.getElementById("history-back"), showGraph: document.getElementById("show-in-graph"),
    workspace: document.getElementById("workspace"), view: document.getElementById("view-root"),
    details: document.getElementById("detail-pane"), drop: document.getElementById("drop-overlay"),
    toast: document.getElementById("toast")
  };

  let model = null;
  let currentView = "process";
  let selectedId = null;
  let currentStageId = null;
  let currentKnowledgeBaseId = null;
  let currentBranchId = null;
  let selectionHistory = [];
  let expandedStages = new Set();
  let catalogFilter = null;
  let searchCursor = 0;
  let graphState = null;
  let toastTimer = null;

  function localName(iri) {
    const clean = String(iri || "").replace(/[\/#]+$/, "");
    const at = Math.max(clean.lastIndexOf("#"), clean.lastIndexOf("/"));
    try { return decodeURIComponent(clean.slice(at + 1)); } catch (_) { return clean.slice(at + 1); }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function decodeLiteral(raw) {
    const expanded = raw.replace(/\\U([0-9A-Fa-f]{8})/g, function (_, hex) {
      return String.fromCodePoint(parseInt(hex, 16));
    });
    try { return JSON.parse('"' + expanded + '"'); }
    catch (_) {
      return expanded.replace(/\\n/g, "\n").replace(/\\r/g, "\r").replace(/\\t/g, "\t")
        .replace(/\\"/g, '"').replace(/\\\\/g, "\\");
    }
  }

  function parseNTriples(text, sourceName) {
    const triples = [];
    const lines = String(text || "").split(/\r?\n/);
    const triplePattern = /^<([^>]*)>\s+<([^>]*)>\s+(<[^>]*>|"(?:[^"\\]|\\.)*"(?:@[A-Za-z0-9-]+|\^\^<[^>]+>)?)\s+\.\s*$/;
    const literalPattern = /^"((?:[^"\\]|\\.)*)"(?:@([A-Za-z0-9-]+)|\^\^<([^>]+)>)?$/;
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index].trim();
      if (!line || line.startsWith("#")) continue;
      const match = line.match(triplePattern);
      if (!match) throw new Error(sourceName + ": строка " + (index + 1) + " не является N-Triples");
      const objectToken = match[3];
      if (objectToken.startsWith("<")) {
        triples.push({ s: match[1], p: match[2], o: objectToken.slice(1, -1), literal: false, source: sourceName });
      } else {
        const literal = objectToken.match(literalPattern);
        if (!literal) throw new Error(sourceName + ": не удалось прочитать литерал в строке " + (index + 1));
        triples.push({
          s: match[1], p: match[2], o: decodeLiteral(literal[1]), literal: true,
          lang: literal[2] || "", datatype: literal[3] || "", source: sourceName
        });
      }
    }
    return triples;
  }

  function buildModel(triples, name, files) {
    const unique = new Map();
    triples.forEach(function (t) {
      const key = [t.s, t.p, t.literal ? "L" : "I", t.o, t.lang || "", t.datatype || ""].join("\u001f");
      if (!unique.has(key)) unique.set(key, t);
    });
    const cleanTriples = Array.from(unique.values());
    const nodes = new Map();

    function ensure(id) {
      if (!nodes.has(id)) nodes.set(id, { id: id, outgoing: new Map(), incoming: new Map(), types: new Set(), labels: {} });
      return nodes.get(id);
    }

    cleanTriples.forEach(function (t) {
      const subject = ensure(t.s);
      if (!subject.outgoing.has(t.p)) subject.outgoing.set(t.p, []);
      subject.outgoing.get(t.p).push(t);
      if (!t.literal) {
        const object = ensure(t.o);
        if (!object.incoming.has(t.p)) object.incoming.set(t.p, []);
        object.incoming.get(t.p).push(t);
        if (t.p === P.type) subject.types.add(t.o);
      }
      if (t.p === P.label && t.literal) subject.labels[t.lang || ""] = t.o;
    });

    nodes.forEach(function (node) {
      node.label = node.labels.ru || node.labels.en || node.labels[""] || localName(node.id);
      node.category = categorize(node);
      node.searchText = [node.label, node.labels.en || "", localName(node.id),
        literalFirst(node, NS.gm + "apiName") || "", literalFirst(node, NS.bdi + "questionText") || "",
        literalFirst(node, NS.bdi + "guardExpression") || "", literalFirst(node, NS.bdi + "beliefCode") || "",
        literalFirst(node, NS.gm + "conditionText") || "", literalFirst(node, NS.gm + "actionText") || "",
        literalFirst(node, NS.gm + "parameterCode") || "", literalFirst(node, NS.gm + "implementationLocator") || ""]
        .join(" ").toLocaleLowerCase("ru");
    });

    const stages = Array.from(nodes.values()).filter(function (n) { return n.category === "stage" && n.id.includes("#EV_STAGE_"); }).sort(orderSort);
    const processes = Array.from(nodes.values()).filter(function (n) { return n.category === "process"; });
    const process = processes.find(function (n) { return n.id.includes("#PROCESS_GEO_MODEL_V4"); }) || processes[0] || null;
    const stageActivities = new Map();
    const stageSubstages = new Map();
    stages.forEach(function (stage) {
      const activityIds = iriValues(stage, P.hasActivity);
      const activities = activityIds.map(function (id) { return nodes.get(id); }).filter(Boolean).sort(orderSort);
      stageActivities.set(stage.id, activities);
      const substageIds = iriValues(stage, P.hasSubstage);
      stageSubstages.set(stage.id, substageIds.map(function (id) { return nodes.get(id); }).filter(Boolean).sort(orderSort));
    });
    Array.from(nodes.values()).filter(function (n) { return n.category === "activity"; }).forEach(function (activity) {
      const stageId = iriValues(activity, P.belongsToStage)[0];
      if (!stageId) return;
      const values = stageActivities.get(stageId) || [];
      if (!values.some(function (n) { return n.id === activity.id; })) values.push(activity);
      values.sort(orderSort);
      stageActivities.set(stageId, values);
    });

    const knowledgeBases = Array.from(nodes.values()).filter(function (n) { return n.category === "knowledgeBase"; })
      .sort(function (a, b) { return a.label.localeCompare(b.label, "ru"); });
    const kbBranches = new Map();
    knowledgeBases.forEach(function (kb) {
      const linked = iriValues(kb, P.hasBranchPoint).map(function (id) { return nodes.get(id); }).filter(Boolean);
      kbBranches.set(kb.id, linked.sort(function (a, b) { return a.label.localeCompare(b.label, "ru"); }));
    });
    Array.from(nodes.values()).filter(function (n) { return n.category === "branch"; }).forEach(function (branchNode) {
      const kbId = iriValues(branchNode, P.belongsToKnowledgeBase)[0];
      if (!kbId) return;
      const values = kbBranches.get(kbId) || [];
      if (!values.some(function (n) { return n.id === branchNode.id; })) values.push(branchNode);
      values.sort(function (a, b) { return a.label.localeCompare(b.label, "ru"); });
      kbBranches.set(kbId, values);
    });

    const counts = {};
    nodes.forEach(function (node) { counts[node.category] = (counts[node.category] || 0) + 1; });
    return { name: name, files: files, triples: cleanTriples, nodes: nodes, process: process, stages: stages,
      stageActivities: stageActivities, stageSubstages: stageSubstages, knowledgeBases: knowledgeBases, kbBranches: kbBranches, counts: counts };
  }

  function categorize(node) {
    const names = Array.from(node.types).map(localName);
    const priority = ["IntegratedGeomodelingProcess", "ModelingProcess", "ProcessStage", "ProcessSubstage", "AtomicModelingTask", "AgentKnowledgeBase", "BranchPoint", "DecisionRule",
      "ConditionGroup", "AtomicCondition", "DecisionOutcome", "BeliefVariable", "Desire", "Intention",
      "EvidenceRequirement", "ExecutionGuard", "DecisionTrace", "Activity", "TNavigatorCallableCandidate", "TNavigatorFunction", "TNavigatorParameterObject",
      "ParameterDefinition", "ModelingParameter", "FunctionParameter", "CrossDisciplineRule", "HistoricalQAQCRule", "QAQCRule", "QualityCriterionVersion", "QualityControl", "AcceptanceCriterion", "SoftwareBinding", "AbstractSoftwareOperation", "SoftwareVersion", "SoftwareProduct", "TransitionCondition", "DataContract", "LifecycleStage", "TechnologyEra", "Uncertainty", "BestPractice",
      "FailureMode", "Method", "Role", "LiteratureSource", "ManualSource", "DiagramSource", "Standard", "Source",
      "Dataset", "Interpretation", "Representation", "Model", "Grid", "Realization", "Report", "Register", "Artifact",
      "DepositionalEnvironment", "DepositionalElement", "FaciesAssociation", "Facies", "PetrophysicalRockType",
      "HydraulicFlowUnit", "RockType", "GeologicUnit", "GeologicStructure", "GeologicFeature", "Property",
      "ObjectProperty", "DatatypeProperty", "Class", "Parameter"];
    for (const type of priority) if (names.includes(type)) return TYPE_TO_CATEGORY.get(type) || "other";
    return "other";
  }

  function triplesFor(node, predicate) { return (node && node.outgoing.get(predicate)) || []; }
  function iriValues(node, predicate) { return triplesFor(node, predicate).filter(function (t) { return !t.literal; }).map(function (t) { return t.o; }); }
  function literalValues(node, predicate) { return triplesFor(node, predicate).filter(function (t) { return t.literal; }).map(function (t) { return t.o; }); }
  function literalFirst(node, predicate) { return literalValues(node, predicate)[0]; }
  function orderOf(node) { const value = Number(literalFirst(node, P.order)); return Number.isFinite(value) ? value : 99999; }
  function orderSort(a, b) { return orderOf(a) - orderOf(b) || a.label.localeCompare(b.label, "ru"); }
  function predicateLocal(iri) { return localName(iri); }

  function colorVar(category) { return CATEGORY[category] ? CATEGORY[category].color : CATEGORY.other.color; }
  function colorCss(category) { return "var(" + colorVar(category) + ")"; }
  function resolveColor(category) { return getComputedStyle(document.documentElement).getPropertyValue(colorVar(category)).trim() || "#93a7b8"; }
  function stageColor(index) {
    return ["var(--accent)", "var(--blue)", "var(--green)", "var(--purple)", "var(--amber)",
      "var(--rose)", "var(--yellow)", "var(--blue)", "var(--purple)", "var(--red)"][index % 10];
  }

  function showToast(message, isError) {
    clearTimeout(toastTimer);
    els.toast.textContent = message;
    els.toast.classList.toggle("is-error", Boolean(isError));
    els.toast.hidden = false;
    toastTimer = setTimeout(function () { els.toast.hidden = true; }, 4200);
  }

  function loadDefault() {
    try {
      const data = window.GM_DEFAULT_ONTOLOGY;
      if (!data || !data.ntriples) throw new Error("Встроенные данные не найдены");
      const triples = parseNTriples(data.ntriples, data.source || "встроенная онтология");
      activateModel(buildModel(triples, data.name || "GeoModelingEvolutionOntology v4", [data.source || "встроенная онтология"]));
    } catch (error) { showToast(error.message, true); }
  }

  function activateModel(nextModel) {
    model = nextModel;
    selectionHistory = [];
    expandedStages = new Set();
    selectedId = model.process ? model.process.id : (model.stages[0] ? model.stages[0].id : (model.nodes.values().next().value || {}).id);
    currentStageId = model.stages[0] ? model.stages[0].id : null;
    currentKnowledgeBaseId = model.knowledgeBases[0] ? model.knowledgeBases[0].id : null;
    currentBranchId = currentKnowledgeBaseId && (model.kbBranches.get(currentKnowledgeBaseId) || [])[0]
      ? model.kbBranches.get(currentKnowledgeBaseId)[0].id : null;
    if (currentStageId) expandedStages.add(currentStageId);
    els.datasetName.textContent = model.name;
    els.stats.textContent = model.triples.length.toLocaleString("ru-RU") + " триплетов · " + model.nodes.size.toLocaleString("ru-RU") + " узлов";
    renderTree();
    renderDetail();
    renderBreadcrumbs();
    setView(model.stages.length ? "process" : (model.knowledgeBases.length ? "decisions" : "catalog"));
    showToast("Загружено: " + model.triples.length.toLocaleString("ru-RU") + " триплетов из " + model.files.length + " файл(ов)");
  }

  async function loadFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    try {
      const batches = await Promise.all(files.map(async function (file) {
        return parseNTriples(await file.text(), file.name);
      }));
      const name = files.length === 1 ? files[0].name : "Связанный набор · " + files.length + " файлов";
      activateModel(buildModel([].concat.apply([], batches), name, files.map(function (f) { return f.name; })));
    } catch (error) { showToast(error.message, true); }
    finally { els.fileInput.value = ""; }
  }

  function setView(view) {
    currentView = view;
    els.tabs.forEach(function (tab) {
      const active = tab.dataset.view === view;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    els.graphControl.hidden = view !== "graph";
    els.view.classList.toggle("graph-mode", view === "graph");
    renderCurrentView();
  }

  function renderCurrentView() {
    if (!model) return;
    if (currentView !== "graph") disconnectGraph();
    if (currentView === "process") renderProcess();
    else if (currentView === "subprocess") renderSubprocess();
    else if (currentView === "decisions") renderDecisions();
    else if (currentView === "graph") renderGraph();
    else renderCatalog();
  }

  function decisionBranchForNode(node) {
    if (!node) return null;
    if (node.category === "branch") return node;
    function incomingSources(current, predicate, category) {
      return (current.incoming.get(predicate) || []).map(function (triple) { return model.nodes.get(triple.s); })
        .filter(function (candidate) { return candidate && (!category || candidate.category === category); });
    }
    if (node.category === "rule") return incomingSources(node, P.hasRule, "branch")[0] || null;
    if (node.category === "conditionGroup") {
      const rule = incomingSources(node, NS.bdi + "hasConditionGroup", "rule")[0];
      return rule ? decisionBranchForNode(rule) : null;
    }
    if (node.category === "condition") {
      const group = incomingSources(node, NS.bdi + "hasCondition", "conditionGroup")[0];
      return group ? decisionBranchForNode(group) : null;
    }
    if (node.category === "belief") {
      const condition = incomingSources(node, NS.bdi + "evaluatesBelief", "condition")[0];
      return condition ? decisionBranchForNode(condition) : null;
    }
    if (node.category === "outcome") {
      const rule = incomingSources(node, NS.bdi + "concludesOutcome", "rule")[0];
      return rule ? decisionBranchForNode(rule) : null;
    }
    if (node.category === "intention") {
      const rule = incomingSources(node, NS.bdi + "setsIntention", "rule")[0];
      return rule ? decisionBranchForNode(rule) : null;
    }
    if (node.category === "evidence") return incomingSources(node, NS.bdi + "requiresEvidence", "branch")[0] || null;
    return null;
  }

  function setSelected(id, options) {
    options = options || {};
    if (!model || !model.nodes.has(id)) return;
    if (selectedId && selectedId !== id && options.pushHistory !== false) selectionHistory.push(selectedId);
    selectedId = id;
    const node = model.nodes.get(id);
    const decisionBranch = decisionBranchForNode(node);
    if (decisionBranch) {
      currentBranchId = decisionBranch.id;
      const ownerKb = iriValues(decisionBranch, P.belongsToKnowledgeBase)[0];
      if (ownerKb) currentKnowledgeBaseId = ownerKb;
    }
    if (node.category === "stage") currentStageId = id;
    if (node.category === "substage") {
      const owner = (node.incoming.get(P.hasSubstage) || [])[0];
      if (owner) { currentStageId = owner.s; expandedStages.add(owner.s); }
    }
    if (node.category === "activity") {
      const stageId = iriValues(node, P.belongsToStage)[0];
      if (stageId) { currentStageId = stageId; expandedStages.add(stageId); }
    }
    if (node.category === "knowledgeBase") currentKnowledgeBaseId = id;
    if (node.category === "branch") {
      currentBranchId = id;
      const kbId = iriValues(node, P.belongsToKnowledgeBase)[0];
      if (kbId) currentKnowledgeBaseId = kbId;
    }
    els.historyBack.disabled = selectionHistory.length === 0;
    renderDetail();
    renderBreadcrumbs();
    renderTree();
    if (options.contextual) {
      if (node.category === "stage" || node.category === "substage" || node.category === "activity") setView("subprocess");
      else if (["knowledgeBase", "branch", "rule", "condition", "belief", "outcome", "intention"].includes(node.category)) setView("decisions");
      else setView("graph");
    } else renderCurrentView();
  }

  function renderTree() {
    if (!model) return;
    const processLabel = model.process ? model.process.label : model.name;
    let html = '<div class="tree-item">' + treeRow(model.process ? model.process.id : "", processLabel, "tree-root", model.stages.length, true) + '</div>';
    model.stages.forEach(function (stage, index) {
      const substages = iriValues(stage, P.hasSubstage).map(function (id) { return model.nodes.get(id); }).filter(Boolean);
      const expanded = expandedStages.has(stage.id);
      html += '<div class="tree-item" data-stage="' + escapeHtml(stage.id) + '">';
      html += treeRow(stage.id, (index + 1) + ". " + stage.label, "", substages.length, false, expanded);
      html += '<div class="tree-children"' + (expanded ? "" : " hidden") + '>';
      substages.forEach(function (substage, subIndex) {
        html += treeRow(substage.id, (subIndex + 1) + ". " + substage.label, "tree-activity", "", true);
      });
      html += "</div></div>";
    });
    html += '<div class="tree-section-title">Быстрый доступ</div>';
    ["knowledgeBase", "branch", "belief", "method", "parameter", "qc", "software", "function", "transition", "uncertainty", "source"].forEach(function (category) {
      const count = model.counts[category] || 0;
      if (!count) return;
      html += '<div class="tree-row"><span></span><button class="tree-select" type="button" data-catalog="' + category + '"><span class="tree-label">' + escapeHtml(CATEGORY[category].label) + '</span></button><span class="tree-count">' + count + '</span></div>';
    });
    els.tree.innerHTML = html;
  }

  function treeRow(id, label, extraClass, count, leaf, expanded) {
    const selected = id && selectedId === id;
    const toggle = leaf ? '<span></span>' : '<button class="tree-toggle" type="button" data-toggle="' + escapeHtml(id) + '" aria-label="Развернуть">' + (expanded ? "−" : "+") + "</button>";
    return '<div class="tree-row ' + extraClass + (selected ? ' is-selected' : '') + '">' + toggle +
      '<button class="tree-select" type="button" data-node="' + escapeHtml(id) + '"><span class="tree-label">' + escapeHtml(label) + '</span></button>' +
      '<span class="tree-count">' + escapeHtml(count) + '</span></div>';
  }

  function renderProcess() {
    const process = model.process;
    const stages = model.stages;
    const activityCount = stages.reduce(function (sum, stage) { return sum + (model.stageActivities.get(stage.id) || []).length; }, 0);
    const title = process ? process.label : "Процесс моделирования";
    const intro = process ? descriptionOf(process) : "Выберите стадию, чтобы перейти к её действиям и связанным знаниям.";
    let html = '<h1 class="view-title">' + escapeHtml(title) + '</h1>';
    if (intro) html += '<p class="view-intro">' + escapeHtml(intro) + '</p>';
    html += '<div class="process-summary"><span><b>' + stages.length + '</b> этапов</span><span><b>' + (model.counts.substage || 0) + '</b> подэтапов</span><span><b>' +(activityCount) + '</b> операций</span><span><b>' + (model.counts.branch || 0) + '</b> развилок BDI</span><span><b>' + (model.counts.qc || 0) + '</b> узлов QA/QC</span><span><b>' + (model.counts.parameter || 0) + '</b> параметров</span><span><b>' + (model.counts.function || 0) + '</b> функций tNavigator</span></div>';
    if (!stages.length) html += '<div class="empty-state"><strong>Стадии процесса не найдены</strong><span>Используйте граф или каталог для просмотра загруженного RDF.</span></div>';
    else {
      html += '<div class="stage-flow">';
      stages.forEach(function (stage, index) {
        const activities = model.stageActivities.get(stage.id) || [];
        const methods = relatedUnique(activities, NS.gm + "usesMethod");
        const functions = relatedUnique(activities, NS.gm + "automatedBy");
        const outputs = relatedUnique(activities, NS.gm + "hasOutput");
        html += '<button class="stage-card' + (selectedId === stage.id ? ' is-selected' : '') + '" type="button" data-stage-open="' + escapeHtml(stage.id) + '" style="--stage-color:' + stageColor(index) + '">';
        html += '<span class="stage-number">' + (index + 1) + '</span><span class="stage-main"><strong>' + escapeHtml(stage.label) + '</strong><span>' + escapeHtml(stagePreview(activities)) + '</span></span>';
        const substages = iriValues(stage, P.hasSubstage);
        html += '<span class="stage-metrics"><span><b>' + substages.length + '</b>подэтапов</span><span><b>' + activities.length + '</b>операций</span><span><b>' + methods.length + '</b>методов</span><span><b>' + outputs.length + '</b>выходов</span></span></button>';
      });
      html += "</div>";
    }
    els.view.innerHTML = html;
  }

  function relatedUnique(nodes, predicate) {
    const result = new Set();
    nodes.forEach(function (node) { iriValues(node, predicate).forEach(function (id) { result.add(id); }); });
    return Array.from(result);
  }

  function stagePreview(activities) {
    return activities.slice(0, 3).map(function (a) { return a.label; }).join(" · ") + (activities.length > 3 ? "…" : "");
  }

  function renderSubprocess() {
    let stage = currentStageId ? model.nodes.get(currentStageId) : model.stages[0];
    if (!stage || stage.category !== "stage") stage = model.stages[0];
    if (!stage) {
      els.view.innerHTML = '<div class="empty-state"><strong>Подпроцессы не найдены</strong></div>';
      return;
    }
    currentStageId = stage.id;
    const stageIndex = Math.max(0, model.stages.findIndex(function (s) { return s.id === stage.id; }));
    const substageIds = iriValues(stage, P.hasSubstage);
    const substages = substageIds.map(function (id) { return model.nodes.get(id); }).filter(Boolean);
    let html = '<div class="subprocess-header" style="--stage-color:' + stageColor(stageIndex) + '"><span class="stage-index">' + (stageIndex + 1) + '</span><div><span class="eyebrow">Этап → подэтап → операция</span><h1 class="view-title">' + escapeHtml(stage.label) + '</h1><p class="view-intro">Раскрывайте подэтапы до атомарных операций; справа доступны входы, выходы, методы, переходы, параметры, QA/QC и программные вызовы.</p></div></div>';
    html += '<div class="substage-flow" style="--stage-color:' + stageColor(stageIndex) + '">';
    substages.forEach(function (substage, subIndex) {
      const activities = iriValues(substage, P.hasActivity).map(function (id) { return model.nodes.get(id); }).filter(Boolean);
      const branches = (substage.incoming.get(P.governsActivity) || []).map(function (triple) { return model.nodes.get(triple.s); }).filter(Boolean);
      html += '<section class="substage-group"><button class="substage-card' + (selectedId === substage.id ? ' is-selected' : '') + '" type="button" data-node="' + escapeHtml(substage.id) + '"><span class="substage-index">' + (subIndex + 1) + '</span><span><strong>' + escapeHtml(substage.label) + '</strong><small>' + activities.length + ' атомарных операций · ' + branches.length + ' decision gate</small></span></button>';
      html += '<div class="activity-flow">';
      activities.forEach(function (activity, activityIndex) {
        const methods = iriValues(activity, NS.gm + "usesMethod").length;
        const transitions = iriValues(activity, NS.gm + "hasTransitionCondition").length;
        html += '<button class="activity-card' + (selectedId === activity.id ? ' is-selected' : '') + '" type="button" data-node="' + escapeHtml(activity.id) + '">';
        html += '<span class="activity-order">' + (activityIndex + 1) + '</span><span class="activity-main"><strong>' + escapeHtml(activity.label) + '</strong><span class="activity-meta"><span>' + methods + ' метод</span><span>' + transitions + ' переход</span></span></span></button>';
      });
      html += '</div></section>';
    });
    html += "</div>";
    els.view.innerHTML = html;
    requestAnimationFrame(function () {
      const selected = els.view.querySelector('.activity-card.is-selected');
      if (selected) selected.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }

  function relationNodes(node, predicate) {
    return iriValues(node, predicate).map(function (id) { return model.nodes.get(id); }).filter(Boolean);
  }

  function rulePriority(node) {
    const value = Number(literalFirst(node, NS.bdi + "rulePriority") || literalFirst(node, NS.bdi + "priority"));
    return Number.isFinite(value) ? value : 99999;
  }

  function ruleConditions(rule) {
    const result = [];
    relationNodes(rule, NS.bdi + "hasConditionGroup").forEach(function (group) {
      const operator = literalFirst(group, NS.bdi + "logicalOperator") || "ALL";
      relationNodes(group, NS.bdi + "hasCondition").forEach(function (condition) {
        const belief = relationNodes(condition, NS.bdi + "evaluatesBelief")[0];
        result.push({
          id: condition.id,
          beliefId: belief ? belief.id : condition.id,
          label: belief ? belief.label : condition.label,
          operator: operator,
          comparator: literalFirst(condition, NS.bdi + "comparator") || "",
          expected: literalFirst(condition, NS.bdi + "expectedValue") || "",
          unit: literalFirst(condition, NS.bdi + "unitSymbol") || ""
        });
      });
    });
    return result;
  }

  function decisionActionLabels(rule) {
    const definitions = [
      [NS.bdi + "selectsMethod", "Метод"], [NS.bdi + "selectsFunction", "tNavigator"],
      [NS.bdi + "advancesToActivity", "Далее"], [NS.bdi + "returnsToActivity", "Возврат"]
    ];
    const result = [];
    definitions.forEach(function (entry) {
      relationNodes(rule, entry[0]).forEach(function (node) { result.push(entry[1] + ": " + node.label); });
    });
    const requested = literalFirst(rule, NS.bdi + "requestedFunctionCode");
    if (requested) result.push("tNavigator: " + requested);
    return result;
  }

  function renderDecisions() {
    if (!model.knowledgeBases.length) {
      els.view.innerHTML = '<div class="empty-state"><strong>Базы знаний BDI не найдены</strong><span>Загрузите BDI_DecisionOntology_AllInOne.rdf вместе с процессной онтологией.</span></div>';
      return;
    }
    let kb = currentKnowledgeBaseId ? model.nodes.get(currentKnowledgeBaseId) : model.knowledgeBases[0];
    if (!kb || kb.category !== "knowledgeBase") kb = model.knowledgeBases[0];
    currentKnowledgeBaseId = kb.id;
    const branches = model.kbBranches.get(kb.id) || [];
    let selectedBranch = currentBranchId ? model.nodes.get(currentBranchId) : branches[0];
    if (!selectedBranch || selectedBranch.category !== "branch" || !branches.some(function (item) { return item.id === selectedBranch.id; })) selectedBranch = branches[0];
    if (selectedBranch) currentBranchId = selectedBranch.id;

    let html = '<div class="decision-heading"><div><span class="eyebrow">BDI knowledge runtime</span><h1 class="view-title">Правила автономных решений</h1><p class="view-intro">Выберите базу знаний и точку ветвления. Правила выполняются сверху вниз по PRIORITY; серый fallback срабатывает при неполных или конфликтующих данных.</p></div>';
    html += '<div class="decision-summary"><span><b>' + (model.counts.knowledgeBase || 0) + '</b> баз</span><span><b>' + (model.counts.branch || 0) + '</b> развилок</span><span><b>' + (model.counts.rule || 0) + '</b> правил</span><span><b>' + (model.counts.belief || 0) + '</b> убеждений</span></div></div>';
    html += '<div class="kb-tabs" role="tablist" aria-label="Базы знаний агентов">';
    model.knowledgeBases.forEach(function (item) {
      const count = (model.kbBranches.get(item.id) || []).length;
      html += '<button type="button" class="kb-tab' + (item.id === kb.id ? ' is-active' : '') + '" data-kb-open="' + escapeHtml(item.id) + '"><span>' + escapeHtml(item.label.replace(/^База знаний (агента |петрофизического агента)?/i, "")) + '</span><b>' + count + '</b></button>';
    });
    html += '</div>';

    if (!selectedBranch) {
      html += '<div class="empty-state"><strong>В этой базе нет точек ветвления</strong></div>';
      els.view.innerHTML = html;
      return;
    }

    html += '<div class="decision-layout"><aside class="branch-list"><div class="branch-list-title"><span>' + escapeHtml(kb.label) + '</span><b>' + branches.length + '</b></div>';
    branches.forEach(function (item, index) {
      const activity = relationNodes(item, NS.bdi + "appliesToActivity")[0] || relationNodes(item, NS.bdi + "governsActivity")[0];
      html += '<button type="button" class="branch-button' + (item.id === selectedBranch.id ? ' is-active' : '') + '" data-branch-open="' + escapeHtml(item.id) + '"><span class="branch-index">' + (index + 1) + '</span><span><strong>' + escapeHtml(item.label) + '</strong><small>' + escapeHtml(activity ? activity.label : "Без привязки к процессу") + '</small></span></button>';
    });
    html += '</aside><section class="decision-table-panel">';

    const question = literalFirst(selectedBranch, NS.bdi + "questionText") || descriptionOf(selectedBranch);
    const hitPolicy = literalFirst(selectedBranch, NS.bdi + "hitPolicy") || "PRIORITY";
    const missingPolicy = literalFirst(selectedBranch, NS.bdi + "missingDataPolicy") || "";
    const conflictPolicy = literalFirst(selectedBranch, NS.bdi + "conflictPolicy") || "";
    const activity = relationNodes(selectedBranch, NS.bdi + "appliesToActivity")[0] || relationNodes(selectedBranch, NS.bdi + "governsActivity")[0];
    const evidence = relationNodes(selectedBranch, NS.bdi + "requiresEvidence");
    const rules = relationNodes(selectedBranch, NS.bdi + "hasRule").sort(function (a, b) { return rulePriority(a) - rulePriority(b); });

    html += '<div class="decision-title-row"><div><span class="decision-context">' + escapeHtml(activity ? activity.label : "Точка процесса не задана") + '</span><h2>' + escapeHtml(selectedBranch.label) + '</h2><p>' + escapeHtml(question) + '</p></div><button type="button" class="icon-button" data-node="' + escapeHtml(selectedBranch.id) + '">Карточка узла</button></div>';
    html += '<div class="policy-strip"><span><b>' + escapeHtml(hitPolicy) + '</b> первое истинное правило</span><span><b>Нет данных</b> ' + escapeHtml(missingPolicy) + '</span><span><b>Конфликт</b> ' + escapeHtml(conflictPolicy) + '</span></div>';
    if (evidence.length) {
      html += '<div class="evidence-row"><span>Нужно evidence</span>';
      evidence.forEach(function (item) { html += '<button type="button" data-node="' + escapeHtml(item.id) + '">' + escapeHtml(item.label) + '</button>'; });
      html += '</div>';
    }

    html += '<div class="decision-rules"><div class="decision-rule-head"><span>Приоритет</span><span>Критерии (beliefs)</span><span>Результат и намерение</span></div>';
    rules.forEach(function (rule) {
      const guardText = literalFirst(rule, NS.bdi + "guardExpression") || "";
      const isDefault = String(literalFirst(rule, NS.bdi + "isDefault")) === "true" || guardText === "otherwise" || rulePriority(rule) >= 99;
      const human = String(literalFirst(rule, NS.bdi + "requiresHumanApproval")) === "true";
      const outcome = relationNodes(rule, NS.bdi + "concludesOutcome")[0];
      const intention = relationNodes(rule, NS.bdi + "setsIntention")[0];
      const conditions = ruleConditions(rule);
      const outcomeText = outcome ? outcome.label : (literalFirst(rule, NS.bdi + "outcomeText") || "Результат не задан");
      const intentionText = intention ? intention.label : (literalFirst(rule, NS.bdi + "intentionText") || "");
      const actions = decisionActionLabels(rule);
      html += '<article class="decision-rule' + (isDefault ? ' is-fallback' : '') + (human ? ' needs-human' : '') + '">';
      html += '<button type="button" class="rule-priority" data-node="' + escapeHtml(rule.id) + '"><b>' + (isDefault ? '∞' : rulePriority(rule)) + '</b><span>' + escapeHtml(literalFirst(rule, NS.bdi + "ruleCode") || localName(rule.id)) + '</span>' + (human ? '<em>эксперт</em>' : '') + '</button>';
      html += '<div class="condition-stack">';
      if (isDefault) html += '<div class="fallback-condition"><strong>Иначе</strong><span>Нет полного совпадения или evidence недостаточно</span></div>';
      if (!conditions.length && guardText && !isDefault) html += '<div class="condition-chip static"><span>Guard expression</span><code>' + escapeHtml(guardText) + '</code></div>';
      conditions.forEach(function (condition, index) {
        if (index > 0) html += '<span class="logic-token">' + escapeHtml(condition.operator === "ANY" ? "ИЛИ" : "И") + '</span>';
        html += '<button type="button" class="condition-chip" data-node="' + escapeHtml(condition.beliefId) + '"><span>' + escapeHtml(condition.label) + '</span><code>' + escapeHtml(condition.comparator + " " + condition.expected + (condition.unit ? " " + condition.unit : "")) + '</code></button>';
      });
      html += '</div><div class="rule-result"><strong>' + escapeHtml(outcomeText) + '</strong><span>' + escapeHtml(intentionText) + '</span>';
      if (actions.length) html += '<div class="rule-actions">' + actions.map(function (action) { return '<code>' + escapeHtml(action) + '</code>'; }).join("") + '</div>';
      html += '</div></article>';
    });
    html += '</div></section></div>';
    els.view.innerHTML = html;
  }

  function renderCatalog() {
    const groups = ["knowledgeBase", "branch", "rule", "belief", "intention", "outcome", "evidence", "guard",
      "lifecycle", "stage", "substage", "activity", "transition", "contract", "artifact", "method",
      "parameterObject", "parameter", "qc", "software", "function", "uncertainty",
      "practice", "failure", "role", "geology", "source"];
    const activeGroups = catalogFilter ? groups.filter(function (g) { return g === catalogFilter; }) : groups;
    let html = '<h1 class="view-title">Каталог знаний</h1><p class="view-intro">Классы сущностей сгруппированы по назначению. Любой элемент открывает свои атрибуты и отношения.</p><div class="category-grid">';
    activeGroups.forEach(function (category) {
      const nodes = Array.from(model.nodes.values()).filter(function (node) { return node.category === category; }).sort(function (a, b) { return a.label.localeCompare(b.label, "ru"); });
      if (!nodes.length) return;
      const limit = catalogFilter ? Math.min(nodes.length, 500) : 12;
      html += '<section class="category-section"><div class="category-header"><h3>' + escapeHtml(CATEGORY[category].label) + '</h3><span>' + nodes.length + '</span></div><div class="catalog-list">';
      nodes.slice(0, limit).forEach(function (node) {
        html += '<button class="catalog-node" type="button" data-node="' + escapeHtml(node.id) + '" style="--node-color:' + colorCss(category) + '"><span class="catalog-dot"></span><span>' + escapeHtml(node.label) + '</span></button>';
      });
      if (!catalogFilter && nodes.length > limit) html += '<button class="show-more" type="button" data-catalog="' + category + '">Показать ' + CATEGORY[category].label + ' (' + nodes.length + ')</button>';
      if (catalogFilter && nodes.length > limit) html += '<div class="catalog-limit">Показаны первые 500 из ' + nodes.length + '. Для точного перехода используйте поиск.</div>';
      html += "</div></section>";
    });
    html += "</div>";
    if (catalogFilter) html = '<button class="icon-button" type="button" data-catalog-all>← Все категории</button>' + html;
    els.view.innerHTML = html;
  }

  function descriptionOf(node) {
    return literalFirst(node, P.description) || literalFirst(node, NS.bdi + "rationale") || literalFirst(node, NS.gm + "rationale") || "";
  }

  function renderDetail() {
    if (!model || !selectedId || !model.nodes.has(selectedId)) return;
    const node = model.nodes.get(selectedId);
    const category = CATEGORY[node.category] || CATEGORY.other;
    const typeNames = Array.from(node.types).map(function (id) { return model.nodes.get(id) ? model.nodes.get(id).label : localName(id); });
    let html = '<article class="detail-card" style="--node-color:' + colorCss(node.category) + '">';
    html += '<div class="type-line"><span class="type-badge">' + escapeHtml(category.label) + '</span>';
    typeNames.slice(0, 3).forEach(function (type) { html += '<span class="type-badge">' + escapeHtml(type) + '</span>'; });
    html += '</div><h2>' + escapeHtml(node.label) + '</h2><code class="detail-iri">' + escapeHtml(node.id) + '</code>';
    const description = descriptionOf(node);
    if (description) html += '<p class="detail-description">' + escapeHtml(description) + '</p>';
    html += '<div class="detail-actions"><button class="icon-button" type="button" data-focus-graph>Сеть узла</button>';
    if (node.category === "stage") html += '<button class="icon-button" type="button" data-open-stage="' + escapeHtml(node.id) + '">Открыть подпроцесс</button>';
    html += "</div>";

    const literals = collectLiterals(node);
    if (literals.length) {
      html += '<section class="detail-section"><h3>Атрибуты <span>' + literals.length + '</span></h3><table class="literal-table"><tbody>';
      literals.forEach(function (row) { html += '<tr><th>' + escapeHtml(row.label) + '</th><td>' + escapeHtml(row.value) + '</td></tr>'; });
      html += "</tbody></table></section>";
    }

    const groups = collectRelations(node);
    groups.forEach(function (group) {
      html += '<section class="detail-section"><h3>' + escapeHtml(group.title) + ' <span>' + group.items.length + '</span></h3><div class="relation-list">';
      group.items.slice(0, 60).forEach(function (item) {
        const target = model.nodes.get(item.id);
        const targetCategory = target ? target.category : "other";
        html += '<button class="relation-link" type="button" data-node="' + escapeHtml(item.id) + '" style="--node-color:' + colorCss(targetCategory) + '"><span class="relation-mark"></span><span class="relation-label">' + escapeHtml(target ? target.label : localName(item.id)) + '</span><span class="relation-kind">' + escapeHtml(target ? CATEGORY[targetCategory].label : "IRI") + '</span></button>';
      });
      if (group.items.length > 60) html += '<div class="relation-limit">Показаны 60 из ' + group.items.length + '. Используйте поиск для перехода к остальным узлам.</div>';
      html += "</div></section>";
    });
    html += "</article>";
    els.details.innerHTML = html;
  }

  function collectLiterals(node) {
    const rows = [];
    node.outgoing.forEach(function (triples, predicate) {
      const local = predicateLocal(predicate);
      if (predicate === P.label || predicate === P.description || predicate === P.title) return;
      triples.filter(function (t) { return t.literal; }).forEach(function (t) {
        rows.push({ key: local, label: LITERAL_LABELS[local] || (model.nodes.get(predicate) ? model.nodes.get(predicate).label : local), value: t.o });
      });
    });
    const order = Object.keys(LITERAL_LABELS);
    rows.sort(function (a, b) {
      const ai = order.indexOf(a.key), bi = order.indexOf(b.key);
      return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.label.localeCompare(b.label, "ru");
    });
    return rows;
  }

  function collectRelations(node) {
    const groups = [];
    const pairSeen = new Set();
    node.outgoing.forEach(function (triples, predicate) {
      const local = predicateLocal(predicate);
      if (!PREDICATE_LABELS[local]) return;
      const items = [];
      triples.filter(function (t) { return !t.literal; }).forEach(function (t) {
        const key = predicate + "|" + t.o;
        if (!pairSeen.has(key)) { pairSeen.add(key); items.push({ id: t.o }); }
      });
      if (items.length) groups.push({ predicate: local, title: PREDICATE_LABELS[local], items: sortRelationItems(items) });
    });
    node.incoming.forEach(function (triples, predicate) {
      const local = predicateLocal(predicate);
      if (!INVERSE_LABELS[local]) return;
      const reciprocal = local === "automatedBy" || local === "automatesActivity" || local === "hasActivity" || local === "belongsToStage";
      if (reciprocal && groups.some(function (g) { return (local === "automatedBy" && g.predicate === "automatesActivity") || (local === "automatesActivity" && g.predicate === "automatedBy") || (local === "hasActivity" && g.predicate === "belongsToStage") || (local === "belongsToStage" && g.predicate === "hasActivity"); })) return;
      const items = [];
      triples.forEach(function (t) {
        const key = "inverse:" + predicate + "|" + t.s;
        if (!pairSeen.has(key)) { pairSeen.add(key); items.push({ id: t.s }); }
      });
      if (items.length) groups.push({ predicate: "inverse:" + local, title: INVERSE_LABELS[local], items: sortRelationItems(items) });
    });
    groups.sort(function (a, b) {
      const ai = RELATION_ORDER.indexOf(a.predicate.replace("inverse:", ""));
      const bi = RELATION_ORDER.indexOf(b.predicate.replace("inverse:", ""));
      return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.title.localeCompare(b.title, "ru");
    });
    return groups;
  }

  function sortRelationItems(items) {
    return items.sort(function (a, b) {
      const an = model.nodes.get(a.id), bn = model.nodes.get(b.id);
      if (!an || !bn) return localName(a.id).localeCompare(localName(b.id), "ru");
      return orderSort(an, bn);
    });
  }

  function renderBreadcrumbs() {
    if (!model || !selectedId) return;
    const ids = [];
    if (model.process) ids.push(model.process.id);
    selectionHistory.slice(-3).forEach(function (id) { if (!ids.includes(id) && id !== selectedId) ids.push(id); });
    if (!ids.includes(selectedId)) ids.push(selectedId);
    els.breadcrumbs.innerHTML = ids.map(function (id, index) {
      const node = model.nodes.get(id);
      const button = '<button class="crumb" type="button" data-node="' + escapeHtml(id) + '">' + escapeHtml(node ? node.label : localName(id)) + '</button>';
      return (index ? '<span class="crumb-sep">›</span>' : "") + button;
    }).join("");
  }

  function renderSearch() {
    if (!model) return;
    const query = els.search.value.trim().toLocaleLowerCase("ru");
    if (!query) { els.searchResults.hidden = true; return; }
    const words = query.split(/\s+/).filter(Boolean);
    const results = Array.from(model.nodes.values()).filter(function (node) {
      return words.every(function (word) { return node.searchText.includes(word); });
    }).sort(function (a, b) {
      const aStarts = a.label.toLocaleLowerCase("ru").startsWith(query) ? 0 : 1;
      const bStarts = b.label.toLocaleLowerCase("ru").startsWith(query) ? 0 : 1;
      return aStarts - bStarts || a.label.localeCompare(b.label, "ru");
    }).slice(0, 24);
    searchCursor = Math.min(searchCursor, Math.max(0, results.length - 1));
    if (!results.length) els.searchResults.innerHTML = '<div class="search-empty">Совпадений нет</div>';
    else els.searchResults.innerHTML = results.map(function (node, index) {
      return '<button class="search-result' + (index === searchCursor ? ' is-active' : '') + '" type="button" role="option" data-node="' + escapeHtml(node.id) + '" style="--node-color:' + colorCss(node.category) + '"><span class="catalog-dot"></span><span class="search-result-main"><strong>' + escapeHtml(node.label) + '</strong><span>' + escapeHtml(localName(node.id)) + '</span></span><span class="search-result-kind">' + escapeHtml(CATEGORY[node.category].label) + '</span></button>';
    }).join("");
    els.searchResults.hidden = false;
  }

  function chooseActiveSearch() {
    const buttons = Array.from(els.searchResults.querySelectorAll(".search-result"));
    if (!buttons.length) return;
    const button = buttons[Math.min(searchCursor, buttons.length - 1)];
    els.search.value = "";
    els.searchResults.hidden = true;
    setSelected(button.dataset.node, { contextual: true });
  }

  function renderGraph() {
    disconnectGraph();
    const focusId = selectedId || (model.process && model.process.id);
    if (!focusId) { els.view.innerHTML = '<div class="empty-state"><strong>Нет узла для построения графа</strong></div>'; return; }
    els.view.innerHTML = '<div class="graph-wrap"><canvas class="graph-canvas" id="graph-canvas" role="img" aria-label="Локальный граф связей выбранного узла"></canvas><div class="graph-note">Колесо — масштаб · перетаскивание — панорама · щелчок по узлу — открыть</div><div class="graph-legend" id="graph-legend"></div><div class="graph-tooltip" id="graph-tooltip" hidden></div></div>';
    const canvas = document.getElementById("graph-canvas");
    graphState = createGraphState(focusId, Number(els.graphDepth.value));
    initGraphCanvas(canvas);
  }

  function disconnectGraph() {
    const canvas = document.getElementById("graph-canvas");
    if (canvas && canvas._observer) canvas._observer.disconnect();
  }

  function createGraphState(focusId, maxDepth) {
    const visited = new Map([[focusId, 0]]);
    const queue = [focusId];
    const edgeMap = new Map();
    const maxNodes = maxDepth === 3 ? 125 : 110;
    while (queue.length && visited.size < maxNodes) {
      const id = queue.shift();
      const depth = visited.get(id);
      const node = model.nodes.get(id);
      if (!node || depth >= maxDepth) continue;
      node.outgoing.forEach(function (triples, predicate) {
        const local = predicateLocal(predicate);
        if (!GRAPH_PREDICATES.has(local)) return;
        triples.filter(function (t) { return !t.literal; }).forEach(function (t) {
          if (visited.size >= maxNodes && !visited.has(t.o)) return;
          edgeMap.set(t.s + "|" + predicate + "|" + t.o, { from: t.s, to: t.o, predicate: local });
          if (!visited.has(t.o)) { visited.set(t.o, depth + 1); queue.push(t.o); }
        });
      });
      node.incoming.forEach(function (triples, predicate) {
        const local = predicateLocal(predicate);
        if (!GRAPH_PREDICATES.has(local)) return;
        triples.forEach(function (t) {
          if (visited.size >= maxNodes && !visited.has(t.s)) return;
          edgeMap.set(t.s + "|" + predicate + "|" + t.o, { from: t.s, to: t.o, predicate: local });
          if (!visited.has(t.s)) { visited.set(t.s, depth + 1); queue.push(t.s); }
        });
      });
    }
    const nodes = Array.from(visited.entries()).map(function (entry, index) {
      const node = model.nodes.get(entry[0]);
      const depth = entry[1];
      const angle = hashNumber(entry[0]) / 4294967295 * Math.PI * 2;
      const radius = depth * 170 + (index % 7) * 9;
      return { id: entry[0], ref: node, depth: depth, x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, vx: 0, vy: 0, w: entry[0] === focusId ? 150 : 126, h: entry[0] === focusId ? 48 : 40 };
    });
    const nodeMap = new Map(nodes.map(function (n) { return [n.id, n]; }));
    const edges = Array.from(edgeMap.values()).filter(function (e) { return nodeMap.has(e.from) && nodeMap.has(e.to); });
    relaxGraph(nodes, edges, nodeMap, focusId);
    return { focusId: focusId, nodes: nodes, nodeMap: nodeMap, edges: edges, scale: 1, tx: 0, ty: 0, dragNode: null, panning: false, pointerStart: null, hover: null };
  }

  function hashNumber(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) { hash ^= text.charCodeAt(i); hash = Math.imul(hash, 16777619); }
    return hash >>> 0;
  }

  function relaxGraph(nodes, edges, nodeMap, focusId) {
    for (let iteration = 0; iteration < 190; iteration += 1) {
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const a = nodes[i], b = nodes[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          let distance2 = dx * dx + dy * dy;
          if (distance2 < 1) { dx = 1; dy = .4; distance2 = 1.16; }
          const distance = Math.sqrt(distance2);
          const force = Math.min(3.2, 15500 / distance2) * (1 - iteration / 240);
          const fx = dx / distance * force, fy = dy / distance * force;
          if (a.id !== focusId) { a.vx -= fx; a.vy -= fy; }
          if (b.id !== focusId) { b.vx += fx; b.vy += fy; }
        }
      }
      edges.forEach(function (edge) {
        const a = nodeMap.get(edge.from), b = nodeMap.get(edge.to);
        const dx = b.x - a.x, dy = b.y - a.y, distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const desired = 150 + 24 * Math.abs(a.depth - b.depth);
        const force = (distance - desired) * .008;
        const fx = dx / distance * force, fy = dy / distance * force;
        if (a.id !== focusId) { a.vx += fx; a.vy += fy; }
        if (b.id !== focusId) { b.vx -= fx; b.vy -= fy; }
      });
      nodes.forEach(function (node) {
        if (node.id === focusId) { node.x = 0; node.y = 0; node.vx = 0; node.vy = 0; return; }
        node.vx += -node.x * .0009; node.vy += -node.y * .0009;
        node.vx *= .82; node.vy *= .82;
        node.x += node.vx; node.y += node.vy;
      });
    }
  }

  function initGraphCanvas(canvas) {
    const wrap = canvas.parentElement;
    const tooltip = document.getElementById("graph-tooltip");
    const categories = Array.from(new Set(graphState.nodes.map(function (n) { return n.ref.category; })));
    document.getElementById("graph-legend").innerHTML = categories.map(function (category) {
      return '<span class="legend-item" style="--node-color:' + colorCss(category) + '"><span class="legend-dot"></span>' + escapeHtml(CATEGORY[category].label) + '</span>';
    }).join("");

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.max(1, window.devicePixelRatio || 1);
      canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
      canvas._cssWidth = rect.width; canvas._cssHeight = rect.height; canvas._ratio = ratio;
      fitGraph(canvas, false); drawGraph(canvas);
    }
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    canvas._observer = observer;

    canvas.addEventListener("wheel", function (event) {
      event.preventDefault();
      const point = canvasPoint(canvas, event);
      const before = screenToWorld(canvas, point.x, point.y);
      const factor = event.deltaY < 0 ? 1.12 : .89;
      graphState.scale = Math.max(.18, Math.min(3.5, graphState.scale * factor));
      const after = screenToWorld(canvas, point.x, point.y);
      graphState.tx += (after.x - before.x) * graphState.scale;
      graphState.ty += (after.y - before.y) * graphState.scale;
      drawGraph(canvas);
    }, { passive: false });

    canvas.addEventListener("pointerdown", function (event) {
      canvas.setPointerCapture(event.pointerId);
      const point = canvasPoint(canvas, event), world = screenToWorld(canvas, point.x, point.y);
      const hit = hitGraphNode(world.x, world.y);
      graphState.dragNode = hit;
      graphState.panning = !hit;
      graphState.pointerStart = { x: point.x, y: point.y, worldX: world.x, worldY: world.y, tx: graphState.tx, ty: graphState.ty, moved: false };
      canvas.classList.add("is-dragging");
    });
    canvas.addEventListener("pointermove", function (event) {
      const point = canvasPoint(canvas, event);
      if (graphState.pointerStart) {
        const dx = point.x - graphState.pointerStart.x, dy = point.y - graphState.pointerStart.y;
        if (Math.abs(dx) + Math.abs(dy) > 4) graphState.pointerStart.moved = true;
        if (graphState.dragNode) {
          const world = screenToWorld(canvas, point.x, point.y);
          graphState.dragNode.x = world.x; graphState.dragNode.y = world.y;
        } else if (graphState.panning) {
          graphState.tx = graphState.pointerStart.tx + dx; graphState.ty = graphState.pointerStart.ty + dy;
        }
        drawGraph(canvas); return;
      }
      const world = screenToWorld(canvas, point.x, point.y);
      const hit = hitGraphNode(world.x, world.y);
      graphState.hover = hit;
      if (hit) {
        tooltip.hidden = false; tooltip.textContent = hit.ref.label;
        tooltip.style.left = Math.min(wrap.clientWidth - 290, point.x + 14) + "px";
        tooltip.style.top = Math.max(8, point.y - 16) + "px";
      } else tooltip.hidden = true;
      drawGraph(canvas);
    });
    canvas.addEventListener("pointerup", function (event) {
      const start = graphState.pointerStart;
      canvas.classList.remove("is-dragging");
      graphState.pointerStart = null; graphState.panning = false;
      const chosen = graphState.dragNode; graphState.dragNode = null;
      if (chosen && start && !start.moved) setSelected(chosen.id);
    });
    canvas.addEventListener("pointerleave", function () { if (!graphState.pointerStart) { graphState.hover = null; tooltip.hidden = true; drawGraph(canvas); } });
    requestAnimationFrame(resize);
  }

  function canvasPoint(canvas, event) { const rect = canvas.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top }; }
  function screenToWorld(canvas, x, y) { return { x: (x - canvas._cssWidth / 2 - graphState.tx) / graphState.scale, y: (y - canvas._cssHeight / 2 - graphState.ty) / graphState.scale }; }
  function worldToScreen(canvas, x, y) { return { x: canvas._cssWidth / 2 + graphState.tx + x * graphState.scale, y: canvas._cssHeight / 2 + graphState.ty + y * graphState.scale }; }
  function hitGraphNode(x, y) {
    for (let i = graphState.nodes.length - 1; i >= 0; i -= 1) {
      const n = graphState.nodes[i]; if (Math.abs(x - n.x) <= n.w / 2 && Math.abs(y - n.y) <= n.h / 2) return n;
    }
    return null;
  }

  function fitGraph(canvas, redraw) {
    if (!graphState || !canvas || !graphState.nodes.length) return;
    const minX = Math.min.apply(null, graphState.nodes.map(function (n) { return n.x - n.w / 2; }));
    const maxX = Math.max.apply(null, graphState.nodes.map(function (n) { return n.x + n.w / 2; }));
    const minY = Math.min.apply(null, graphState.nodes.map(function (n) { return n.y - n.h / 2; }));
    const maxY = Math.max.apply(null, graphState.nodes.map(function (n) { return n.y + n.h / 2; }));
    graphState.scale = Math.max(.18, Math.min(1.25, Math.min((canvas._cssWidth - 80) / Math.max(1, maxX - minX), (canvas._cssHeight - 80) / Math.max(1, maxY - minY))));
    graphState.tx = -(minX + maxX) / 2 * graphState.scale;
    graphState.ty = -(minY + maxY) / 2 * graphState.scale;
    if (redraw !== false) drawGraph(canvas);
  }

  function drawGraph(canvas) {
    if (!graphState || !canvas._ratio) return;
    const ratio = canvas._ratio, ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, canvas._cssWidth, canvas._cssHeight);
    const styles = getComputedStyle(document.documentElement);
    const line = styles.getPropertyValue("--line-strong").trim();
    const text = styles.getPropertyValue("--text").trim();
    const muted = styles.getPropertyValue("--muted").trim();
    graphState.edges.forEach(function (edge) {
      const a = graphState.nodeMap.get(edge.from), b = graphState.nodeMap.get(edge.to);
      const p1 = worldToScreen(canvas, a.x, a.y), p2 = worldToScreen(canvas, b.x, b.y);
      const emphasized = a.id === selectedId || b.id === selectedId;
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = emphasized ? resolveColor("stage") : line; ctx.globalAlpha = emphasized ? .75 : .34;
      ctx.lineWidth = emphasized ? 1.7 : 1; ctx.stroke(); ctx.globalAlpha = 1;
    });
    graphState.nodes.forEach(function (node) {
      const point = worldToScreen(canvas, node.x, node.y);
      const w = node.w * graphState.scale, h = node.h * graphState.scale;
      if (w < 18 || h < 8) return;
      const selected = node.id === selectedId, hover = graphState.hover && graphState.hover.id === node.id;
      ctx.beginPath(); roundedRect(ctx, point.x - w / 2, point.y - h / 2, w, h, Math.min(9, h / 4));
      ctx.fillStyle = selected ? resolveColor(node.ref.category) : styles.getPropertyValue("--surface-2").trim();
      ctx.globalAlpha = selected ? .92 : .94; ctx.fill(); ctx.globalAlpha = 1;
      ctx.strokeStyle = selected || hover ? resolveColor(node.ref.category) : line;
      ctx.lineWidth = selected ? 2.2 : hover ? 1.7 : 1; ctx.stroke();
      if (graphState.scale > .34) {
        ctx.fillStyle = selected ? styles.getPropertyValue("--bg-deep").trim() : text;
        ctx.font = (selected ? "600 " : "500 ") + Math.max(10, Math.min(12, 11 * graphState.scale + 2)) + "px Segoe UI, sans-serif";
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        drawWrappedLabel(ctx, node.ref.label, point.x, point.y, Math.max(55, w - 14), h - 6, selected ? styles.getPropertyValue("--bg-deep").trim() : text, muted);
      }
    });
  }

  function roundedRect(ctx, x, y, w, h, r) {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.moveTo(x + radius, y); ctx.arcTo(x + w, y, x + w, y + h, radius); ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius); ctx.arcTo(x, y, x + w, y, radius); ctx.closePath();
  }

  function drawWrappedLabel(ctx, label, x, y, maxWidth, maxHeight) {
    const words = label.split(/\s+/); const lines = []; let line = "";
    words.forEach(function (word) {
      const test = line ? line + " " + word : word;
      if (ctx.measureText(test).width > maxWidth && line) { lines.push(line); line = word; } else line = test;
    });
    if (line) lines.push(line);
    const visible = lines.slice(0, 2); if (lines.length > 2) visible[1] = visible[1].replace(/[.…]*$/, "…");
    const lineHeight = Math.min(15, maxHeight / Math.max(1, visible.length));
    visible.forEach(function (value, index) { ctx.fillText(value, x, y + (index - (visible.length - 1) / 2) * lineHeight, maxWidth); });
  }

  function graphFocus() { setView("graph"); }

  function handleDelegatedClick(event) {
    const activityDecision = event.target.closest("[data-open-activity-decisions]");
    if (activityDecision) {
      const activity = model.nodes.get(activityDecision.dataset.openActivityDecisions);
      const branchNode = activity && (activity.incoming.get(P.appliesToActivity) || [])
        .map(function (triple) { return model.nodes.get(triple.s); })
        .find(function (node) { return node && node.category === "branch"; });
      if (branchNode) { setSelected(branchNode.id); setView("decisions"); }
      return;
    }
    const kbOpen = event.target.closest("[data-kb-open]");
    if (kbOpen) {
      currentKnowledgeBaseId = kbOpen.dataset.kbOpen;
      const first = (model.kbBranches.get(currentKnowledgeBaseId) || [])[0];
      currentBranchId = first ? first.id : null;
      setSelected(currentKnowledgeBaseId);
      setView("decisions");
      return;
    }
    const branchOpen = event.target.closest("[data-branch-open]");
    if (branchOpen) { setSelected(branchOpen.dataset.branchOpen); setView("decisions"); return; }
    const nodeButton = event.target.closest("[data-node]");
    if (nodeButton && nodeButton.dataset.node) {
      const fromSearch = Boolean(nodeButton.closest(".search-results"));
      if (fromSearch) { els.search.value = ""; els.searchResults.hidden = true; }
      setSelected(nodeButton.dataset.node, { contextual: fromSearch });
      return;
    }
    const stageOpen = event.target.closest("[data-stage-open], [data-open-stage]");
    if (stageOpen) {
      const id = stageOpen.dataset.stageOpen || stageOpen.dataset.openStage;
      currentStageId = id; expandedStages.add(id); setSelected(id); setView("subprocess"); return;
    }
    const toggle = event.target.closest("[data-toggle]");
    if (toggle) {
      const id = toggle.dataset.toggle;
      if (expandedStages.has(id)) expandedStages.delete(id); else expandedStages.add(id);
      renderTree(); return;
    }
    const catalog = event.target.closest("[data-catalog]");
    if (catalog) { catalogFilter = catalog.dataset.catalog; setView("catalog"); return; }
    if (event.target.closest("[data-catalog-all]")) { catalogFilter = null; renderCatalog(); return; }
    if (event.target.closest("[data-focus-graph]")) graphFocus();
  }

  els.tabs.forEach(function (tab) { tab.addEventListener("click", function () { catalogFilter = null; setView(tab.dataset.view); }); });
  els.loadFiles.addEventListener("click", function () { els.fileInput.click(); });
  els.fileInput.addEventListener("change", function () { loadFiles(els.fileInput.files); });
  els.loadDefault.addEventListener("click", loadDefault);
  els.graphDepth.addEventListener("change", function () { if (currentView === "graph") renderGraph(); });
  els.graphFit.addEventListener("click", function () { const canvas = document.getElementById("graph-canvas"); if (canvas) fitGraph(canvas); });
  els.collapseTree.addEventListener("click", function () { expandedStages.clear(); renderTree(); });
  els.showGraph.addEventListener("click", graphFocus);
  els.historyBack.addEventListener("click", function () {
    const previous = selectionHistory.pop(); if (previous) setSelected(previous, { pushHistory: false });
    els.historyBack.disabled = selectionHistory.length === 0;
  });
  [els.tree, els.view, els.details, els.breadcrumbs, els.searchResults].forEach(function (element) { element.addEventListener("click", handleDelegatedClick); });

  els.search.addEventListener("input", function () { searchCursor = 0; renderSearch(); });
  els.search.addEventListener("keydown", function (event) {
    const count = els.searchResults.querySelectorAll(".search-result").length;
    if (event.key === "ArrowDown" && count) { event.preventDefault(); searchCursor = (searchCursor + 1) % count; renderSearch(); }
    else if (event.key === "ArrowUp" && count) { event.preventDefault(); searchCursor = (searchCursor - 1 + count) % count; renderSearch(); }
    else if (event.key === "Enter") { event.preventDefault(); chooseActiveSearch(); }
    else if (event.key === "Escape") { els.search.value = ""; els.searchResults.hidden = true; }
  });
  document.addEventListener("keydown", function (event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); els.search.focus(); els.search.select(); }
  });
  document.addEventListener("click", function (event) {
    if (!event.target.closest(".search-box") && !event.target.closest(".search-results")) els.searchResults.hidden = true;
  });

  let dragCounter = 0;
  ["dragenter", "dragover"].forEach(function (name) {
    els.workspace.addEventListener(name, function (event) { event.preventDefault(); if (name === "dragenter") dragCounter += 1; els.drop.classList.add("is-visible"); });
  });
  els.workspace.addEventListener("dragleave", function (event) { event.preventDefault(); dragCounter -= 1; if (dragCounter <= 0) { dragCounter = 0; els.drop.classList.remove("is-visible"); } });
  els.workspace.addEventListener("drop", function (event) { event.preventDefault(); dragCounter = 0; els.drop.classList.remove("is-visible"); loadFiles(event.dataTransfer.files); });

  if (window.matchMedia) {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    if (media.addEventListener) media.addEventListener("change", function () { const canvas = document.getElementById("graph-canvas"); if (canvas) drawGraph(canvas); });
  }

  loadDefault();
}());
