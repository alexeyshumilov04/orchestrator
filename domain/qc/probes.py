"""Пробники ОТКРЫТОГО проекта тНава: свойства, статистики, фации, контакты, запасы.

Канал: `project.run_py_code(code=…)` не возвращает значения наружу (проверено на
26.x), поэтому сниппет пишет отчёт «ключ|значение» в tmp-файл, а координатор/агент
его разбирает (:func:`parse_report`). Здесь живут ТОЛЬКО генераторы кода и разбор:
никаких доменных имён в коде — имена сетки/кубов/карт приходят АРГУМЕНТАМИ из
данных (правило 1).

Правило 6: каждая недоступная величина попадает в отчёт как `key=unknown` вместе
с текстом ошибки API (`<key>__error`), а не подменяется нулём. Поэтому сниппеты
собираются из отдельных try/except-блоков, а не из одного общего.
"""
from __future__ import annotations

from pathlib import Path


def _q(path) -> str:
    return str(path).replace("\\", "/")


def _writer(out_path) -> str:
    """Хвост сниппета: записать накопленные строки в tmp-файл."""
    return (
        "try:\n"
        f"    open (r'{_q(out_path)}', 'w', encoding='utf-8').write ('\\n'.join (out))\n"
        "except Exception as e:\n"
        "    out.append ('__write_error|' + str (e)[:160])\n"
        "'ok'\n"
    )


def property_inventory_code(grid_name: str, out_path) -> str:
    """Список свойств сетки (`get_all_properties`) с попыткой прочитать тип.

    Отчёт: ``property|<имя>|<тип или unknown>`` по строке на свойство.
    """
    code = (
        "out = []\n"
        "try:\n"
        f"    g = get_grid_by_name (name='{grid_name}')\n"
        "except Exception as e:\n"
        "    out.append ('__grid_error|' + str (e)[:160])\n"
        "    g = None\n"
        "if g is not None:\n"
        "    try:\n"
        "        props = list (g.get_all_properties ())\n"
        "    except Exception as e:\n"
        "        out.append ('__properties_error|' + str (e)[:160])\n"
        "        props = []\n"
        "    for p in props:\n"
        "        nm = str (getattr (p, 'name', '') or '')\n"
        "        tp = 'unknown'\n"
        "        for meth in ('get_type', 'get_template', 'get_data_type'):\n"
        "            fn = getattr (p, meth, None)\n"
        "            if fn is None:\n"
        "                continue\n"
        "            try:\n"
        "                _v = fn ()\n"
        "            except Exception as e:\n"
        "                tp = 'unknown (' + meth + ': ' + str (e)[:60] + ')'\n"
        "                break\n"
        "            # str()/repr() на объектах API не вызываем (роняли задачу тНава)\n"
        "            tp = _v if isinstance (_v, str) else 'object'\n"
        "            break\n"
        "        out.append ('property|' + nm + '|' + tp)\n"
    )
    return code + _writer(out_path)


def _stat_call(kind: str) -> str:
    """Один try/except-блок чтения статистики `kind` (ошибка API — в отчёт)."""
    return (
        "    try:\n"
        f"        _v = p.compute_statistics (type='{kind}')\n"
        "        if isinstance (_v, dict):\n"
        f"            _v = _v.get ('{kind}')\n"
        "        out.append ('" + kind + "|' + (repr (float (_v))"
        " if isinstance (_v, (int, float)) else 'unknown'))\n"
        "    except Exception as e:\n"
        "        out.append ('" + kind + "__error|' + type (e).__name__ + ': '"
        " + str (e)[:120])\n"
    )


