from __future__ import annotations

import csv
from pathlib import Path

from evaluate_decision_v4_1 import evaluate_guard


HERE = Path(__file__).resolve().parent


def choose(branch_id: str, beliefs: dict, policy: dict, schemas: dict[str, dict[str, str]],
           rows: list[dict[str, str]]) -> str:
    branch_rows = sorted((row for row in rows if row["branch_id"] == branch_id), key=lambda row: int(row["priority"]))
    fallback = next(row for row in branch_rows if row["guard"] == "otherwise")
    for row in branch_rows:
        if row["guard"] == "otherwise":
            continue
        value, _, _ = evaluate_guard(row["guard"], beliefs, schemas, policy)
        if value is None:
            return fallback["rule_id"]
        if value:
            return row["rule_id"]
    return fallback["rule_id"]


def main() -> int:
    with (HERE / "belief_schema_v4_1.csv").open(encoding="utf-8-sig", newline="") as stream:
        schemas = {row["belief_code"]: row for row in csv.DictReader(stream)}
    with (HERE / "decision_tables_v4_1.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    policy = {"project_symbolic_threshold": 0.9, "project_hybrid_threshold": 0.4, "project_analog_threshold": 0.7}
    cases = [
        ("BR_NS_COVERAGE_MODE", {"approved_plan_found": True, "ontology_coverage": 0.95}, "010"),
        ("BR_NS_COVERAGE_MODE", {"approved_plan_found": False, "ontology_coverage": 0.65}, "020"),
        ("BR_NS_COVERAGE_MODE", {"approved_plan_found": False, "ontology_coverage": 0.2}, "030"),
        ("BR_LIT_FACIES_ALGORITHM", {"training_image_available": True}, "999"),
        ("BR_LIT_FACIES_ALGORITHM", {"training_image_available": True, "non_two_point_patterns_material": True}, "010"),
        ("BR_LIT_SATURATION_MODEL", {"conductive_clay_effect": "strong", "archie_calibration_available": False}, "020"),
        ("BR_LIT_WELLTEST_DIAGNOSTIC", {"pressure_rate_history_qc": False}, "010"),
        ("BR_LIT_GEOMECH_COUPLING", {"mem_calibrated": True, "depletion_geomech_coupling_material": True, "stress_calibration_data_available": True}, "020"),
        ("BR_LIT_UNCERT_AGGREGATION", {"aggregation_requested": True, "dependent_parameters_present": True, "correlation_model_validated": False}, "010"),
        ("BR_NS_SOFTWARE_CALL", {"capability_verified": False}, "010"),
    ]
    for branch, beliefs, suffix in cases:
        selected = choose(branch, beliefs, policy, schemas, rows)
        assert selected.endswith(suffix), (branch, selected, suffix)
    print(f"PASS: {len(cases)} symbolic, missing-data, literature and safety cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
