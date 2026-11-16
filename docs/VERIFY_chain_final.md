=== 1. ОБЯЗАТЕЛЬНЫЕ ТЕСТЫ (python) ===
  tests/test_v5.py: пройдено 32, провалено 0 (exit=0)
  tests/test_agents.py: пройдено 223, провалено 0 (exit=0)
  tests/test_base_agent.py: пройдено 39, провалено 0 (exit=0)

=== 1b. ТЕСТ АУДИТА ХАРДКОДА ===
  exit=0, итог: (4, 0); долг: известный долг есть

=== 1c. ТЕСТЫ УЧАСТНИКОВ ===
  tests/test_contracts.py: пройдено 107, провалено 0 (exit=0)
  tests/test_qaqc_checks.py: пройдено 55, провалено 0 (exit=0)
  tests/test_structural_agent.py: пройдено 69, провалено 0 (exit=0)
  tests/test_facies_agent.py: пройдено 44, провалено 0 (exit=0)
  tests/test_petro_agent.py: пройдено 78, провалено 0 (exit=0)
  найдено тестов участников: 5/5

=== 1d. ПЕРЕСЧЁТ ЧЕРЕЗ pytest (скрытые ошибки импорта) ===
..........................................                               [100%]
42 passed in 55.02s
  pytest: 42 passed, errors=нет

=== 2. PREFLIGHT ===
  exit=0; строка 'preflight: OK': True

=== 3. DRY-RUN + ИНВАРИАНТЫ ОТЧЁТА ===
        "not_implemented": 5158,
        "unknown_unformalized": 5353,
        "file": "qaqc_coverage.json"
      }
    }
  }
  
  прогон завершён: вердикт QA/QC = unknown
  steps: total=49 done=47 error=0 pending_template=0 skipped_by_policy=2
  render_warnings=[]
[WARN] skipped_by_policy=2 (на базовой линии был ровно 1 — шаг вреза)

=== 4. QA/QC В ОТЧЁТЕ ВЕРХНЕГО УРОВНЯ ===
  qaqc: total=712 passed=0 failed=0 not_applicable=705 kq=0.0 kc=0.0 physical=None
  qaqc_coverage.json есть; заявленный охват: 6065

=== 5. МЕСТА QA/QC В АРТЕФАКТАХ ===
  карт PNG в runs/<id>/maps/: 7: ['HCPV', 'NetVolume', 'PERM', 'PoreVolume', 'PORO', 'Tl_thick', 'U1_top']
  (dry-run: карты не обязательны; на --execute ожидается >= 8)
  ветвей ансамбля в отчёте: 5
  отрендеренный воркфлоу: строк 3886, begin_wf_item=47
  чужые токены обучения в рендере: нет (всего проверено 8)

=== 6. РЕАЛЬНЫЙ ПРОГОН (--execute) ===
  не запускался: нужен флаг --execute (лицензия, ~13 мин)

=== ИТОГ (chain) ===
FAIL: 0 | WARN: 1