def statistics_code(grid_name: str, prop_name: str, out_path,
                    percentiles: tuple[float, ...] = ()) -> str:
    """Статистики куба: min/max/mean/sum/std + проценты (если API их поддерживает).

    Для процентов перебираются разные имена параметра/типа; что не поддержано —
    попадает в отчёт как ``pNN=unknown`` с текстом ошибки (правило 6).
    """
    code = (
        "out = []\n"
        "try:\n"
        f"    p = get_grid_by_name (name='{grid_name}').get_property_by_name"
        f" (name='{prop_name}')\n"
        "except Exception as e:\n"
        "    out.append ('__property_error|' + str (e)[:160])\n"
        "    p = None\n"
        "if p is not None:\n"
    )
    for kind in ("min", "max", "mean", "sum", "std"):
        code += _stat_call(kind)
    for pct in percentiles:
        tag = f"p{pct:g}".replace(".", "_")
        for tname in ("percentile", "quantile", "p"):
            code += (
                f"    try:\n"
                f"        _v = p.compute_statistics (type='{tname}', percentile={pct!r})\n"
                f"        if isinstance (_v, dict):\n"
                f"            _v = _v.get ('{tname}')\n"
                f"        out.append ('{tag}|' + (repr (float (_v))"
                f" if isinstance (_v, (int, float)) else 'unknown'))\n"
                f"    except Exception as e:\n"
                f"        if not any (_l.startswith ('{tag}|') for _l in out):\n"
                f"            out.append ('{tag}|unknown')\n"
                f"            out.append ('{tag}__error|' + type (e).__name__ + ': '"
                f" + str (e)[:120])\n"
            )
    return code + _writer(out_path)


def facies_proportions_code(grid_name: str, prop_name: str, out_path,
                            codes: tuple[int, ...] = ()) -> str:
    """Доли фаций по КОДАМ: перебор способов чтения массива куба.

    Коды приходят из данных (перечень классов), а не из кода. Если API не отдаёт
    массив значений — в отчёте ``__array_error`` и ни одной доли (не нули).
    """
    code = (
        "out = []\n"
        "values = None\n"
        "try:\n"
        f"    p = get_grid_by_name (name='{grid_name}').get_property_by_name"
        f" (name='{prop_name}')\n"
        "except Exception as e:\n"
        "    out.append ('__property_error|' + str (e)[:160])\n"
        "    p = None\n"
        "if p is not None:\n"
        "    for meth in ('get_np_array', 'get_all_values', 'get_values', 'to_np_array'):\n"
        "        fn = getattr (p, meth, None)\n"
        "        if fn is None or values is not None:\n"
        "            continue\n"
        "        try:\n"
        "            values = list (fn ())\n"
        "            out.append ('__array_source|' + meth)\n"
        "        except Exception as e:\n"
        "            out.append ('__array_try|' + meth + '|' + str (e)[:100])\n"
        "if values is None:\n"
        "    out.append ('__array_error|ни один способ чтения массива куба недоступен')\n"
        "else:\n"
        "    import numpy as _np\n"
        "    arr = _np.asarray (values, dtype=float).reshape (-1)\n"
        "    finite = arr[_np.isfinite (arr)]\n"
        "    out.append ('__total|' + repr (int (finite.size)))\n"
        "    for code in [" + ", ".join(str(int(c)) for c in (codes or ())) + "]:\n"
        "        if finite.size:\n"
        "            share = float (_np.count_nonzero (finite == float (code)))"
        " / float (finite.size)\n"
        "            out.append ('facies|' + str (code) + '|' + repr (share))\n"
        "        else:\n"
        "            out.append ('facies|' + str (code) + '|unknown')\n"
    )
    return code + _writer(out_path)


_CONTACT_GETTERS = ("get_contact_by_name", "get_contact", "contact_by_name")


