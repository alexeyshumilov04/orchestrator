"""Проба CONSOLE-SAFE карт тНава (E9): `map_2d_create_by_grid_property` + экспорт.

Задача инструмента — не «угадать», а ПОЛУЧИТЬ ОТ тНава точную сигнатуру: builtin'ы
валидируют вызов и сами называют недостающий/неверный аргумент (методика v7,
`orchestrator_v7/orchestrator/docs/tasks/B4_facies.md`, раунды 15–21).

Что проверяется в ОДНОЙ сессии тНава (копия реального проекта с сеткой и кубами):
  * инвентарь: свойства сетки (`get_all_properties`) и список 2D-карт проекта;
  * `map_2d_create_by_grid_property` — сигнатура (кандидат взят из РЕАЛЬНОГО
    воркфлоу тНава `tutorials/GM1.1_.../Geomechanics_workflow.py`, index 154 —
    источник достовернее каталога и курсов, правило 8);
  * `map_2d_export_cps_format` — сигнатура эталона v26.1
    (`domain/ontology_rules/reference_workflow.py`, index 3) + файл на диске;
  * `map_2d_export_ascii_format` — перебор вариантов (в эталоне только CPS);
  * `map_2d_statistic` — перебор вариантов.

Никаких значений поля в этом файле нет: имена сетки/куба/карты приходят
аргументами командной строки, а по умолчанию — из ДАННЫХ (проектный YAML).

Запуск:
    python -X utf8 tools/probe_maps.py --project <путь к .snp> --grid main_grid \
        --cube PORO --out _probe_maps.txt
Результат: текстовый отчёт (по строке на вариант) + список файлов в каталоге карт.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_config                        # noqa: E402
from domain.tnav_client import TnavClient                  # noqa: E402

PROBE_DIR_NAME = "_probe_maps"
WF_DIR_NAME = "_probe_wf"


def _q(path) -> str:
    return str(path).replace("\\", "/")


def _workflow_item_probe(*, grid: str, cube: str, map_name: str, export_dir: str,
                         with_expression: bool) -> str:
    """Проба элемента ВОРКФЛОУ (`begin_wf_item`): что тНав принимает внутри item.

    Реальный прогон 26.2 дал «Error near line N: Could not recognize python code
    as workflow item» на `import os` ВНУТРИ элемента. Здесь проверяются два
    варианта: (W1) элемент ровно из вызова функции тНава и (W2) элемент с
    БЕЗЫМПОРТНОЙ формой `__import__("os").makedirs(...)` вместо `import`.
    Каталог выгрузки при этом создаётся ЗАРАНЕЕ обычным Python (вне элементов).
    """
    code = "out = []\n"
    code += (
        "import os\n"
        "try:\n"
        "    os.makedirs (os.path.join (get_project_folder (), r'" + export_dir + "'),"
        " exist_ok=True)\n"
        "    out.append ('pre-mkdir (вне элемента): OK')\n"
        "except Exception as e:\n"
        "    out.append ('pre-mkdir ERR: ' + str (e)[:160])\n"
    )
    code += (
        "try:\n"
        f"    map_2d_create_by_grid_property (grid=find_object (name='{grid}',"
        f" type='Grid3d'), continuous_properties=True,"
        f" continues_cube_and_map_table=[{{'use': True,"
        f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
        f" 'map_2d': find_object (name='{map_name}', type='Map2d'),"
        f" 'method': 'average'}}])\n"
        "    out.append ('create Map2d (вне элемента): OK')\n"
        "except Exception as e:\n"
        "    out.append ('create ERR: ' + type (e).__name__ + ': ' + str (e)[:200])\n"
    )
    if not with_expression:
        code += (
            "try:\n"
            "    begin_wf_item (index = 901)\n"
            f"    map_2d_export_ascii_format (file_name='{export_dir}/{map_name}_w1.txt',"
            f" map_2d=find_object (name='{map_name}', type='Map2d'),"
            f" default_value=9999900, units_system='metric')\n"
            "    end_wf_item (index = 901)\n"
            "    out.append ('W1 item (только вызов тНава): OK')\n"
            "except Exception as e:\n"
            "    out.append ('W1 item: ' + type (e).__name__ + ': ' + str (e)[:220])\n"
        )
    else:
        code += (
            "try:\n"
            "    begin_wf_item (index = 902)\n"
            "    __import__('os').makedirs (__import__('os').path.join"
            f" (get_project_folder (), '{export_dir}'), exist_ok=True)\n"
            f"    map_2d_export_ascii_format (file_name='{export_dir}/{map_name}_w2.txt',"
            f" map_2d=find_object (name='{map_name}', type='Map2d'),"
            f" default_value=9999900, units_system='metric')\n"
            "    end_wf_item (index = 902)\n"
            "    out.append ('W2 item (__import__-выражение): OK')\n"
            "except Exception as e:\n"
            "    out.append ('W2 item: ' + type (e).__name__ + ': ' + str (e)[:220])\n"
        )
    code += (
        "try:\n"
        f"    _pd = os.path.join (get_project_folder (), r'{export_dir}')\n"
        "    out.append ('files: ' + '|'.join (sorted (os.listdir (_pd))))\n"
        "except Exception as e:\n"
        "    out.append ('files ERR: ' + str (e)[:140])\n"
    )
    code += "open (r'__OUT__', 'w', encoding='utf-8').write ('\\n'.join (out))\n'ok'\n"
    return code


def build_code(*, grid: str, cube: str, map_name: str, export_dir: str) -> str:
    """Собрать py-код пробы: инвентарь + варианты вызовов (статические try/except)."""
    variants: list[tuple[str, str]] = []

    # --- map_2d_create_by_grid_property: сигнатура (источник — воркфлоу GM1.1) ---
    create_head = f"map_2d_create_by_grid_property (grid=find_object (name='{grid}', type='Grid3d')"
    g2d = ("grid_2d_settings=Grid2DSettings (grid_2d_settings_shown=True, "
           "autodetect_box=True, min_x=0, min_y=0, length_x=1000, length_y=1000, "
           "margin_x=0, margin_y=0, consider_blank_nodes=False, autodetect_angle=False, "
           "angle=0, autodetect_grid=False, grid_adjust_mode='step', step_x=100, "
           "step_y=100, counts_x=10, counts_y=10, "
           "sample_object=absolute_object_name (name=None, typed_names=[]), "
           "autodetect_during_wf_calculation=True)")
    create_full = (
        f", use_user_cut=False,"
        f" user_cut=find_object (name='', type='Grid3dProperty'),"
        f" comparator=Comparator (rule='equals', value=0),"
        f" use_user_cut_second=False,"
        f" user_cut_second=find_object (name='', type='Grid3dProperty'),"
        f" comparator_second=Comparator (rule='equals', value=0),"
        f" use_zone=False, zone=find_object (name='', type='Grid3dProperty'),"
        f" continuous_properties=True,"
        f" continues_cube_and_map_table=[{{'use': True,"
        f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
        f" 'map_2d': find_object (name='{map_name}', type='Map2d'),"
        f" 'zone_id': 0, 'method': 'average', 'smooth': False, 'blocked_wells': None}}],"
        f" discrete_properties=False, discrete_cube_and_map_table=[],"
        f" smoothing_radius=10, ignore_faults=False, set_na_instead_of_zero=False,"
        f" compatibility_options=False, set_na_outside_filter=True,"
        f" grid_2d_source='from_grid', add_half_cell_offset=True, subdivision=1,"
        f" {g2d})")
    variants += [
        ("V1 create: без аргументов", "map_2d_create_by_grid_property ()"),
        ("V2 create: только grid", create_head + ")"),
        ("V3 create: grid+cube+map (таблица)",
         create_head + f", continuous_properties=True, "
                       f"continues_cube_and_map_table=[{{'use': True,"
                       f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
                       f" 'map_2d': find_object (name='{map_name}', type='Map2d'),"
                       f" 'zone_id': 0, 'method': 'average', 'smooth': False,"
                       f" 'blocked_wells': None}}])"),
        ("V4 create: полная сигнатура (GM1.1)", create_head + create_full),
        ("V5 create: неверный аргумент", create_head + ", bogus=1)"),
    ]

    # --- экспорт CPS (сигнатура из эталона v26.1) -----------------------------
    for tag, args in [
        ("E1 cps: без аргументов", ""),
        ("E2 cps: эталон (file_name+map_2d+default_value+units_system)",
         f"file_name='{export_dir}/{map_name}.txt',"
         f" map_2d=find_object (name='{map_name}', type='Map2d'),"
         f" default_value=99999, units_system='metric'"),
        ("E3 cps: только file_name+map_2d",
         f"file_name='{export_dir}/{map_name}.txt',"
         f" map_2d=find_object (name='{map_name}', type='Map2d')"),
    ]:
        variants.append((tag, f"map_2d_export_cps_format ({args})"))

    # --- экспорт ASCII (в эталоне нет; перебор кандидатов) --------------------
    ascii_cands = [
        ("EA1 ascii: без аргументов", ""),
        ("EA2 ascii: folder", f"folder='{export_dir}'"),
        ("EA3 ascii: file_name+map_2d",
         f"file_name='{export_dir}/{map_name}_a.txt',"
         f" map_2d=find_object (name='{map_name}', type='Map2d')"),
        ("EA4 ascii: folder+maps_table",
         f"folder='{export_dir}', maps_table=[find_object (name='{map_name}', type='Map2d')]"),
        ("EA5 ascii: folder+table",
         f"folder='{export_dir}', table=[{{'use': True,"
         f" 'map_2d': find_object (name='{map_name}', type='Map2d')}}]"),
        ("EA6 ascii: file_names_table",
         f"folder='{export_dir}', file_names_table=[{{'use': True,"
         f" 'map_2d': find_object (name='{map_name}', type='Map2d'),"
         f" 'file_name': '{map_name}_b.txt'}}]"),
        ("EA7 ascii: path+default_value+units_system",
         f"path='{export_dir}', default_value=99999, units_system='metric'"),
    ]
    variants += [(tag, f"map_2d_export_ascii_format ({args})") for tag, args in ascii_cands]

    # --- статистика по набору карт -------------------------------------------
    variants += [
        ("S1 statistic: без аргументов", "map_2d_statistic ()"),
        ("S2 statistic: карты+тип",
         f"map_2d_statistic (maps_table=[find_object (name='{map_name}', type='Map2d')],"
         f" statistics_type='mean')"),
        ("S3 statistic: result+source",
         f"map_2d_statistic (result_map_2d=find_object (name='{map_name}_stat', type='Map2d'),"
         f" maps=[find_object (name='{map_name}', type='Map2d')])"),
    ]

    # --- РАУНД 2: карта из СУЩЕСТВУЮЩЕГО куба донора + экспорт файла ----------
    # Куб донора может быть ДИСКРЕТНЫМ (`zone_id`), поэтому проверяются обе
    # таблицы вызова: непрерывная и дискретная (обе есть в воркфлоу GM1.1).
    disc_map = f"{map_name}_D"
    variants += [
        ("V6 create: дискретная таблица (куб донора)",
         create_head + f", continuous_properties=False, continues_cube_and_map_table=[],"
                       f" discrete_properties=True,"
                       f" discrete_cube_and_map_table=[{{'use': True,"
                       f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
                       f" 'map_2d': find_object (name='{disc_map}', type='Map2d'),"
                       f" 'zone_id': 0, 'method': 'average', 'smooth': False,"
                       f" 'blocked_wells': None}}], {g2d})"),
        ("V7 create: непрерывная таблица без grid_2d_settings",
         create_head + f", continuous_properties=True,"
                       f" continues_cube_and_map_table=[{{'use': True,"
                       f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
                       f" 'map_2d': find_object (name='{map_name}', type='Map2d'),"
                       f" 'zone_id': 0, 'method': 'average', 'smooth': False,"
                       f" 'blocked_wells': None}}])"),
    ]
    # экспорт ТОЛЬКО ЧТО созданной карты: CPS (сигнатура эталона) и ASCII (перебор)
    variants += [
        ("E4 cps: экспорт созданной карты",
         f"map_2d_export_cps_format (file_name='{export_dir}/cps_map.txt',"
         f" map_2d=find_object (name='{map_name}', type='Map2d'),"
         f" default_value=99999, units_system='metric')"),
        ("EA8 ascii: file_name+map_2d+default_value+units_system",
         f"map_2d_export_ascii_format (file_name='{export_dir}/ascii_map.txt',"
         f" map_2d=find_object (name='{map_name}', type='Map2d'),"
         f" default_value=99999, units_system='metric')"),
        ("EA9 ascii: только file_name+map_2d",
         f"map_2d_export_ascii_format (file_name='{export_dir}/ascii2_map.txt',"
         f" map_2d=find_object (name='{map_name}', type='Map2d'))"),
        ("V8 create: дискретная таблица, method=most_of",
         create_head + f", continuous_properties=False, continues_cube_and_map_table=[],"
                       f" discrete_properties=True,"
                       f" discrete_cube_and_map_table=[{{'use': True,"
                       f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
                       f" 'map_2d': find_object (name='{disc_map}', type='Map2d'),"
                       f" 'zone_id': 0, 'method': 'most_of', 'smooth': False,"
                       f" 'blocked_wells': None}}])"),
        ("E5 cps: экспорт дискретной карты",
         f"map_2d_export_cps_format (file_name='{export_dir}/cps_disc.txt',"
         f" map_2d=find_object (name='{disc_map}', type='Map2d'),"
         f" default_value=99999, units_system='metric')"),
    ]
    # map_2d_statistic: `result_map` подтверждён пробой (SR1 = OK); ищем параметр
    # НАБОРА исходных карт (метка «Result 2D-Map» относится к результату).
    variants += [("SR0 statistic: result_map (подтверждено)", "map_2d_statistic (result_map=find_object (name='%s_s', type='Map2d'))" % map_name)]
    for i, arg in enumerate(("maps_table",), start=1):
        for key in ("2d_map", "map_2d", "map", "2D-Maps", "use"):
            variants.append((f"ST{i} statistic: maps_table row[{key}]",
                             f"map_2d_statistic (result_map=find_object (name='{map_name}_s',"
                             f" type='Map2d'), maps_table=[{{'{key}':"
                             f" find_object (name='{map_name}', type='Map2d')}}])"))
    # создание карты БЕЗ колонки чужого проекта `zone_id` в строке таблицы
    variants += [
        ("V9 create: строка без zone_id",
         create_head + f", continuous_properties=True,"
                       f" continues_cube_and_map_table=[{{'use': True,"
                       f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
                       f" 'map_2d': find_object (name='{map_name}_nz', type='Map2d'),"
                       f" 'method': 'average', 'smooth': False,"
                       f" 'blocked_wells': None}}])"),
        ("V10 create: строка только use/cube/map_2d/method",
         create_head + f", continuous_properties=True,"
                       f" continues_cube_and_map_table=[{{'use': True,"
                       f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
                       f" 'map_2d': find_object (name='{map_name}_nz2', type='Map2d'),"
                       f" 'method': 'average'}}])"),
    ]

    code = "out = []\n"
    code += (
        "try:\n"
        "    import os\n"
        "except Exception as e:\n"
        "    out.append ('os ERR: ' + str (e)[:120])\n"
    )
    # каталог ПРОЕКТА: тНав разрешает относительный file_name от папки проекта, но
    # создавать папку нужно ЯВНО и в правильном каталоге (иначе «Can't open file»).
    # Подтверждено пробой: `get_project_folder ()` возвращает папку проекта.
    code += "pdir = ''\n"
    for expr in ("get_project_folder ()", "get_project_path ()", "get_project_dir ()",
                 "os.getcwd ()"):
        code += (
            "try:\n"
            f"    _v = {expr}\n"
            "    out.append ('pdir: " + expr + " = ' + str (_v)[:160])\n"
            "    if isinstance (_v, str) and _v and not pdir:\n"
            "        pdir = _v.rstrip ('/\\\\')\n"
            "except Exception as e:\n"
            "    out.append ('pdir: " + expr + " ERR: ' + str (e)[:80])\n"
        )
    # папка выгрузки: относительный file_name тНав разрешает от ПАПКИ ПРОЕКТА,
    # поэтому создаём её явно по найденному каталогу проекта (иначе «Can't open file»).
    code += (
        "try:\n"
        "    for _base in ([pdir] if pdir else []) + [os.getcwd ()]:\n"
        f"        _d = os.path.join (_base, r'{export_dir}')\n"
        "        try:\n"
        "            os.makedirs (_d, exist_ok=True)\n"
        "            out.append ('mkdir ok: ' + _d)\n"
        "        except Exception as e:\n"
        "            out.append ('mkdir ERR ' + _d + ': ' + str (e)[:100])\n"
        "except Exception as e:\n"
        "    out.append ('mkdir ERR: ' + str (e)[:120])\n"
    )
    # инвентарь: свойства сетки и карты проекта
    code += (
        "try:\n"
        f"    g = get_grid_by_name (name='{grid}')\n"
        "    props = [str (getattr (p, 'name', p)) for p in g.get_all_properties ()]\n"
        "    out.append ('props: ' + '|'.join (props))\n"
        "except Exception as e:\n"
        "    out.append ('props ERR: ' + str (e)[:200])\n"
    )
    for tag, expr in [("maps: get_all_maps ()", "get_all_maps ()"),
                      ("maps: get_all_maps_2d ()", "get_all_maps_2d ()")]:
        code += (
            "try:\n"
            f"    ms = {expr}\n"
            "    out.append ('" + tag + ": ' + str (len (ms)) + ' -> ' +"
            " '|'.join (sorted (str (getattr (m, 'name', m)) for m in ms)[:20]))\n"
            "except Exception as e:\n"
            "    out.append ('" + tag + " ERR: ' + str (e)[:120])\n"
        )
    for tag, call in variants:
        # БЕЗ `repr` на объектах API: repr ронял задачу тНава (access violation).
        code += (
            "try:\n"
            f"    {call}\n"
            f"    out.append ('{tag}: OK')\n"
            "except Exception as e:\n"
            f"    out.append ('{tag}: ' + type (e).__name__ + ': ' + str (e)[:220])\n"
            "try:\n"
            "    open (r'__OUT__', 'w', encoding='utf-8').write ('\\n'.join (out))\n"
            "except Exception as e:\n"
            "    out.append ('report write ERR: ' + str (e)[:80])\n"
        )
    code += (
        "try:\n"
        f"    _mdir = os.path.join (pdir, r'{export_dir}') if pdir else r'{export_dir}'\n"
        "    files = sorted (os.listdir (_mdir))\n"
        "    out.append ('files in ' + _mdir + ': ' + '|'.join (files[:20]))\n"
        "    for _f in files[:5]:\n"
        "        _p = os.path.join (_mdir, _f)\n"
        "        _n = os.path.getsize (_p)\n"
        "        _head = open (_p, 'r', encoding='utf-8', errors='replace').readlines ()[:3]\n"
        "        out.append ('file ' + _f + ' bytes=' + str (_n) + ' head=' +"
        " ' / '.join (x.strip ()[:60] for x in _head))\n"
        "except Exception as e:\n"
        "    out.append ('files ERR: ' + str (e)[:120])\n"
    )
    # инвентарь всех сетей проекта и их свойств (донор может держать кубы не на main_grid)
    for tag, expr in [("grids: get_all_grids ()", "get_all_grids ()"),
                      ("grids: get_all_grid_names ()", "get_all_grid_names ()")]:
        code += (
            "try:\n"
            f"    gs = {expr}\n"
            "    out.append ('" + tag + ": ' + '|'.join (sorted (str (getattr (x, 'name', x))"
            " for x in gs)))\n"
            "except Exception as e:\n"
            "    out.append ('" + tag + " ERR: ' + str (e)[:120])\n"
        )
    code += "open (r'__OUT__', 'w', encoding='utf-8').write ('\\n'.join (out))\n'ok'\n"
    return code


def _item_workflow_file(*, grid: str, cube: str, map_name: str, export_dir: str,
                        file_name: str, with_expression: bool) -> str:
    """Собрать НАСТОЯЩИЙ файл воркфлоу тНава (обёртка + элементы) для пробы item'ов.

    Отличие от `run_py_code` с «сырым» кодом: только в файле с `declare_workflow` /
    `check_launch_method` функции `begin_wf_item`/`end_wf_item` доступны по-настоящему
    (в сыром коде тНав подменяет их заглушкой
    `restricted_func_was_used_here_and_was_replaced_to_avoid_data_loss`).
    Элемент 1 создаёт Map2d из куба, элемент 2 — выгружает её (вариант: с
    безымпортным `__import__("os").makedirs(...)` вместо `import`).
    """
    from domain.workflow_renderer import WorkflowBuilder

    create_block = (
        "    begin_wf_item (index = 1)\n"
        f"    map_2d_create_by_grid_property (grid=find_object (name='{grid}',"
        f" type='Grid3d'), continuous_properties=True,"
        f" continues_cube_and_map_table=[{{'use': True,"
        f" 'cube': find_object (name='{cube}', type='Grid3dProperty'),"
        f" 'map_2d': find_object (name='{map_name}', type='Map2d'),"
        f" 'method': 'average'}}])\n"
        "    end_wf_item (index = 1)\n"
    )
    lines = ["    begin_wf_item (index = 2)"]
    if with_expression:
        lines.append("    __import__('os').makedirs (__import__('os').path.join"
                     f" (get_project_folder (), '{export_dir}'), exist_ok=True)")
    lines.append(f"    map_2d_export_ascii_format (file_name='{file_name}',"
                 f" map_2d=find_object (name='{map_name}', type='Map2d'),"
                 f" default_value=9999900, units_system='metric')")
    lines.append("    end_wf_item (index = 2)")
    export_block = "\n".join(lines) + "\n"

    builder = WorkflowBuilder(
        wrapper=ROOT / "domain" / "templates" / "template_wf.txt",
        templates_dir=ROOT / "domain" / "templates")
    return builder.assemble([create_block, export_block])


def _map_check_file(*, grid: str, cube: str, map_name: str, export_dir: str,
                    variant: str) -> tuple[str, str]:
    """Файл воркфлоу для F-18: один вариант создания карты + выгрузка.

    Варианты (все — кандидаты, подтверждаются прогоном, правило 8):
      ``v1`` — ТОЧНАЯ форма шаблона (полный список аргументов + Grid2DSettings);
      ``v2`` — минимальная подтверждённая форма (``continuous_properties`` + таблица);
      ``v3`` — как v2, но без ``method`` в строке таблицы;
      ``v4`` — как v2 + фильтр блоков ``use_user_cut`` с компаратором (кандидат).
    Возвращает ``(текст_воркфлоу, имя_файла_выгрузки)``.
    """
    from domain.workflow_renderer import WorkflowBuilder

    file_name = f"{export_dir}/{map_name}_{variant}.txt"
    row_base = (f"{{'use': True, 'cube': find_object (name='{cube}',"
                f" type='Grid3dProperty'), 'map_2d': find_object (name='{map_name}_{variant}',"
                f" type='Map2d')")
    g2d = ("Grid2DSettings (grid_2d_settings_shown=True, autodetect_box=True, min_x=0, "
           "min_y=0, length_x=1000, length_y=1000, margin_x=0, margin_y=0, "
           "consider_blank_nodes=False, autodetect_angle=False, angle=0, "
           "autodetect_grid=False, grid_adjust_mode='step', step_x=100, step_y=100, "
           "counts_x=10, counts_y=10, sample_object=absolute_object_name (name=None, "
           "typed_names=[]), autodetect_during_wf_calculation=True)")
    if variant == "v1":
        call = (
            f"map_2d_create_by_grid_property (grid=find_object (name='{grid}',"
            f" type='Grid3d'), use_user_cut=False,"
            f" user_cut=find_object (name='', type='Grid3dProperty'),"
            f" comparator=Comparator (rule='equals', value=2), use_user_cut_second=False,"
            f" user_cut_second=find_object (name='', type='Grid3dProperty'),"
            f" comparator_second=Comparator (rule='not_equals', value=0), use_zone=False,"
            f" zone=find_object (name='', type='Grid3dProperty'),"
            f" continuous_properties=True,"
            f" continues_cube_and_map_table=[{row_base}, 'method': 'average',"
            f" 'smooth': False, 'blocked_wells': None}}], discrete_properties=False,"
            f" discrete_cube_and_map_table=[], smoothing_radius=10, ignore_faults=False,"
            f" set_na_instead_of_zero=False, compatibility_options=False,"
            f" set_na_outside_filter=True, grid_2d_source='from_grid',"
            f" add_half_cell_offset=True, subdivision=1, grid_2d_settings={g2d})")
    elif variant == "v3":
        call = (f"map_2d_create_by_grid_property (grid=find_object (name='{grid}',"
                f" type='Grid3d'), continuous_properties=True,"
                f" continues_cube_and_map_table=[{row_base}}}])")
    elif variant == "v4":
        call = (f"map_2d_create_by_grid_property (grid=find_object (name='{grid}',"
                f" type='Grid3d'), use_user_cut=True,"
                f" user_cut=find_object (name='{cube}', type='Grid3dProperty'),"
                f" comparator=Comparator (rule='greater', value=0),"
                f" continuous_properties=True,"
                f" continues_cube_and_map_table=[{row_base}, 'method': 'average'}}])")
    else:                                                   # v2 — минимальная форма
        call = (f"map_2d_create_by_grid_property (grid=find_object (name='{grid}',"
                f" type='Grid3d'), continuous_properties=True,"
                f" continues_cube_and_map_table=[{row_base}, 'method': 'average'}}])")
    create_block = ("    begin_wf_item (index = 1)\n"
                    f"    {call}\n"
                    "    end_wf_item (index = 1)\n")
    export_block = ("    begin_wf_item (index = 2)\n"
                    f"    map_2d_export_ascii_format (file_name='{file_name}',"
                    f" map_2d=find_object (name='{map_name}_{variant}', type='Map2d'),"
                    f" default_value=9999900, units_system='metric')\n"
                    "    end_wf_item (index = 2)\n")
    builder = WorkflowBuilder(
        wrapper=ROOT / "domain" / "templates" / "template_wf.txt",
        templates_dir=ROOT / "domain" / "templates")
    return builder.assemble([create_block, export_block]), file_name


def _redirect_appdata(target: Path) -> str:
    """Перенести %APPDATA%/%TEMP% тНава в рабочую папку (права на запись у процессов тНава).

    Процессы тНава (`tNavigator-API-client.exe`, local dispatcher, встроенный Python)
    пишут log-файлы и рабочие каталоги в `%APPDATA%\\tNavigator` и `%TEMP%`; вне
    рабочей папки у них нет права записи — подключение/проект падают с «Отказано в
    доступе» (`local_dispatcher_*.log`, `tnav_py_run_*`). Переносим `APPDATA`, `TMP`
    и `TEMP` на каталоги ВНУТРИ рабочей папки: настройки лицензии (`tNavigator.ini`)
    переносятся копией, все временные файлы остаются рядом с прогоном.
    """
    target = Path(target)
    (target / "tNavigator").mkdir(parents=True, exist_ok=True)
    for sub in ("api_server", "local_dispatcher", "ai_server"):
        (target / "tNavigator" / sub).mkdir(parents=True, exist_ok=True)
    original = Path(os.environ.get("APPDATA") or "")
    src_ini = original / "tNavigator" / "tNavigator.ini"
    dst_ini = target / "tNavigator" / "tNavigator.ini"
    if src_ini.is_file() and not dst_ini.is_file():
        shutil.copy2(src_ini, dst_ini)
    os.environ["APPDATA"] = str(target)
    temp = target / "Temp"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(temp)
    os.environ["TEMP"] = str(temp)
    return str(target)


def _evidence_run(client, cfg, *, grid: str, extra_names=()) -> dict:
    """Снять свидетельства гейтов (task-10): свойства, статистики, blocked wells.

    Возвращается словарь ровно в том виде, в каком его ждёт `ev` этапа
    (контракт согласован с foundation): отсутствие проекта/API/данных → ключа НЕТ
    (правило 6), а не пустой список-«свойств нет». Рядом кладётся `_diagnostics`
    с СЫРЫМИ отчётами пробников — чтобы была видна причина (для инструмента, не
    для свидетельства).
    """
    from domain.qc import probes

    names = list(dict.fromkeys([*probes.property_names(cfg), *extra_names]))
    qc_dir = ROOT / ".qc"
    out: dict = {}
    diag: dict = {}

    gp_tmp = qc_dir / "grid_properties.tmp"
    raw = probes.read_capture(client,
                              code=probes.grid_properties_code(grid, gp_tmp),
                              tmp=gp_tmp)
    diag["grid_properties"] = raw
    grid_props = probes.parse_grid_properties(raw)
    if grid_props is not None:
        out["grid_properties"] = grid_props

    ps_tmp = qc_dir / "property_stats.tmp"
    raw = probes.read_capture(client,
                              code=probes.property_stats_code(grid, names, ps_tmp),
                              tmp=ps_tmp)
    diag["property_stats"] = raw
    stats = probes.parse_property_stats(raw)
    if stats is not None:
        out["property_stats"] = stats

    bw_tmp = qc_dir / "blocked_wells.tmp"
    raw = probes.read_capture(client,
                              code=probes.blocked_wells_code(bw_tmp, grid), tmp=bw_tmp)
    diag["blocked_wells"] = raw
    blocked = probes.parse_blocked_wells(raw)
    if blocked is not None:
        out["blocked_wells"] = blocked

    out["_requested"] = {"grid": grid, "property_names": names}
    out["_diagnostics"] = diag
    return out


def main(argv: list[str] | None = None) -> int:
    cfg = load_config(None)
    graph = {}
    graph_dir = cfg.path("project.graph_dir", "ontology_project")
    field = str(cfg.get("project.default_field", "") or "")
    for cand in (graph_dir / f"{field}.yaml",):
        if cand.is_file():
            import yaml
            graph = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
    petro = (graph.get("petrophysics") or {})
    cubes = [c for c in (petro.get("cubes") or []) if isinstance(c, dict)]
    default_cube = str((cubes[0].get("cube") if cubes else "") or "")
    sheets = graph.get("maps") or {}
    default_dir = str(sheets.get("export_dir") or "")

    ap = argparse.ArgumentParser(description="проба console-safe карт тНава")
    ap.add_argument("--project", required=True,
                    help="путь к .snp проекта-донора (копируется в models/_probe_maps)")
    ap.add_argument("--grid", default=str(cfg.get("project.grid_name", "") or ""))
    ap.add_argument("--cube", default=default_cube)
    ap.add_argument("--map-name", default=f"{default_cube}_map" if default_cube else "probe_map")
    ap.add_argument("--export-dir", default=default_dir)
    ap.add_argument("--out", default="_probe_maps.txt")
    ap.add_argument("--appdata", default="",
                    help="каталог APPDATA для процессов тНава (по умолчанию "
                         "внутри рабочей папки: права на запись log-файлов)")
    ap.add_argument("--blocks", action="store_true",
                    help="проба ЭЛЕМЕНТА ВОРКФЛОУ: begin_wf_item ровно с вызовом тНава")
    ap.add_argument("--blocks-expr", action="store_true",
                    help="проба ЭЛЕМЕНТА ВОРКФЛОУ с безымпортной формой "
                         "__import__('os').makedirs(...) вместо import")
    ap.add_argument("--item-file", action="store_true",
                    help="проба НАСТОЯЩЕГО файла воркфлоу (обёртка + элементы): "
                         "создание карты и выгрузка")
    ap.add_argument("--evidence", action="store_true",
                    help="снять свидетельства гейтов (grid_properties / "
                         "property_stats / blocked_wells) с проекта-донора")
    ap.add_argument("--map-check", action="store_true",
                    help="F-18: создать карту из куба (вариант --variant) и выгрузить "
                         "файлом; затем посчитать непустые ячейки")
    ap.add_argument("--variant", default="v1", choices=("v1", "v2", "v3", "v4"),
                    help="вариант вызова map_2d_create_by_grid_property")
    args = ap.parse_args(argv)
    evidence = bool(args.evidence)
    if not args.grid or (not args.cube and not evidence):
        print("нужны --grid и --cube (или petrophysics.cubes в проектном YAML)")
        return 2

    out_path = ROOT / args.out
    probe = ROOT / "models" / PROBE_DIR_NAME
    src = Path(args.project)
    if src.is_dir():
        src = next(iter(sorted(src.glob("*.snp"))), src)
    if not src.is_file():
        print(f"проект-донор не найден: {src}")
        return 2
    if probe.exists():
        shutil.rmtree(probe, ignore_errors=True)
    probe.mkdir(parents=True, exist_ok=True)
    for item in src.parent.iterdir():
        dst = probe / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)

    wf_dir = ROOT / WF_DIR_NAME
    wf_dir.mkdir(exist_ok=True)
    item_file = bool(args.item_file)
    map_check = bool(args.map_check)
    code, wf = "", None
    if evidence:
        pass                                   # свидетельства снимаются пробниками
    elif map_check:
        (probe / args.export_dir).mkdir(parents=True, exist_ok=True)
        code, _fn = _map_check_file(grid=args.grid, cube=args.cube,
                                    map_name=args.map_name,
                                    export_dir=args.export_dir, variant=args.variant)
        wf = wf_dir / f"map_check_{args.variant}.py"
    elif item_file:
        export_dir = probe / args.export_dir
        export_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{args.export_dir}/{args.map_name}_item.txt"
        code = _item_workflow_file(grid=args.grid, cube=args.cube,
                                   map_name=args.map_name,
                                   export_dir=args.export_dir, file_name=file_name,
                                   with_expression=bool(args.blocks_expr))
        wf = wf_dir / ("item_wf_expr.py" if args.blocks_expr else "item_wf_call.py")
    elif args.blocks or args.blocks_expr:
        code = _workflow_item_probe(grid=args.grid, cube=args.cube,
                                    map_name=args.map_name,
                                    export_dir=args.export_dir,
                                    with_expression=bool(args.blocks_expr))
    else:
        code = build_code(grid=args.grid, cube=args.cube, map_name=args.map_name,
                          export_dir=args.export_dir)
    if not item_file and not evidence:
        code = code.replace("__OUT__", _q(out_path))
    if not evidence:
        compile(code, "<probe_maps>", "exec")
    if not item_file and not evidence and not map_check:
        wf = wf_dir / ("maps_probe_item.py" if (args.blocks or args.blocks_expr)
                       else "maps_probe.py")
    if wf is not None:
        wf.write_text(code, encoding="utf-8")

    if out_path.exists():
        out_path.unlink()
    appdata = Path(args.appdata) if args.appdata else (ROOT / ".tnav_appdata")
    print(f"APPDATA процессов тНава → {_redirect_appdata(appdata)}", flush=True)
    cfg.set("tnavigator.dry_run", False)
    client = TnavClient(cfg)
    client.dry_run = False
    client.set_log(lambda line: print(f"  · {line}", flush=True))
    try:
        client.open(project_path=probe / src.name, create=False)
        if evidence:
            extra = [args.cube] if args.cube else []
            result = _evidence_run(client, cfg, grid=args.grid, extra_names=extra)
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            print("\n=== свидетельства гейтов ===", flush=True)
            print(json.dumps(result, ensure_ascii=False, indent=1), flush=True)
        else:
            res = client.run_workflow(wf, save=False, timeout_sec=1200)
            print(f"probe ok={res.ok} {str(res.error or '')[:300]}", flush=True)
            if map_check:
                from domain.map_render import count_points
                exported = probe / args.export_dir / f"{args.map_name}_{args.variant}.txt"
                if not exported.is_file():
                    print("ВЫГРУЗКИ НЕТ (карта не создана/не выгружена)", flush=True)
                    return 1
                points = count_points(exported)
                print(f"ВАРИАНТ {args.variant}: {exported.name} "
                      f"bytes={exported.stat().st_size} непустых ячеек={points}",
                      flush=True)
                return 0 if points else 1
    finally:
        client.close()
    if evidence:
        return 0 if out_path.is_file() else 1
    if out_path.is_file():
        print(f"\n=== {out_path.name} ===", flush=True)
        print(out_path.read_text(encoding="utf-8"), flush=True)
        return 0
    if item_file:
        # Результат файлового варианта — сам выгруженный файл карты в папке проекта.
        exported = probe / args.export_dir / f"{args.map_name}_item.txt"
        if exported.is_file():
            head = exported.read_text(encoding="utf-8", errors="replace").splitlines()[:2]
            print(f"\nВЫГРУЗКА ЕСТЬ: {exported.name} bytes={exported.stat().st_size} "
                  f"head={' / '.join(x.strip()[:70] for x in head)}", flush=True)
            return 0
        print("ВЫГРУЗКИ НЕТ (файл карты не создан)", flush=True)
        return 1
    print("результат не получен (нет файла отчёта)", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
