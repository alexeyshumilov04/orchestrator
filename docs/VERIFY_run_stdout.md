# Сырой вывод dry-run (хвост, 33199 строк всего)

````
    "unknown": 7,
    "applicable": 0,
    "by_block": {
      "02": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 438,
        "unknown": 0,
        "unverified": 0,
        "total": 438
      },
      "03": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 7,
        "unknown": 0,
        "unverified": 0,
        "total": 7
      },
      "04": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 148,
        "unknown": 0,
        "unverified": 0,
        "total": 148
      },
      "05": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 46,
        "unknown": 0,
        "unverified": 0,
        "total": 46
      },
      "06": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 14,
        "unknown": 4,
        "unverified": 0,
        "total": 18
      },
      "13": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 15,
        "unknown": 0,
        "unverified": 0,
        "total": 15
      },
      "07": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 10,
        "unknown": 0,
        "unverified": 0,
        "total": 10
      },
      "08": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 7,
        "unknown": 1,
        "unverified": 0,
        "total": 8
      },
      "09": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 10,
        "unknown": 2,
        "unverified": 0,
        "total": 12
      },
      "10": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 10,
        "unknown": 0,
        "unverified": 0,
        "total": 10
      }
    },
    "by_source": {
      "package": {
        "passed": 0,
        "failed": 0,
        "not_applicable": 705,
        "unknown": 7,
        "unverified": 0,
        "total": 712
      }
    },
    "kq": 0.0,
    "kc": 0.0,
    "fitness": 0.0,
    "physical": null,
    "physical_known": false,
    "weights": {
      "alpha": 0.5,
      "beta": 0.5
    },
    "failed_checks": [],
    "blocks": [
      "01",
      "02",
      "03",
      "04",
      "05",
      "06",
      "07",
      "08",
      "13",
      "09",
      "10"
    ],
    "sources": {
      "package_blocks": {
        "G-DATA": [
          "01",
          "02",
          "03"
        ],
        "G-STRUCT": [
          "04"
        ],
        "G-GRID": [
          "04"
        ],
        "G-FACIES": [
          "05",
          "06"
        ],
        "G-PETRO": [
          "07",
          "08",
          "13"
        ],
        "G-SAT": [
          "09"
        ],
        "G-VOL": [
          "10"
        ],
        "G-MAPS": [
          "07",
          "08"
        ]
      },
      "gate_map": "ontology/qa_gate_map.yaml",
      "catalog": "domain/qaqc/checks_table.csv + ontology/qa_checks/*.csv",
      "checklist_index": "ontology/qa_checks/checklist_index.csv",
      "severity_levels": [
        0.9,
        0.75
      ],
      "catalog_checks": 714,
      "engine_checks": 705
    },
    "consistency": {
      "catalog_checks_in_scope": 712,
      "engine_checks_in_scope": 705,
      "described_but_not_executable": 7,
      "described_only_ids": [
        "QC_LITH_005",
        "QC_LITH_006",
        "QC_LITH_008",
        "QC_LITH_010",
        "QC_PERM_006",
        "QC_SAT_007",
        "QC_SAT_008"
      ],
      "unknown_checks": 7,
      "note": "unknown = описание есть, исполнимой проверки нет (или схема не разобрана) — это НЕ провал модели. described_only_ids — авторитетный перечень domain/qaqc.DESCRIBED_ONLY"
    },
    "values_keys": [
      "H_bot",
      "H_top",
      "H_well",
      "THICKNESS"
    ],
    "checklist": {
      "total_items": 6065,
      "blocks": 13,
      "index_total": 6065,
      "index_outside_blocks": 195,
      "catalog_checks": 714
    },
    "generated": "2026-10-12T07:25:01+00:00",
    "coverage": {
      "implemented": 714,
      "not_implemented": 5158,
      "unknown_unformalized": 5353,
      "file": "qaqc_coverage.json"
    }
  }
}

прогон завершён: вердикт QA/QC = unknown
````
