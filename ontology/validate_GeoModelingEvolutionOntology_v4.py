from __future__ import annotations

import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


HERE = Path(__file__).resolve().parent
MODULE_DIR = HERE / "modules"
MONOLITH = HERE / "GeoModelingEvolutionOntology_v4_AllInOne.rdf"
MANIFEST = HERE / "manifest.json"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
OWL_IMPORTS = "<http://www.w3.org/2002/07/owl#imports>"
BASES = ("https://example.org/geomodel/evolution/v4#", "https://example.org/geomodel/evolution/v4/bdi#")
IRI_PATTERN = re.compile(r"<([^>]+)>")


def read_lines(path: Path) -> set[str]:
    if not path.is_file():
        raise AssertionError(f"Missing file: {path}")
    lines = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("<") or not line.endswith(" ."):
            raise AssertionError(f"Malformed N-Triples line {path.name}:{number}: {line[:180]}")
        if len(IRI_PATTERN.findall(line)) < 2:
            raise AssertionError(f"Insufficient IRIs {path.name}:{number}: {line[:180]}")
        lines.add(line)
    return lines


def csv_count(name: str) -> int:
    with (HERE / name).open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    monolith = read_lines(MONOLITH)
    module_files = sorted(MODULE_DIR.glob("*.rdf"))
    if len(module_files) != manifest["modules"]:
        raise AssertionError(f"Module count mismatch: {len(module_files)} != {manifest['modules']}")

    union = set()
    module_names = {path.stem for path in module_files}
    for path in module_files:
        triples = read_lines(path)
        union.update(triples)
        if not triples <= monolith:
            raise AssertionError(f"Monolith does not contain all triples from {path.name}")
        for line in triples:
            if OWL_IMPORTS not in line:
                continue
            target = IRI_PATTERN.findall(line)[-1].rsplit("/", 1)[-1]
            if target not in module_names:
                raise AssertionError(f"Dangling owl:imports target {target} in {path.name}")

    if manifest["triples_all_in_one"] != len(monolith):
        raise AssertionError("Manifest triple count does not match monolith")
    if not (8000 <= manifest["distinct_local_nodes"] <= 20000):
        raise AssertionError(f"Node target violated: {manifest['distinct_local_nodes']}")

    expected_csv = {
        "process_catalog.csv": manifest["atomic_process_activities"],
        "data_parameter_catalog.csv": manifest["data_parameter_definitions"],
        "qaqc_rules.csv": manifest["qaqc_rules_imported"],
        "tnavigator_functions.csv": manifest["tnavigator_callable_candidates"],
        "software_mappings.csv": manifest["software_bindings"],
        "source_register.csv": manifest["local_and_web_sources"],
    }
    for name, expected in expected_csv.items():
        actual = csv_count(name)
        if actual != expected:
            raise AssertionError(f"{name}: {actual} rows != {expected}")

    minimums = {
        "process_stages": 18,
        "process_substages": 200,
        "atomic_process_activities": 1200,
        "data_parameter_definitions": 400,
        "qaqc_rules_imported": 6000,
        "tnavigator_callable_candidates": 3000,
        "software_bindings": 400,
        "local_and_web_sources": 1500,
        "bdi_transition_rules_added": 1400,
    }
    for key, minimum in minimums.items():
        if manifest[key] < minimum:
            raise AssertionError(f"{key}: {manifest[key]} < {minimum}")

    required_text = [
        "Правило QAQC:", "typicalRange", "typicalUncertainty", "hasTechnologyMetadataProfile",
        "hasUncertaintyProfile", "hasEscalationRoute", "hasAlternativeBinding", "guardExpression",
        "requiresHumanApproval", "exactDuplicateOf", "wasRevisionOf",
    ]
    text = "\n".join(monolith)
    for token in required_text:
        if token not in text:
            raise AssertionError(f"Required semantic feature absent: {token}")

    ET.parse(HERE / "catalog-v001.xml")
    report = {
        "status": "PASS",
        "triples": len(monolith),
        "modules": len(module_files),
        "distinct_local_nodes": manifest["distinct_local_nodes"],
        "checks": 14 + len(module_files) + len(expected_csv) + len(minimums) + len(required_text),
        "note": "N-Triples lexical structure, modular closure, imports, catalogs and coverage thresholds validated.",
    }
    (HERE / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        raise
