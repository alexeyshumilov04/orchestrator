from __future__ import annotations

import ast
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
BDI_FILE = HERE.parent / "BDI_KnowledgeBase_v4_1_AllInOne.rdf"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
BDI = "https://example.org/geomodel/evolution/v4/bdi#"
TRIPLE_RE = re.compile(r'^<([^>]*)> <([^>]*)> (.+) \.$')
IRI_RE = re.compile(r'^<([^>]*)>$')


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def main() -> int:
    manifest = json.loads((HERE / "manifest_v4_1.json").read_text(encoding="utf-8"))
    lines = [line for line in BDI_FILE.read_text(encoding="utf-8").splitlines() if line]
    outgoing: dict[tuple[str, str], list[str]] = defaultdict(list)
    types: dict[str, set[str]] = defaultdict(set)
    for number, line in enumerate(lines, 1):
        match = TRIPLE_RE.fullmatch(line)
        require(bool(match), f"Invalid N-Triples line {number}")
        subject, predicate, obj = match.groups()
        outgoing[(subject, predicate)].append(obj)
        target = IRI_RE.fullmatch(obj)
        if predicate == RDF_TYPE and target:
            types[subject].add(target.group(1))

    branches = {subject for subject, values in types.items() if BDI + "BranchPoint" in values}
    rules = {subject for subject, values in types.items() if BDI + "DecisionRule" in values}
    profiles = {subject for subject, values in types.items() if BDI + "DomainAgentProfile" in values}
    require(len(branches) == manifest["combined_branch_points"], "Branch count mismatch")
    require(len(rules) == manifest["combined_rules"], "Rule count mismatch")
    require(len(profiles) == manifest["agent_profiles"], "Profile count mismatch")

    priorities: dict[str, list[int]] = defaultdict(list)
    linked_rules: set[str] = set()
    for branch in branches:
        for predicate in [
            "belongsToKnowledgeBase", "appliesToActivity", "missingDataPolicy",
            "conflictPolicy", "requiresEvidence", "hasFallbackRule",
        ]:
            require(bool(outgoing[(branch, BDI + predicate)]), f"{branch}: missing {predicate}")
        rule_tokens = outgoing[(branch, BDI + "hasRule")]
        require(len(rule_tokens) >= 2, f"{branch}: fewer than two rules")
        fallback = outgoing[(branch, BDI + "hasFallbackRule")]
        require(len(fallback) == 1 and fallback[0] in rule_tokens, f"{branch}: invalid fallback")
        for token in rule_tokens:
            match = IRI_RE.fullmatch(token)
            require(bool(match), f"{branch}: rule is not IRI")
            rid = match.group(1)
            linked_rules.add(rid)
            raw_priorities = outgoing[(rid, BDI + "rulePriority")]
            require(bool(raw_priorities), f"{rid}: no rulePriority")
            number = int(re.search(r'"(-?\d+)"', raw_priorities[0]).group(1))
            priorities[branch].append(number)
            require(bool(outgoing[(rid, BDI + "guardExpression")]), f"{rid}: no guard")
            require(bool(outgoing[(rid, BDI + "concludesOutcome")]), f"{rid}: no outcome")
            require(bool(outgoing[(rid, BDI + "setsIntention")]), f"{rid}: no intention")
            require(bool(outgoing[(rid, BDI + "requiresHumanApproval")]), f"{rid}: no human gate")
        require(len(priorities[branch]) == len(set(priorities[branch])), f"{branch}: duplicate priorities")
    require(linked_rules == rules, "Unlinked rules found")

    with (HERE / "decision_tables_v4_1.csv").open(encoding="utf-8-sig", newline="") as stream:
        decision_rows = list(csv.DictReader(stream))
    with (HERE / "belief_schema_v4_1.csv").open(encoding="utf-8-sig", newline="") as stream:
        belief_rows = list(csv.DictReader(stream))
    with (HERE / "agent_profiles.csv").open(encoding="utf-8-sig", newline="") as stream:
        agent_rows = list(csv.DictReader(stream))
    require(len(decision_rows) == len(rules), "Decision CSV does not cover RDF rules")
    require(len({row["rule_id"] for row in decision_rows}) == len(rules), "Duplicate rule ids in CSV")
    require(len(belief_rows) == manifest["belief_schema_entries"], "Belief schema count mismatch")
    belief_schema = {row["belief_code"]: row for row in belief_rows}
    for row in decision_rows:
        guard = row["guard"]
        if guard == "otherwise":
            continue
        separator = " ANY " if " ANY " in guard else " ALL "
        for atom in guard.split(separator):
            code, comparator, expected = atom.strip().split(" ", 2)
            require(code in belief_schema, f"{row['rule_id']}: missing belief schema {code}")
            allowed = {value for value in belief_schema[code].get("allowed_values", "").split("|") if value}
            if allowed and comparator in {"=", "in"}:
                expected_values = set(expected.split("|"))
                require(expected_values <= allowed, f"{row['rule_id']}: {expected_values - allowed} outside {code} enum")
    stage_counts = Counter(stage for row in agent_rows for stage in row["stages"].split(","))
    require(all(stage_counts[f"S{i:02d}"] for i in range(1, 19)), "Not all stages have agent coverage")

    ast.parse((HERE.parent.parent / "build_NeurosymbolicAgentKB_v4_1.py").read_text(encoding="utf-8"))
    ast.parse((HERE / "evaluate_decision_v4_1.py").read_text(encoding="utf-8"))
    print(json.dumps({
        "status": "PASS", "branches": len(branches), "rules": len(rules),
        "agent_profiles": len(profiles), "beliefs": len(belief_rows),
        "note": "Structural autonomy is complete; production gates remain intentionally blocking.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
