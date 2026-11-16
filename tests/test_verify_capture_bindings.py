"""Снимок сырых выводов аудита привязок и хардкода в docs/VERIFY_hardcode_raw.md.

Запуск: python -X utf8 tests/test_verify_capture_bindings.py
"""
from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ["test_verify_field_bindings.py", "test_verify_hardcode.py",
         "test_verify_qaqc_checklist.py"]

fence = "`" * 4
parts = [f"# АУДИТ ПРИВЯЗОК И ХАРДКОДА — сырые выводы ({datetime.datetime.now():%Y-%m-%d %H:%M})\n"]
for t in TOOLS:
    p = subprocess.run([sys.executable, "-X", "utf8", "tests/" + t],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    body = ((p.stdout or "") + (p.stderr or "")).strip()
    print(f"{t}: exit={p.returncode}")
    parts.append(f"\n## tests/{t} (exit={p.returncode})\n\n{fence}\n{body}\n{fence}\n")
out = ROOT / "docs" / "VERIFY_hardcode_raw.md"
out.write_text("\n".join(parts), encoding="utf-8")
print("written", out.relative_to(ROOT))
