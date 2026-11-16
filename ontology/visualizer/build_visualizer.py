from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ONTOLOGY_DIR = HERE.parent
REFERENCE = ONTOLOGY_DIR.parents[1] / "Онтологии процесса 3" / "visualizer" / "dist"
DIST = HERE / "dist"
SOURCE_DIR = HERE / "src"


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ONTOLOGY_DIR / "manifest.json").read_text(encoding="utf-8"))
    agent_manifest_path = ONTOLOGY_DIR / "bdi_knowledge" / "neurosymbolic_agents" / "manifest_v4_1.json"
    agent_manifest = json.loads(agent_manifest_path.read_text(encoding="utf-8")) if agent_manifest_path.is_file() else {}
    source = ONTOLOGY_DIR / "GeoModelingEvolutionOntology_v4_1_AgentExtended_AllInOne.rdf"
    if not source.is_file():
        source = ONTOLOGY_DIR / "GeoModelingEvolutionOntology_v4_AllInOne.rdf"
    ntriples = source.read_text(encoding="utf-8")

    # Authored static files live in src; the first post-customization run captures
    # the current dist files so later data rebuilds cannot erase v4 UI changes.
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ["index.html", "app.js", "styles.css"]:
        authored = SOURCE_DIR / name
        if authored.is_file():
            content = authored.read_text(encoding="utf-8")
        elif (DIST / name).is_file():
            content = (DIST / name).read_text(encoding="utf-8")
            authored.write_text(content, encoding="utf-8", newline="\n")
        else:
            content = (REFERENCE / name).read_text(encoding="utf-8")
            authored.write_text(content, encoding="utf-8", newline="\n")
        (DIST / name).write_text(content, encoding="utf-8", newline="\n")

    payload = {
        "name": "Эволюционная онтология КГМ v4.1 · процесс + данные + QA/QC + нейросимвольные BDI-агенты",
        "source": source.name,
        "version": agent_manifest.get("version", manifest["version"]),
        "sha256": hashlib.sha256(ntriples.encode("utf-8")).hexdigest(),
        "statistics": {**manifest, "agent_extension": agent_manifest},
        "ntriples": ntriples,
    }
    (DIST / "ontology-data.js").write_text(
        "window.GM_DEFAULT_ONTOLOGY=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"dist": str(DIST), "ontology_data_bytes": (DIST / "ontology-data.js").stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