def contacts_code(contact_names: tuple[str, ...], out_path) -> str:
    """Отметки контактов проекта: перебор документированных геттеров.

    Для каждого имени — ``contact|<имя>|<значение или unknown>``; ошибки API
    фиксируются в ``contact__error`` (правило 6). Имена — аргумент из данных.
    """
    names = ", ".join(repr(str(n)) for n in (contact_names or ()))
    code = (
        "out = []\n"
        f"for _n in [{names}]:\n"
        "    got = False\n"
        "    for meth in " + repr(list(_CONTACT_GETTERS)) + ":\n"
        "        fn = globals ().get (meth)\n"
        "        if fn is None or got:\n"
        "            continue\n"
        "        try:\n"
        "            c = fn (name=_n)\n"
        "        except Exception as e:\n"
        "            out.append ('contact__try|' + meth + '|' + str (e)[:100])\n"
        "            continue\n"
        "        val = None\n"
        "        for ameth in ('get_value', 'get_z', 'value'):\n"
        "            av = getattr (c, ameth, None)\n"
        "            if av is None:\n"
        "                continue\n"
        "            try:\n"
        "                val = float (av ()) if callable (av) else float (av)\n"
        "                break\n"
        "            except Exception as e:\n"
        "                out.append ('contact__value|' + _n + '|' + ameth + '|'"
        " + str (e)[:80])\n"
        "        out.append ('contact|' + _n + '|' + (repr (val)"
        " if val is not None else 'unknown'))\n"
        "        got = True\n"
        "    if not got:\n"
        "        out.append ('contact|' + _n + '|unknown')\n"
    )
    return code + _writer(out_path)


def reserves_code(grid_name: str, prop_names: tuple[str, ...], out_path) -> str:
    """Суммарные значения свойств-запасов (`compute_statistics(type='sum')`).

    Имена свойств — из ДАННЫХ (`checks.properties.<роль>.cube`); проверяются по
    порядку, первое доступное даёт метрику: ``reserve|<имя>|<сумма>``.
    """
    names = ", ".join(repr(str(n)) for n in (prop_names or ()))
    code = (
        "out = []\n"
        "try:\n"
        f"    g = get_grid_by_name (name='{grid_name}')\n"
        "except Exception as e:\n"
        "    out.append ('__grid_error|' + str (e)[:160])\n"
        "    g = None\n"
        "if g is not None:\n"
        f"    for _n in [{names}]:\n"
        "        try:\n"
        "            p = g.get_property_by_name (name=_n)\n"
        "        except Exception as e:\n"
        "            out.append ('__property_error|' + _n + '|' + str (e)[:100])\n"
        "            continue\n"
        "        try:\n"
        "            v = p.compute_statistics (type='sum')\n"
        "        except Exception as e:\n"
        "            out.append ('__sum_error|' + _n + '|' + str (e)[:100])\n"
        "            continue\n"
        "        if isinstance (v, dict):\n"
        "            v = v.get ('sum')\n"
        "        out.append ('reserve|' + _n + '|' + (repr (float (v))"
        " if isinstance (v, (int, float)) else 'unknown'))\n"
    )
    return code + _writer(out_path)


def parse_report(text: str) -> dict:
    """Разобрать отчёт «ключ|значение» (или «ключ|поле|значение») → словарь.

    Повторяющиеся ключи накапливаются в списки (`property`, `facies`), ошибки
    остаются под своими ключами (`__grid_error`, `p10__error`, …) — правило 6:
    причина недоступности величины сохраняется рядом с величиной.
    """
    multi = {"property", "facies", "contact", "blocked", "stats", "__api_source",
             "__array_source", "__array_try", "__stat_try", "__stat_empty",
             "__stat_ok", "__property_error", "__array_error", "__api_error",
             "__blocked_names"}
    out: dict = {}
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("|")
        key = parts[0].strip()
        if not key:
            continue
        if key in multi:
            if key == "facies" and len(parts) >= 3:
                out.setdefault(key, {})[parts[1].strip()] = _num_or_text(parts[2])
            else:
                out.setdefault(key, []).append("|".join(parts[1:]))
            continue
        out[key] = _num_or_text("|".join(parts[1:])) if len(parts) > 1 else True
    return out


