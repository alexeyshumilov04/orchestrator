"""C1 — ЗНАНИЕ: онтология ГГДМ v4, загруженная КАК ДАННЫЕ (RDF + CSV-каталоги).

Операции, стадии, QA/QC-правила, функции tNavigator и параметры читаются из
КАТАЛОГОВ онтологии v4 (process_catalog.csv, tnavigator_functions.csv,
data_parameter_catalog.csv, qaqc_rules.csv, software_mappings.csv), а НЕ из кода.

RDF (50 МБ) грузится ОПЦИОНАЛЬНО через rdflib. Основной путь планирования — CSV:
быстро, детерминированно, без тяжёлого графа в рантайме.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import Config


# -- записи каталогов (данные, не поведение) ---------------------------------
@dataclass(frozen=True)
class ProcessOperation:
    id: str
    stage: str
    stage_label: str
    substage: str
    substage_label: str
    task: str
    method: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    transition: str


@dataclass(frozen=True)
class TNavFunction:
    node: str
    function: str
    manual: str
    pages: str
    stage: str
    operation: str
    mapping_basis: str
    status: str


@dataclass(frozen=True)
class ParamSpec:
    code: str
    name: str
    data_type: str
    unit: str
    typical_range: str
    typical_error: str
    level: str
    domain: str
    stage: str
    equipment: str
    node: str


@dataclass(frozen=True)
class QaRule:
    node: str
    id: str
    rule_type: str
    stage: str
    condition: str
    action: str
    target: str
    state: str
    source_row: str

    @property
    def formalized(self) -> bool:
        return "не формализовано" not in (self.state or "").lower()


@dataclass(frozen=True)
class SoftwareBinding:
    method: str
    operation_node: str
    binding_node: str
    target_software: str
    target_version: str
    locator: str
    status: str


@dataclass(frozen=True)
class StageInfo:
    id: str
    label: str
    order: int


class OntologyService:
    """Единая точка знания. CSV-каталоги + (опционально) RDF-граф."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._cache: dict[str, list] = {}
        self._graph = None

    def _csv(self, dotted: str) -> Path:
        return self.cfg.path(dotted)

    @staticmethod
    def _read_csv(path: Path) -> list[dict]:
        path = Path(path)
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [{(k or "").strip(): (v or "").strip() for k, v in row.items()}
                    for row in csv.DictReader(fh)]

    def _rows(self, key: str, dotted: str) -> list[dict]:
        if key not in self._cache:
            self._cache[key] = self._read_csv(self._csv(dotted))
        return self._cache[key]

    @staticmethod
    def _split_ids(value: str) -> tuple[str, ...]:
        if not value:
            return ()
        for sep in (";", "|", ","):
            value = value.replace(sep, " ")
        return tuple(tok for tok in value.split() if tok)

    # -- операции / стадии ---------------------------------------------------
    def operations(self, stage: str | None = None) -> list[ProcessOperation]:
        out: list[ProcessOperation] = []
        for r in self._rows("process", "ontology.process_csv"):
            if stage and r.get("stage") != stage:
                continue
            out.append(ProcessOperation(
                id=r.get("id", ""), stage=r.get("stage", ""),
                stage_label=r.get("stage_label", ""), substage=r.get("substage", ""),
                substage_label=r.get("substage_label", ""), task=r.get("task", ""),
                method=r.get("method", ""), inputs=self._split_ids(r.get("input", "")),
                outputs=self._split_ids(r.get("output", "")), transition=r.get("transition", "")))
        return out

    def stages(self) -> list[StageInfo]:
        out: list[StageInfo] = []
        seen: set[str] = set()
        for op in self.operations():
            if op.stage and op.stage not in seen:
                seen.add(op.stage)
                out.append(StageInfo(id=op.stage, label=op.stage_label, order=len(out) + 1))
        return out

    # -- функции тНавигатора (callable) --------------------------------------
    @staticmethod
    def _tnav(r: dict) -> TNavFunction:
        return TNavFunction(**{k: r.get(k, "") for k in (
            "node", "function", "manual", "pages", "stage", "operation",
            "mapping_basis", "status")})

    def bindings(self, op_id: str) -> list[TNavFunction]:
        out = []
        for r in self._rows("tnav_functions", "ontology.functions_csv"):
            if op_id and (r.get("operation") == op_id or op_id in (r.get("operation", "") or "")):
                out.append(self._tnav(r))
        return out

    def tnav_functions(self, *, only_verified: bool = False) -> list[TNavFunction]:
        out = [self._tnav(r) for r in self._rows("tnav_functions", "ontology.functions_csv")]
        if only_verified:
            out = [f for f in out if "candidate" not in (f.status or "").lower()]
        return out

    # -- QA/QC ---------------------------------------------------------------
    def qa_rules(self, stage: str | None = None, *, formalized_only: bool = False) -> list[QaRule]:
        out: list[QaRule] = []
        for r in self._rows("qaqc", "ontology.qaqc_csv"):
            if stage and r.get("stage") != stage:
                continue
            rule = QaRule(
                node=r.get("node", ""), id=r.get("id", ""), rule_type=r.get("rule_type", ""),
                stage=r.get("stage", ""), condition=r.get("condition", ""),
                action=r.get("action", ""), target=r.get("target", ""),
                state=r.get("state", ""), source_row=r.get("source_row", ""))
            if formalized_only and not rule.formalized:
                continue
            out.append(rule)
        return out

    # -- параметры -----------------------------------------------------------
    def parameters(self, level: str | None = None, domain: str | None = None) -> list[ParamSpec]:
        out: list[ParamSpec] = []
        for r in self._rows("params", "ontology.params_csv"):
            if level and r.get("level") != level:
                continue
            if domain and r.get("domain") != domain:
                continue
            out.append(ParamSpec(
                code=r.get("code", ""), name=r.get("name", ""), data_type=r.get("data_type", ""),
                unit=r.get("unit", ""), typical_range=r.get("typical_range", ""),
                typical_error=r.get("typical_error", ""), level=r.get("level", ""),
                domain=r.get("domain", ""), stage=r.get("stage", ""),
                equipment=r.get("equipment", ""), node=r.get("node", "")))
        return out

    def parameter(self, code: str) -> ParamSpec | None:
        for p in self.parameters():
            if p.code == code:
                return p
        return None

    # -- привязки к ПО -------------------------------------------------------
    def software_bindings(self, method: str | None = None) -> list[SoftwareBinding]:
        out = []
        for r in self._rows("software", "ontology.software_csv"):
            if method and r.get("method") != method:
                continue
            out.append(SoftwareBinding(
                method=r.get("method", ""), operation_node=r.get("operation_node", ""),
                binding_node=r.get("binding_node", ""), target_software=r.get("target_software", ""),
                target_version=r.get("target_version", ""), locator=r.get("locator", ""),
                status=r.get("status", "")))
        return out

    # -- RDF (опционально) ---------------------------------------------------
    def graph(self):
        if self._graph is not None:
            return self._graph
        path = self._csv("ontology.ttl_path")
        if not path.is_file():
            return None
        try:
            from rdflib import Graph
        except Exception:                     # noqa: BLE001 — rdflib опционален
            return None
        g = Graph()
        try:
            fmt = "nt" if path.suffix.lower() == ".rdf" else "turtle"
            g.parse(str(path), format=fmt)
        except Exception:                     # noqa: BLE001
            return None
        self._graph = g
        return g

    def stats(self) -> dict:
        return {
            "operations": len(self.operations()),
            "stages": len(self.stages()),
            "tnav_functions": len(self.tnav_functions()),
            "qa_rules": len(self.qa_rules()),
            "params": len(self.parameters()),
            "software_bindings": len(self.software_bindings()),
            # RDF НЕ грузим здесь (50 МБ): статус — по уже загруженному графу.
            "rdf": "loaded" if self._graph is not None else "csv-only (rdf lazy)",
        }



