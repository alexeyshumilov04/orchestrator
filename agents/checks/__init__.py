"""Реестр проверок гейтов: builtin, контрактные, пакетные и CSV-описанные.

Сборка ИЗ ДАННЫХ — :meth:`CheckRegistry.from_data` (он же ``from_config``):
код (builtin/contract) + ``domain/qaqc/checks_table.csv`` по блокам из
``ontology/qa_gate_map.yaml`` + ``ontology/qa_checks/*.csv``.
"""
from __future__ import annotations

from agents.checks.base import (FAILED, NOT_APPLICABLE, PASSED, PENDING, STATES,
                                UNKNOWN, UNVERIFIED, CheckCatalogRow, CheckOutcome,
                                CheckRegistry, CheckSpec, RunReport,
                                apply_severity_overrides, build_data_checks,
                                code_checks, described_only_ids, evaluate_catalog_check,
                                gates_by_block, load_check_catalog, load_gate_map,
                                parse_threshold, resolve_values, result_checks,
                                severity_for, severity_levels)

__all__ = ["CheckRegistry", "CheckSpec", "CheckOutcome", "RunReport", "CheckCatalogRow",
           "build_data_checks", "code_checks", "load_check_catalog", "load_gate_map",
           "gates_by_block", "severity_for", "severity_levels", "parse_threshold",
           "resolve_values", "evaluate_catalog_check", "apply_severity_overrides",
           "described_only_ids", "result_checks",
           "PASSED", "FAILED", "NOT_APPLICABLE", "UNKNOWN", "UNVERIFIED", "PENDING",
           "STATES"]