def _num_or_text(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value.strip()


def read_capture(client, *, code: str, tmp: Path,
                 timeout_sec: float | None = None) -> dict:
    """Выполнить сниппет в ОТКРЫТОМ проекте и разобрать tmp-отчёт.

    Возвращает словарь отчёта; при недоступности канала — ``{"__error": текст}``
    (никогда не пустой «нулевой» результат: правило 6).
    """
    proj = getattr(client, "_project", None)
    if proj is None:
        return {"__error": "проект тНава не открыт"}
    tmp = Path(tmp)
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
    except OSError as exc:
        return {"__error": f"не подготовить tmp-файл: {exc}"}
    try:
        proj.run_py_code(code=code)
    except Exception as exc:                      # noqa: BLE001 — причину возвращаем
        return {"__error": f"run_py_code: {type(exc).__name__}: {str(exc)[:200]}"}
    try:
        text = tmp.read_text(encoding="utf-8")
    except OSError as exc:
        return {"__error": f"нет отчёта пробника: {exc}"}
    parsed = parse_report(text)
    if not parsed:
        return {"__error": "отчёт пробника пуст"}
    return parsed


# ============================================================================
# СВИДЕТЕЛЬСТВА РЕЗУЛЬТАТА ЭТАПА (F-19): список свойств, статистики, blocked wells
# ----------------------------------------------------------------------------
# Зачем: гейт должен видеть РЕЗУЛЬТАТ этапа (куб создан? в нём есть данные?),
# иначе проверка существования/непустоты куба не может сработать, и гейт «проходит»
# без результата (приёмочный прогон: гейт фаций = passed при отсутствующем кубе).
#
# Контракт (согласован с foundation, task-9), ключи в `ev` этапа:
#   grid_properties — СПИСОК ИМЁН свойств сетки (имена приходят из проекта тНава);
#   property_stats  — {имя: {count, nulls, cells, min, max, mean, sum, std,
#                             unique_count, classes[]}};
#   blocked_wells   — СПИСОК ИМЁН блокированных логов.
# Правило 6: нет проекта/API/данных → свидетельства НЕТ (None, ключ не пишется),
# а не пустой список-«свойств нет» и не нули.
# ============================================================================
EVIDENCE_KINDS = ("grid_properties", "property_stats", "blocked_wells")

_ARRAY_GETTERS = ("get_np_array", "get_all_values", "get_values", "to_np_array")
# Имена типов статистики ПЕРЕБИРАЮТСЯ: какие поддерживает сборка тНава — те и
# попадают в свидетельство; неподдержанные фиксируются причиной (правило 6).
_STAT_TYPES = ("min", "max", "mean", "sum", "std", "standard_deviation",
               "variance", "median", "count", "non_null_count")
_STAT_REQUIRED = ("min", "max", "mean", "sum")
_CLASSES_MAX_DEFAULT = 64          # предел вывода классов (не домен: размер вывода)


def property_names(cfg) -> list[str]:
    """Имена кубов ИЗ ДАННЫХ: `checks.properties.<роль>.cube` + `ensemble.metric`.

    В коде — только ключи конфигурации; порядок: роли по алфавиту, затем метрика
    ансамбля (если ещё не в списке). Нет данных → пустой список (свидетельство
    не собирается — правило 6).
    """
    if cfg is None:
        return []
    names: list[str] = []
    props = cfg.get("checks.properties")
    if isinstance(props, dict):
        for role in sorted(props):
            item = props.get(role)
            cube = item.get("cube") if isinstance(item, dict) else None
            if cube and str(cube) not in names:
                names.append(str(cube))
    metric = cfg.get("ensemble.metric")
    if metric and str(metric) not in names:
        names.append(str(metric))
    return names


def _stat_tmp(tmp, run_dir, name: str) -> Path:
    """tmp-файл канала «py-код → tmp → разбор» (рядом с прогоном, если задан)."""
    if tmp is not None:
        return Path(tmp)
    base = Path(run_dir) if run_dir is not None else Path.cwd()
    return base / ".qc" / f"{name}.tmp"


def grid_properties_code(grid_name: str, out_path) -> str:
    """Сниппет: список свойств сетки (`get_all_properties`) с типом/шаблоном.

    Отчёт: ``__properties_total|<n>`` (маркер УСПЕШНОГО вызова) и по строке
    ``property|<имя>|<тип или unknown>``. Маркер нужен, чтобы различать
    «свойств нет» (пустой список) и «API недоступен» (свидетельства нет).
    """
    return property_inventory_code(grid_name, out_path).replace(
        "    for p in props:\n",
        "    out.append ('__properties_total|' + str (len (props)))\n"
        "    for p in props:\n")


def blocked_wells_code(out_path, grid_name: str = "") -> str:
    """Сниппет: список блокированных логов (`get_all_blocked_wells` и родственные).

    Живая проба показала: имя из каталога (`get_all_blocked_wells`) в «сыром» py-коде
    НЕ определено (`NameError`), поэтому сниппет СНАЧАЛА перечисляет доступные имена
    с «blocked» из модуля воркфлоу, затем пробует кандидатов по очереди (в т.ч. через
    объект сетки). Что сработало — то и свидетельство; причины — в отчёт (правило 6).
    Отчёт: ``__blocked_names|<имена>`` (что вообще есть), ``__blocked_total|<n>``
    (маркер успешного вызова) и ``blocked|<имя>``.
    """
    grid_arg = f"'{grid_name}'" if grid_name else "''"
    code = (
        "out = []\n"
        "try:\n"
        "    from __main__.tnav import workflow as _wf\n"
        "    _names = sorted (n for n in dir (_wf) if 'blocked' in n.lower ())\n"
        "    out.append ('__blocked_names|' + ','.join (_names))\n"
        "except Exception as e:\n"
        "    out.append ('__blocked_names|ERR ' + type (e).__name__ + ': ' + str (e)[:100])\n"
        "bws = None\n"
        "for _fn in ('get_all_blocked_wells', 'get_all_blocked_wells_logs',\n"
        "            'get_all_blocked_well_logs', 'get_all_blockedwells',\n"
        "            'get_blocked_wells_names'):\n"
        "    if bws is not None:\n"
        "        break\n"
        "    fn = globals ().get (_fn)\n"
        "    if fn is None:\n"
        "        out.append ('__api_try|' + _fn + '|не найдена')\n"
        "        continue\n"
        "    try:\n"
        "        bws = list (fn ())\n"
        "        out.append ('__api_source|' + _fn)\n"
        "    except Exception as e:\n"
        "        out.append ('__api_try|' + _fn + '|' + type (e).__name__ + ': '"
        " + str (e)[:100])\n"
        f"_grid_name = {grid_arg}\n"
        "if bws is None and _grid_name:\n"
        "    try:\n"
        "        _g = get_grid_by_name (name=_grid_name)\n"
        "        bws = list (_g.get_all_blocked_wells ())\n"
        "        out.append ('__api_source|grid.get_all_blocked_wells')\n"
        "    except Exception as e:\n"
        "        out.append ('__api_try|grid.get_all_blocked_wells|'"
        " + type (e).__name__ + ': ' + str (e)[:100])\n"
        "if bws is not None:\n"
        "    out.append ('__blocked_total|' + str (len (bws)))\n"
        "    for _i, _b in enumerate (bws):\n"
        "        _nm = getattr (_b, 'name', '')\n"
        "        if not isinstance (_nm, str) or not _nm:\n"
        "            _nm = 'blocked_' + str (_i)\n"
        "        out.append ('blocked|' + _nm)\n"
    )
    return code + _writer(out_path)


def property_stats_code(grid_name: str, prop_names, out_path,
                        classes_max: int = _CLASSES_MAX_DEFAULT) -> str:
    """Сниппет статистики кубов: count/nulls/cells + min/max/mean/sum/std + классы.

    Числа берутся ЧЕСТНО: `compute_statistics` даёт min/max/mean/sum/std, а
    количество ячеек и пустых — из массива куба (перебор геттеров). Если массив
    недоступен, `count/null` в отчёт НЕ попадают (проверка непустоты честно уйдёт
    в `not_applicable`, а не в «прошло»). Имена кубов — аргумент из данных.
    """
    names = ", ".join(repr(str(n)) for n in (prop_names or ()))
    code = (
        "out = []\n"
        "try:\n"
        "    import numpy as _np\n"
        "except Exception as e:\n"
        "    out.append ('__numpy_error|' + str (e)[:120])\n"
        "    _np = None\n"
        "try:\n"
        f"    _g = get_grid_by_name (name='{grid_name}')\n"
        "except Exception as e:\n"
        "    out.append ('__grid_error|' + str (e)[:160])\n"
        "    _g = None\n"
        "if _g is not None:\n"
        f"    for _n in [{names}]:\n"
        "        try:\n"
        "            _p = _g.get_property_by_name (name=_n)\n"
        "        except Exception as e:\n"
        "            out.append ('__property_error|' + _n + '|' + str (e)[:140])\n"
        "            continue\n"
        "        _parts = []\n"
        "        _ok_types = []\n"
        "        for _t in " + repr(list(_STAT_TYPES)) + ":\n"
        "            try:\n"
        "                _v = _p.compute_statistics (type=_t)\n"
        "                if isinstance (_v, dict):\n"
        "                    _v = _v.get (_t)\n"
        "                if isinstance (_v, (int, float)):\n"
        "                    _parts.append (_t + '=' + repr (float (_v)))\n"
        "                    _ok_types.append (_t)\n"
        "                else:\n"
        "                    out.append ('__stat_empty|' + _n + '|' + _t)\n"
        "            except Exception as e:\n"
        "                out.append ('__stat_try|' + _n + '|' + _t + '|' + str (e)[:80])\n"
        "        out.append ('__stat_ok|' + _n + '|' + ','.join (_ok_types))\n"
        "        _arr = None\n"
        "        if _np is not None:\n"
        "            for _m in " + repr(list(_ARRAY_GETTERS)) + ":\n"
        "                _fn = getattr (_p, _m, None)\n"
        "                if _fn is None or _arr is not None:\n"
        "                    continue\n"
        "                try:\n"
        "                    _arr = _np.asarray (_fn (), dtype=float).reshape (-1)\n"
        "                    out.append ('__array_source|' + _n + '|' + _m)\n"
        "                except Exception as e:\n"
        "                    out.append ('__array_try|' + _n + '|' + _m + '|'"
        " + str (e)[:80])\n"
        "        if _arr is not None:\n"
        "            _fin = _arr[_np.isfinite (_arr)]\n"
        "            _cells = int (_arr.size)\n"
        "            _cnt = int (_fin.size)\n"
        "            _parts.append ('cells=' + repr (_cells))\n"
        "            _parts.append ('count=' + repr (_cnt))\n"
        "            _parts.append ('nulls=' + repr (_cells - _cnt))\n"
        "            if _cells:\n"
        "                _parts.append ('nonempty_fraction=' + repr (float (_cnt) / _cells))\n"
        "            if _cnt:\n"
        "                _uniq = _np.unique (_fin)\n"
        "                _parts.append ('unique_count=' + repr (int (_uniq.size)))\n"
        f"                if _uniq.size <= {int(classes_max)}:\n"
        "                    _parts.append ('classes=' + ','.join ("
        "repr (float (v)) for v in _uniq))\n"
        "                else:\n"
        "                    # классы НЕ перечислены (их слишком много) — это НЕ «пусто»:\n"
        "                    _parts.append ('classes_truncated=1')\n"
        "        else:\n"
        "            out.append ('__array_error|' + _n + '|массив куба недоступен')\n"
        "        out.append ('stats|' + _n + '|' + ';'.join (_parts))\n"
    )
    return code + _writer(out_path)


def parse_grid_properties(report: dict) -> list[str] | None:
    """`grid_properties` = список имён свойств; None — свидетельства нет.

    Пустой список возвращается ТОЛЬКО когда API ответил (маркер
    ``__properties_total``) и свойств действительно нет: «свойств нет» — это факт,
    а «API недоступен» — отсутствие свидетельства (правило 6).
    """
    if not isinstance(report, dict) or "__error" in report:
        return None
    if "__properties_total" not in report:
        return None
    names: list[str] = []
    for row in _rows(report, "property"):
        name = row.split("|", 1)[0].strip()
        if name:
            names.append(name)
    return names


def _rows(report: dict, key: str) -> list[str]:
    """Строки отчёта по ключу: принимает и список, и одиночную строку."""
    value = report.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def parse_property_stats(report: dict) -> dict | None:
    """`property_stats` = {имя: {метрики}}; None — свидетельства нет."""
    if not isinstance(report, dict) or "__error" in report:
        return None
    rows = _rows(report, "stats")
    if not rows:
        return None
    out: dict = {}
    for row in rows:
        name, _, rest = row.partition("|")
        name = name.strip()
        if not name:
            continue
        item: dict = {}
        for pair in rest.split(";"):
            key, _, value = pair.partition("=")
            key = key.strip()
            if not key:
                continue
            if key == "classes":
                classes: list[float] = []
                for token in value.split(","):
                    try:
                        classes.append(float(token))
                    except ValueError:
                        continue
                item[key] = classes
                continue
            try:
                item[key] = float(value)
            except ValueError:
                item[key] = value.strip()
        reasons = [row for row in _rows(report, "__stat_try")
                   if row.startswith(f"{name}|")]
        reasons += [row for row in _rows(report, "__property_error")
                    if row.startswith(f"{name}|")]
        if reasons:
            item["notes"] = reasons[:5]
        sources = [row.split("|")[-1] for row in _rows(report, "__array_source")
                   if row.startswith(f"{name}|")]
        if sources:
            item["cells_api"] = sources[0]
        out[name] = item
    return out or None


def parse_blocked_wells(report: dict) -> list[str] | None:
    """`blocked_wells` = список имён блокированных логов; None — свидетельства нет."""
    if not isinstance(report, dict) or "__error" in report:
        return None
    if "__blocked_total" not in report:
        return None
    return [row.strip() for row in _rows(report, "blocked") if row.strip()]


def read_grid_properties(client, *, grid_name: str, tmp=None, run_dir=None
                         ) -> list[str] | None:
    """Свидетельство `grid_properties` (None — нет проекта/API)."""
    if not grid_name:
        return None
    path = _stat_tmp(tmp, run_dir, "grid_properties")
    report = read_capture(client, code=grid_properties_code(grid_name, path), tmp=path)
    return parse_grid_properties(report)


def read_property_stats(client, *, grid_name: str, names=None, cfg=None,
                        tmp=None, run_dir=None) -> dict | None:
    """Свидетельство `property_stats` (имена кубов — данные `checks.properties`)."""
    if names is None:
        names = property_names(cfg)
    names = [str(n) for n in (names or []) if str(n)]
    if not grid_name or not names:
        return None
    path = _stat_tmp(tmp, run_dir, "property_stats")
    report = read_capture(client,
                          code=property_stats_code(grid_name, names, path), tmp=path)
    return parse_property_stats(report)


def read_blocked_wells(client, *, grid_name: str = "", tmp=None, run_dir=None
                       ) -> list[str] | None:
    """Свидетельство `blocked_wells` (None — нет проекта/API/способа получить)."""
    path = _stat_tmp(tmp, run_dir, "blocked_wells")
    report = read_capture(client, code=blocked_wells_code(path, grid_name), tmp=path)
    return parse_blocked_wells(report)
