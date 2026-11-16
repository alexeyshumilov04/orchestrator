from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
NODE = Path(r"C:\Users\Fedor Kondratenko\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")


def main() -> int:
    required = ["index.html", "styles.css", "app.js", "ontology-data.js"]
    for name in required:
        path = DIST / name
        if not path.is_file() or path.stat().st_size == 0:
            raise AssertionError(f"Missing visualizer asset: {name}")

    html = (DIST / "index.html").read_text(encoding="utf-8")
    for asset in ["styles.css", "ontology-data.js", "app.js"]:
        if asset not in html:
            raise AssertionError(f"Entrypoint does not reference {asset}")
    for required_id in ["global-search", "ontology-tree", "view-root", "detail-pane"]:
        if f'id="{required_id}"' not in html:
            raise AssertionError(f"Missing UI landmark: {required_id}")

    app = (DIST / "app.js").read_text(encoding="utf-8")
    for token in ["ProcessSubstage", "AtomicModelingTask", "QAQCRule", "SoftwareBinding", "guardExpression", "hasTransitionCondition", "passesParameter"]:
        if token not in app:
            raise AssertionError(f"Missing v4 visual behavior: {token}")
    syntax = subprocess.run([str(NODE), "--check", str(DIST / "app.js")], capture_output=True, text=True)
    if syntax.returncode:
        raise AssertionError(syntax.stderr or syntax.stdout)

    data_path = DIST / "ontology-data.js"
    with data_path.open("r", encoding="utf-8") as handle:
        prefix = handle.read(512)
    if not prefix.startswith("window.GM_DEFAULT_ONTOLOGY=") or "GeoModelingEvolutionOntology_v4_1_AgentExtended_AllInOne.rdf" not in prefix:
        raise AssertionError("Embedded ontology header is invalid")

    report = {
        "status": "PASS",
        "assets": required,
        "embedded_data_bytes": data_path.stat().st_size,
        "javascript_syntax": "PASS",
        "views": ["process", "subprocess", "decisions", "graph", "catalog"],
        "agent_extension": "v4.1",
        "responsive_breakpoints": len(re.findall(r"@media", (DIST / "styles.css").read_text(encoding="utf-8"))),
    }
    (HERE / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"VISUALIZER VALIDATION FAILED: {exc}", file=sys.stderr)
        raise
