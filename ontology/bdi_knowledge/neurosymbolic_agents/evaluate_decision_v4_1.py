from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected JSON object")
    return value


def scalar(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def compare(actual: Any, comparator: str, expected: Any) -> bool:
    if comparator == "=":
        return actual == expected
    if comparator == "!=":
        return actual != expected
    if comparator == "in":
        return actual in expected
    if comparator == "not in":
        return actual not in expected
    if comparator == "<":
        return actual < expected
    if comparator == "<=":
        return actual <= expected
    if comparator == ">":
        return actual > expected
    if comparator == ">=":
        return actual >= expected
    raise ValueError(f"Unknown comparator: {comparator}")


def validate_value(code: str, value: Any, schema: dict[str, str]) -> None:
    kind = schema["variable_type"]
    if kind == "boolean" and not isinstance(value, bool):
        raise TypeError(f"{code}: expected boolean")
    if kind == "decimal" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise TypeError(f"{code}: expected number")
    if kind in {"enum", "string"} and not isinstance(value, str):
        raise TypeError(f"{code}: expected string")
    allowed = [item for item in schema.get("allowed_values", "").split("|") if item]
    if allowed and value not in allowed:
        raise ValueError(f"{code}: {value!r} not in {allowed}")


def evaluate_guard(
    guard: str,
    beliefs: dict[str, Any],
    schemas: dict[str, dict[str, str]],
    policy: dict[str, Any],
) -> tuple[bool | None, list[dict[str, Any]], list[str]]:
    if guard == "otherwise":
        return True, [], []
    separator = " ANY " if " ANY " in guard else " ALL "
    logical = "ANY" if separator == " ANY " else "ALL"
    details: list[dict[str, Any]] = []
    missing: list[str] = []
    truths: list[bool] = []
    for atom in guard.split(separator):
        parts = atom.strip().split(" ", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid guard atom: {atom}")
        code, comparator, expected_raw = parts
        if code not in beliefs:
            missing.append(code)
            continue
        if code not in schemas:
            raise KeyError(f"No belief schema: {code}")
        actual = beliefs[code]
        validate_value(code, actual, schemas[code])
        if expected_raw.startswith("project_"):
            if expected_raw not in policy:
                missing.append(expected_raw)
                continue
            expected = policy[expected_raw]
        elif comparator in {"in", "not in"}:
            expected = [scalar(item) for item in expected_raw.split("|")]
        else:
            expected = scalar(expected_raw)
        passed = compare(actual, comparator, expected)
        truths.append(passed)
        details.append({
            "belief": code, "actual": actual, "comparator": comparator,
            "expected": expected, "passed": passed,
        })
    if logical == "ALL" and False in truths:
        return False, details, sorted(set(missing))
    if logical == "ANY" and True in truths:
        return True, details, sorted(set(missing))
    if missing:
        return None, details, sorted(set(missing))
    return (all(truths) if logical == "ALL" else any(truths)), details, []


def main() -> int:
    parser = argparse.ArgumentParser(description="GeoMAS BDI decision-table interpreter v4.1")
    parser.add_argument("branch_id")
    parser.add_argument("beliefs", type=Path)
    parser.add_argument("--policy", type=Path, default=HERE / "project_policy.v4_1.example.json")
    parser.add_argument("--allow-draft-policy", action="store_true")
    args = parser.parse_args()

    beliefs = load_object(args.beliefs)
    policy_document = load_object(args.policy)
    if not policy_document.get("approved", False) and not args.allow_draft_policy:
        raise PermissionError("Project policy is not APPROVED; draft is demonstration-only")
    policy = policy_document.get("parameters", {})

    with (HERE / "belief_schema_v4_1.csv").open(encoding="utf-8-sig", newline="") as stream:
        schemas = {row["belief_code"]: row for row in csv.DictReader(stream)}
    with (HERE / "decision_tables_v4_1.csv").open(encoding="utf-8-sig", newline="") as stream:
        rules = [row for row in csv.DictReader(stream) if row["branch_id"] == args.branch_id]
    if not rules:
        raise KeyError(f"Unknown branch: {args.branch_id}")
    rules.sort(key=lambda row: int(row["priority"]))

    selected: dict[str, str] | None = None
    evaluated: list[dict[str, Any]] = []
    fallback: dict[str, str] | None = None
    for row in rules:
        if row["guard"] == "otherwise":
            fallback = row
            continue
        value, details, missing = evaluate_guard(row["guard"], beliefs, schemas, policy)
        evaluated.append({"rule_id": row["rule_id"], "value": value, "details": details, "missing": missing})
        if value is None:
            break
        if value:
            selected = row
            break
    if selected is None:
        if fallback is None:
            raise RuntimeError("Branch has no safe fallback")
        selected = fallback

    human_required = selected["requires_human_approval"].lower() == "true"
    approved = bool(beliefs.get("expert_approval_present", False))
    status = selected.get("knowledge_status", "")
    execution_scope = selected.get("execution_eligibility", "")
    production_eligible = (
        (not human_required or approved)
        and status in {"APPROVED", "APPROVED_REFERENCE", "APPROVED_ARCHITECTURE"}
        and execution_scope == "PRODUCTION_AFTER_PROJECT_APPROVAL"
        and policy_document.get("approved", False)
    )
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "branch_id": args.branch_id,
        "selected_rule": selected["rule_id"],
        "outcome": selected["outcome"],
        "intention": selected["intention"],
        "method": selected.get("selected_method", ""),
        "function": selected.get("selected_function", ""),
        "capability": selected.get("requested_capability", ""),
        "knowledge_status": status,
        "execution_scope": execution_scope,
        "human_required": human_required,
        "production_eligible": production_eligible,
        "evaluated": evaluated,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
