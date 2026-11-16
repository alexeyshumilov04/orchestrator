"""Дешёвая проба фациального моделирования в ОДНОЙ сессии тНава.

Зачем: `grid_property_facies_by_wells_log_3d` не создаёт куб сам — нужен ЗАРАНЕЕ
существующий дискретный FACIES с дискретной палитрой («Object "Property "FACIES""
has inappropriate template ("Continuous palette")»); `grid_property_calculator`
даёт continuous, `grid_property_change_type` конверсию не выполняет (52 раунда
проб — `orchestrator_v7/orchestrator/docs/tasks/B4_facies.md`).

Мануал тНава 26.2 (`tNavUserGuideDesignerRussian.pdf`) говорит прямо:
  * стр. 2581 — `grid_property_facies_modeling()` «Фациальное моделирование
    (Зоны, Регионы)»: «позволяет создать ДИСКРЕТНОЕ свойство по объекту Blocked
    Wells»; «Дискретные Blocked Wells должны быть предварительно созданы»;
  * стр. 2733 — `grid_property_create_by_zones()`: «Созданному свойству
    автоматически присваивается дискретный шаблон» (Сетка, Свойство зон, Исп.,
    Имя зоны, Значение, K1, K2); стр. 2734 — `grid_property_create_by_values()`.

Инструмент копирует проект-донор (`--donor`) в `models/_probe_facies`, открывает
его ОДИН раз и перебирает варианты вызовов, ДОПИСЫВАЯ ответы тНава в файл после
каждого варианта (падение тНава не теряет уже полученные факты). Методика: тНав
сам называет неверный/недостающий аргумент, варианты уточняются по тексту ошибок.

Окружение (проверено на этой машине): процессам тНава ЗАПРЕЩЕНО писать вне
рабочего каталога (лог локального диспетчера в `%APPDATA%\\tNavigator`, каталог
`%TEMP%\\tnav_py_run_*`): «Отказано в доступе». Изоляцию окружения делает ОБЩИЙ
data-driven механизм клиента — `TnavClient.prepare_runtime_env()` по данным
`tnavigator.runtime_env_dir` / `runtime_env_vars` (копирует `tNavigator.ini` и
подменяет `APPDATA/TEMP/TMP` в рабочий каталог). Если этих данных в конфиге нет,
инструмент ПРЕДУПРЕЖДАЕТ: проба может упасть на «Отказано в доступе».

Запуск:
    python -X utf8 tools/probe_facies.py --donor <каталог проекта>
    python -X utf8 tools/probe_facies.py --stage <rendered_stage.py>   # проверка артефакта
Результат — сырой текст ответов тНава; НИЧЕГО не «достраивается по смыслу».
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import load_config                       # noqa: E402
from domain.tnav_client import TnavClient                 # noqa: E402

PROBE_DIR_NAME = "_probe_facies"
WF_DIR_NAME = "_probe_wf"
DEFAULT_OUT = "runs/_probe_facies.txt"

# --- фрагменты вызовов (имена аргументов — из протокола проб B4, раунды 49–52) ----
_E = "find_object (name='', type='')"
ZF_OBJ = ("zone_region_filter=ZoneRegionFilterInfo (use_zone=False, use_region=False, "
          "zone=find_object (name='', type='Grid3dProperty'), "
          "region=find_object (name='', type='Grid3dProperty'))")
ZF_NONE = ("zone_region_filter=ZoneRegionFilterInfo (use_zone=False, use_region=False, "
           "zone=None, region=None)")
ZFA_NONE = "zone_region_filter_args=ZoneRegionFilter (zone=None, region=None)"
ZFA_INT = "zone_region_filter_args=ZoneRegionFilter (zone=1, region=None)"
_ZR_TAIL = ("restrict=ContactParameters (restriction_type='none', "
            f"secondary_attribute={_E}, m_use_da_cond_distr=False, "
            "use_contact_restriction=False, "
            f"contact={_E}, use_contact_horizon=False, contact_horizon={_E}, "
            f"contact_map_total={_E})")
ZRP_PLAIN = ("ZoneRegionParameters=[ZoneRegionParameters (use=True, zone=None, "
             "region=None, facies_order=[], current_facies=3)]")
ZRP_RESTRICT = ("ZoneRegionParameters=[ZoneRegionParameters (use=True, zone=None, "
                f"region=None, facies_order=[], current_facies=3, {_ZR_TAIL})]")
FAC_SIS = ("parameters=[ZoneRegionFaciesParameters (facies=None, "
           "params=InterpolationParametersItem (use=True, interpolator_type='sis'))]")


def fac_item(interpolator: str) -> str:
    """`parameters=[ZoneRegionFaciesParameters(...)]` с заданным interpolator_type."""
    return ("parameters=[ZoneRegionFaciesParameters (facies=None, "
            f"params=InterpolationParametersItem (use=True, interpolator_type='{interpolator}'))]")


def fac_named(argname: str, interpolator: str = "sgs") -> str:
    """Список параметров по фациям под ЗАДАННЫМ именем аргумента (F-27c).

    `parameters` тНав отверг («Unknown argument "parameters"»), поэтому имена
    перебираются в ПРАВИЛЬНОМ контексте — с типизированными объектами (V9/V10).
    """
    return (f"{argname}=[ZoneRegionFaciesParameters (facies=None, "
            f"params=InterpolationParametersItem (use=True, interpolator_type='{interpolator}'))]")


def zrp_with(field: str, interpolator: str = "sgs", base: str = ZRP_PLAIN) -> str:
    """Зональная строка, в которую ТАБЛИЦА ФАЦИЙ вложена под заданным именем (F-27c).

    В `ZoneRegionParameters` уже есть поля фаций (`facies_order`, `current_facies`),
    поэтому следующая гипотеза — таблица `ZoneRegionFaciesParameters` вложена в строку
    зоны, а не лежит на уровне `i3_params`.
    """
    rows = ("[ZoneRegionFaciesParameters (facies=None, "
            "params=InterpolationParametersItem (use=True, "
            f"interpolator_type='{interpolator}'))]")
    return base.replace("facies_order=[],", f"facies_order=[], {field}={rows},")
PALETTE = ("create_object_template (name='FACIES', type='Discrete palette', units='no', "
           "numeric_precision=2, discrete_data=["
           "ColorDataDiscrete (value=0, name='UNKNOWN', red=200, green=200, blue=200, pattern='608'), "
           "ColorDataDiscrete (value=1, name='SANDSTONE', red=255, green=255, blue=0, pattern='620'), "
           "ColorDataDiscrete (value=2, name='SHALE', red=0, green=170, blue=0, pattern='608'), "
           "ColorDataDiscrete (value=3, name='HARD', red=170, green=0, blue=0, pattern='608'), "
           "ColorDataDiscrete (value=8, name='COAL', red=0, green=0, blue=0, pattern='608')])")
MAP_PROPERTY = ("object_template_mapping (folder=find_object (name='3D-Grids', "
                "type='TypedFolder'), use_grid=True, "
                "grid=find_object (name='main_grid', type='Grid3d'), "
                "object_template_table=[{'object' : 'FACIES', 'template_data' : 'FACIES', "
                "'use_local_palette' : False, 'object_type' : 'Property'}])")
ZONES_HEAD = ("grid_property_create_by_zones (mesh=find_object (name='main_grid', "
              "type='Grid3d'), result_grid_property=find_object (name='ZONES_PROBE', "
              "type='Grid3dProperty')")
VALUES_HEAD = ("grid_property_create_by_values (mesh=find_object (name='main_grid', "
               "type='Grid3d'), result_grid_property=find_object (name='ZONES_PROBE_V', "
               "type='Grid3dProperty')")


def _fm(*args: str, result: str = "FACIES") -> str:
    """Вызов `grid_property_facies_modeling`: mesh/blocked_wells/result — ИМЕНА."""
    return ("grid_property_facies_modeling (mesh='main_grid', blocked_wells='FaciesU', "
            f"result_grid_property='{result}', i3_params=Interpolation3dParameters ("
            + ", ".join(args) + "))")


# --- ТИПИЗОВАННЫЕ входы (проба Lead, V9: так вход `Grid` СВЯЗЫВАЕТСЯ) -------------
def _fm_typed(*args: str, result: str = "FACIES") -> str:
    """Вызов с `typed_object_name` (рабочая форма для элемента воркфлоу/пробы)."""
    return ("grid_property_facies_modeling ("
            "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d'), "
            "blocked_wells=typed_object_name (obj_name='FaciesU', obj_type='BlockedWells'), "
            f"result_grid_property=typed_object_name (obj_name='{result}', "
            "obj_type='Grid3dProperty'), i3_params=Interpolation3dParameters ("
            + ", ".join(args) + "))")


# Кандидаты ИМЕНИ аргумента со списком параметров по фациям (правило 8: перебор
# только по ответам тНава; `pgs_parameters` — из машинного шаблона
# `grid_property_facies_by_wells_log_3d`, где список интерполяции назван так).
_LISTS = ("pgs_parameters", "facies_parameters", "parameters", "zone_region_parameters",
          "facies_items", "interpolation_items", "interpolators", "items",
          "probabilities", "fractions", "fraction_parameters", "method_parameters",
          "sis_parameters", "indicator_parameters", "facies_modeling_parameters",
          "zone_region_facies_parameters", "PGS_Parameters", "Facies_Parameters",
          "facies_parameter_items", "interpolation_parameters_items")
_ITEMS = ("params", "parameters", "interpolation_items", "items", "facies_parameters",
          "pgs_parameters", "interpolators", "interpolation")
# Значение-заготовка: один элемент по фации (как требует мануал для каждой фации).
_ITEM_VALUE = ("[ZoneRegionFaciesParameters (facies=None, params=InterpolationParametersItem "
               "(use=True, interpolator_type='sgs'))]")

# --- ЗОНЫ/РЕГИОНЫ: подтверждено пробой, что `parameters=[…]` живёт ВНУТРИ строки
# `ZoneRegionParameters` (тогда схема принимается, а ошибка становится логической:
# «No zones or regions are selected for interpolation!»). Значит остаётся выбрать
# зону: `ZoneRegionFilterInfo.zone` — ОБЪЕКТ, `ZoneRegionFilter.zone` и
# `ZoneRegionParameters.zone` — ИНДЕКС категории (как в машинных шаблонах).
_ZF_INFO_OBJ = ("zone_region_filter=ZoneRegionFilterInfo (use_zone=False, use_region=False, "
                "zone=typed_object_name (obj_name='', obj_type='Grid3dProperty'), "
                "region=typed_object_name (obj_name='', obj_type='Grid3dProperty'))")
_ZF_INFO_ZONE = ("zone_region_filter=ZoneRegionFilterInfo (use_zone=True, use_region=False, "
                 "zone=typed_object_name (obj_name='zone_id', obj_type='Grid3dProperty'), "
                 "region=typed_object_name (obj_name='', obj_type='Grid3dProperty'))")
_ZFA_NONE_T = "zone_region_filter_args=ZoneRegionFilter (zone=None, region=None)"
_ZFA_ZONE1 = "zone_region_filter_args=ZoneRegionFilter (zone=1, region=None)"


def _zrp(*, use: str, zone: str, item_arg: str = "parameters") -> str:
    """Строка `ZoneRegionParameters` с ПОДТВЕРЖДЁННЫМ аргументом списка фаций."""
    return ("ZoneRegionParameters=[ZoneRegionParameters (use=" + use + ", zone=" + zone +
            ", region=None, facies_order=[], current_facies=3, " + item_arg + "=" +
            _ITEM_VALUE + ")]")


# --- ЭТАЛОННАЯ (машинно-сгенерированная) форма 26.2 ---------------------------------
# Источник: `C:/Program Files/tNavigator/26.2/tutorials/GD3.7_HowToPerformDataAnalysis/
# Data_to_import/Interpolation.py` (строки 137–190, вызов
# `grid_property_interpolate_by_wells_log_3d`): строка `ZoneRegionParameters` содержит
# `facies_modeling_method`/`classic_sis`/`classic_sis_random_seed`/`facies_order`/
# `current_facies`/`restrict=ContactParameters(...)` и — ГЛАВНОЕ — список
# `parameters=[ZoneRegionFaciesParameters (facies=None, params=InterpolationParametersItem (...))]`
# ВНУТРИ строки зоны; `ZoneRegionFilterInfo` дополнительно принимает `zone_log`/`region_log`.
_REF_RESTRICT = ("restrict=ContactParameters (restriction_type='none', "
                 "secondary_attribute=typed_object_name (obj_name='', obj_type=''), "
                 "m_use_da_cond_distr=False, use_contact_restriction=False, "
                 "contact=typed_object_name (obj_name='', obj_type=''), "
                 "use_contact_horizon=False, "
                 "contact_horizon=typed_object_name (obj_name='', obj_type=''), "
                 "contact_map_total=typed_object_name (obj_name='', obj_type=''))")
_REF_ITEM = ("[ZoneRegionFaciesParameters (facies=None, params=InterpolationParametersItem "
             "(use=True, interpolator_type='kriging', kriging_params=KrigingParameters "
             "(kriging_type='simple', global_mean=0, use_global_mean=False, "
             "use_kriging_points=True, kriging_points=50, use_groups=False, "
             "points_in_group=1000, use_min_acceptable_distance=False, "
             "min_acceptable_distance=1, random_seed=0, kriging_mean_grfs=0, "
             "use_kriging_mean_grfs=False)))]")
_REF_CLASSIC_ITEM = ("[ZoneRegionFaciesParameters (facies=None, params=InterpolationParametersItem "
                     "(use=True, interpolator_type='kriging'))]")


def _ref_filter(*, use_zone: bool, zone_name: str) -> str:
    """`ZoneRegionFilterInfo` в форме эталона 26.2 (с `zone_log`/`region_log`)."""
    return ("zone_region_filter=ZoneRegionFilterInfo (use_zone=" + str(use_zone) +
            ", use_region=False, zone=typed_object_name (obj_name='" + zone_name +
            "', obj_type='Grid3dProperty'), region=typed_object_name (obj_name='" +
            zone_name + "', obj_type='Grid3dProperty'), "
            "zone_log=typed_object_name (obj_name='', obj_type=''), "
            "region_log=typed_object_name (obj_name='', obj_type=''))")


def _ref_zrp(*, use: str, zone: str, classic: bool = False, item: str = _REF_ITEM) -> str:
    """Строка `ZoneRegionParameters` в форме эталона 26.2 (со списком `parameters`)."""
    return ("ZoneRegionParameters=[ZoneRegionParameters (use=" + use + ", zone=" + zone +
            ", region=None, facies_modeling_method='sis_ordering_cubes', classic_sis=" +
            ("True" if classic else "False") + ", classic_sis_random_seed=0, "
            "facies_order=[], current_facies=None, " + _REF_RESTRICT +
            ", parameters=" + item + ")]")


def _fm_typed(*args: str, result: str = "FACIES") -> str:
    """Тот же вызов, но входы — ТИПИЗИРОВАННЫЕ объекты (`typed_object_name`).

    Гипотеза (правило 8 — проверяется пробой): в контексте ЭЛЕМЕНТА ВОРКФЛОУ строковые
    имена не связываются (`Parameter "Grid" (in group "Input") is not specified!`),
    тогда как работающие функции того же контура (например,
    `map_2d_create_by_grid_property`) передают объекты именно как `typed_object_name`.
    """
    return ("grid_property_facies_modeling (mesh=typed_object_name (obj_name='main_grid', "
            "obj_type='Grid3d'), blocked_wells=typed_object_name (obj_name='FaciesU', "
            "obj_type='BlockedWells'), result_grid_property=typed_object_name "
            f"(obj_name='{result}', obj_type='Grid3dProperty'), "
            "i3_params=Interpolation3dParameters (" + ", ".join(args) + "))")


def variants() -> list[tuple[str, str]]:
    """(метка, код вызова): сначала документированный мануалом путь, затем проверочные."""
    out: list[tuple[str, str]] = [
        ("V0 палитра: create_object_template Discrete palette", PALETTE),
        ("V9 typed-объекты: mesh/blocked_wells/result как typed_object_name (гипотеза F-27b)",
         _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, FAC_SIS)),
        ("V10 typed-объекты + sgs (V9 подтвердил связывание Grid; sis отвергнут тНавом)",
         _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, fac_item("sgs"))),
        ("V11 typed + facies_parameters", _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT,
                                                    fac_named("facies_parameters"))),
        ("V12 typed + facies_params", _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT,
                                                fac_named("facies_params"))),
        ("V13 typed + facies", _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT,
                                         fac_named("facies"))),
        ("V14 typed + facies_table", _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT,
                                               fac_named("facies_table"))),
        ("V15 typed + facies_list", _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT,
                                              fac_named("facies_list"))),
        ("V16 typed + zone_region_facies_parameters",
         _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, fac_named("zone_region_facies_parameters"))),
        ("V17 typed + zones_facies_parameters",
         _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, fac_named("zones_facies_parameters"))),
        ("V18 typed + interpolation_facies_parameters",
         _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, fac_named("interpolation_facies_parameters"))),
        ("V19 таблица фаций ВНУТРИ зоны: ZoneRegionFaciesParameters",
         _fm_typed(ZF_OBJ, zrp_with("ZoneRegionFaciesParameters"))),
        ("V20 таблица фаций ВНУТРИ зоны: facies_parameters",
         _fm_typed(ZF_OBJ, zrp_with("facies_parameters"))),
        ("V21 таблица фаций ВНУТРИ зоны: facies",
         _fm_typed(ZF_OBJ, zrp_with("facies"))),
        ("V22 таблица фаций ВНУТРИ зоны: interpolation_parameters",
         _fm_typed(ZF_OBJ, zrp_with("interpolation_parameters"))),
        ("V23 таблица фаций ВНУТРИ зоны без restrict (ZRP_PLAIN)",
         _fm_typed(ZF_OBJ, zrp_with("ZoneRegionFaciesParameters", base=ZRP_PLAIN))),
        ("V24 typed + ZF(obj) + ZFA(None) + ZRP_PLAIN (без таблицы фаций)",
         _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_PLAIN)),
        ("V25 typed + ZF(obj) + ZRP_PLAIN (минимальная зональная форма)",
         _fm_typed(ZF_OBJ, ZRP_PLAIN)),
        ("V26 ЭТАЛОН тНава: parameters=[ZRFc] ВНУТРИ строки зоны + facies_modeling_method",
         _fm_typed(
             ZF_OBJ,
             "zone_region_filter_args=ZoneRegionFilter (zone=None, region=None)",
             "ZoneRegionParameters=[ZoneRegionParameters (use=True, zone=None, region=None, "
             "facies_modeling_method='sis_ordering_cubes', classic_sis=False, "
             "classic_sis_random_seed=0, facies_order=[], current_facies=None, "
             "restrict=ContactParameters (restriction_type='none', "
             "secondary_attribute=typed_object_name (obj_name='', obj_type=''), "
             "m_use_da_cond_distr=False, use_contact_restriction=False, "
             "contact=typed_object_name (obj_name='', obj_type=''), "
             "use_contact_horizon=False, contact_horizon=typed_object_name (obj_name='', obj_type=''), "
             "contact_map_total=typed_object_name (obj_name='', obj_type='')), "
             "parameters=[ZoneRegionFaciesParameters (facies=None, "
             "params=InterpolationParametersItem (use=True, interpolator_type='kriging'))])]")),
        ("V1 facies_modeling ZF(obj)+ZFA(None)+ZRP(restrict)+SIS",
         _fm(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, FAC_SIS)),
        ("V1k facies_modeling interpolator_type=kriging",
         _fm(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, fac_item("kriging"))),
        ("V1s facies_modeling interpolator_type=sgs",
         _fm(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, fac_item("sgs"))),
        ("V1g facies_modeling interpolator_type=grfs",
         _fm(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, fac_item("grfs"))),
        ("V2 facies_modeling без parameters (только зоны/регионы)",
         _fm(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT)),
        ("V3 facies_modeling без zone_region_filter_args",
         _fm(ZF_OBJ, ZRP_RESTRICT, fac_item("kriging"))),
        ("V4 facies_modeling ZF(zone=None)",
         _fm(ZF_NONE, ZFA_NONE, ZRP_RESTRICT, fac_item("kriging"))),
        ("V5 facies_modeling ZFA(zone=1)+ZRP(plain)",
         _fm(ZF_OBJ, ZFA_INT, ZRP_PLAIN, fac_item("kriging"))),
        ("V7 палитра -> свойство (3D-Grids, Property)", MAP_PROPERTY),
        ("V8 create_by_zones zones_table=[dict use/value/K1/K2]",
         ZONES_HEAD + ", zones_table=[{'use': True, 'value': 1, 'K1': 1, 'K2': 2}])"),
        ("V9 create_by_zones zones_table=[dict use]",
         ZONES_HEAD + ", zones_table=[{'use': True}])"),
        ("V10 create_by_zones zones_table=[(True, 1, 2, 1, 2)]",
         ZONES_HEAD + ", zones_table=[(True, 1, 2, 1, 2)])"),
        ("V11 create_by_values zones_table=[(True, 1, 1, 2)]",
         VALUES_HEAD + ", zones_table=[(True, 1, 1, 2)])"),
    ]
    # перебор ИМЕНИ аргумента со списком параметров фаций (тНав называет неверный)
    for cand in ("parameters", "facies_parameters", "zr_facies_parameters",
                 "zone_region_facies_parameters", "facies_items", "items", "params",
                 "interpolation_parameters", "facies_parameters_list",
                 "ZoneRegionFaciesParameters", "FaciesParameters", "facies",
                 "facies_list", "zone_region_facies", "ZRFaciesParameters",
                 "facies_parameter_items", "zr_parameters", "facies_param",
                 "interpolation_items", "zone_region_parameters_items"):
        out.append((f"V12 i3_params {cand}=[]",
                    _fm(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, f"{cand}=[]")))
    out.append(("V13 facies_modeling apply_to_all_f=True",
                _fm(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, "apply_to_all_f=True")))
    # --- ТИПИЗОВАННЫЕ входы: перебор места/имени списка параметров по фациям ------
    # (V9 Lead: с typed_object_name ошибка «Parameter Grid …» уходит → дальше ищем
    #  только имя аргумента со списком фаций; каждый промах — дешёвый `Unknown argument`).
    for cand in _LISTS:
        out.append((f"T1 i3_params {cand}=[фации]",
                    _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT, f"{cand}={_ITEM_VALUE}")))
    for cand in _ITEMS:
        out.append((f"T2 ZoneRegionParameters {cand}=[фации]",
                    _fm_typed(ZF_OBJ, ZFA_NONE,
                              "ZoneRegionParameters=[ZoneRegionParameters (use=True, "
                              "zone=None, region=None, facies_order=[], current_facies=3, "
                              f"{cand}={_ITEM_VALUE})]")))
    for cand in ("facies_parameters", "parameters", "pgs_parameters", "facies_items"):
        out.append((f"T3 function-level {cand}=[фации]",
                    "grid_property_facies_modeling ("
                    "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d'), "
                    "blocked_wells=typed_object_name (obj_name='FaciesU', "
                    "obj_type='BlockedWells'), "
                    "result_grid_property=typed_object_name (obj_name='FACIES', "
                    f"obj_type='Grid3dProperty'), {cand}={_ITEM_VALUE})"))
    # БЕЗ списка параметров по фациям — известно, что роняет задачу тНава
    # (access violation), поэтому проверяется ПОСЛЕДНИМ (в самом конце пробы).
    out.append(("T0 typed + ZF(obj)+ZFA(None)+ZRP(restrict) без списка",
                _fm_typed(ZF_OBJ, ZFA_NONE, ZRP_RESTRICT)))
    # --- ЗОНЫ/РЕГИОНЫ + подтверждённый `parameters=[…]` внутри ZoneRegionParameters --
    out.append(("Z1 зона zone_id: ZFInfo(use_zone)+ZFA(zone=1)+ZRP(zone=1,parameters)",
                _fm_typed(_ZF_INFO_ZONE, _ZFA_ZONE1,
                          _zrp(use="True", zone="1"))))
    out.append(("Z2 зона zone_id: ZFInfo(use_zone=True)+ZFA(zone=None)+ZRP(zone=1)",
                _fm_typed(_ZF_INFO_ZONE, _ZFA_NONE_T,
                          _zrp(use="True", zone="1"))))
    out.append(("Z3 беззонная: use=False + parameters внутри ZRP",
                _fm_typed(_ZF_INFO_OBJ, _ZFA_NONE_T,
                          _zrp(use="False", zone="None"))))
    out.append(("Z4 беззонная: use=True + typed пустые zone/region",
                _fm_typed(_ZF_INFO_OBJ, _ZFA_NONE_T,
                          _zrp(use="True", zone="None"))))
    out.append(("Z5 зона zone_id: ZFInfo(use_zone)+ZFA(None)+ZRP(zone=1)+current_facies=1",
                _fm_typed(_ZF_INFO_ZONE, _ZFA_NONE_T,
                          "ZoneRegionParameters=[ZoneRegionParameters (use=True, zone=1, "
                          "region=None, facies_order=[], current_facies=1, parameters="
                          + _ITEM_VALUE + ")]")))
    out.append(("Z6 беззонная: use=False, zone_region_filter_args=None (без зон)",
                _fm_typed(_ZF_INFO_OBJ, _zrp(use="False", zone="None"))))
    # --- ЗОНА ДИСКРЕТНАЯ ПАЛИТРА: мануал 26.2 (стр. 2733/2584): «чтобы свойство
    # было доступно в списке свойств (зон), необходимо задать ему ДИСКРЕТНЫЙ шаблон»
    # → назначаем дискретный шаблон свойству зон и повторяем выбор зоны.
    palette_zone = ("create_object_template (name='ZONE_DISC', type='Discrete palette', "
                    "units='no', numeric_precision=0, discrete_data=["
                    "ColorDataDiscrete (value=0, name='Z0', red=200, green=200, blue=200, pattern='608'), "
                    "ColorDataDiscrete (value=1, name='Z1', red=255, green=0, blue=0, pattern='608'), "
                    "ColorDataDiscrete (value=2, name='Z2', red=0, green=255, blue=0, pattern='608'), "
                    "ColorDataDiscrete (value=3, name='Z3', red=0, green=0, blue=255, pattern='608')])")
    map_zone = ("object_template_mapping (folder=find_object (name='3D-Grids', "
                "type='TypedFolder'), use_grid=True, grid=find_object (name='main_grid', "
                "type='Grid3d'), object_template_table=[{'object' : 'zone_id', "
                "'template_data' : 'ZONE_DISC', 'use_local_palette' : False, "
                "'object_type' : 'Property'}])")
    out.append(("Y1 палитра зон + Z1 (zone=zone_id, use_zone=True)",
                palette_zone + "\n" + map_zone + "\n" + _fm_typed(
                    _ZF_INFO_ZONE, _ZFA_ZONE1, _zrp(use="True", zone="1"))))
    out.append(("Y2 Z1 + region=None в ZoneRegionFilterInfo",
                _fm_typed("zone_region_filter=ZoneRegionFilterInfo (use_zone=True, "
                          "use_region=False, zone=typed_object_name (obj_name='zone_id', "
                          "obj_type='Grid3dProperty'), region=None)",
                          _ZFA_ZONE1, _zrp(use="True", zone="1"))))
    out.append(("Y3 zone_region_filter=ZoneRegionFilterParameters(...)",
                _fm_typed("zone_region_filter=ZoneRegionFilterParameters (use_zone=True, "
                          "use_region=False, zone=typed_object_name (obj_name='zone_id', "
                          "obj_type='Grid3dProperty'), region=typed_object_name (obj_name='', "
                          "obj_type='Grid3dProperty'))",
                          _ZFA_ZONE1, _zrp(use="True", zone="1"))))
    out.append(("Y4 zone_region_filter_args=ZonesRegionsFilter(zone=1)",
                _fm_typed(_ZF_INFO_ZONE,
                          "zone_region_filter_args=ZonesRegionsFilter (zone=1, region=None)",
                          _zrp(use="True", zone="1"))))
    out.append(("Y5 зона зоны-региона без zone_region_filter_args, use_zone=True",
                _fm_typed(_ZF_INFO_ZONE, _zrp(use="True", zone="1"))))
    # --- W: ЭТАЛОННАЯ форма 26.2 (GD3.7 Interpolation.py, строки 137–190) ----------
    out.append(("W1 эталон: row(use=False,zone=1)+filter(use_zone,zone_id,zone=4)+parameters",
                _fm_typed(_ref_filter(use_zone=True, zone_name="zone_id"),
                          "zone_region_filter_args=ZoneRegionFilter (zone=4, region=None)",
                          _ref_zrp(use="False", zone="1"))))
    out.append(("W2 эталон: tag же, но row use=True",
                _fm_typed(_ref_filter(use_zone=True, zone_name="zone_id"),
                          "zone_region_filter_args=ZoneRegionFilter (zone=1, region=None)",
                          _ref_zrp(use="True", zone="1"))))
    out.append(("W3 эталон: беззонная (use_zone=False, пустые объекты)+row use=True",
                _fm_typed(_ref_filter(use_zone=False, zone_name=""),
                          "zone_region_filter_args=ZoneRegionFilter (zone=None, region=None)",
                          _ref_zrp(use="True", zone="None"))))
    out.append(("W4 эталон: classic_sis=True + row use=True",
                _fm_typed(_ref_filter(use_zone=True, zone_name="zone_id"),
                          "zone_region_filter_args=ZoneRegionFilter (zone=1, region=None)",
                          _ref_zrp(use="True", zone="1", classic=True))))
    out.append(("W5 эталон: filter(use_zone=False,zone_id)+row(zone=1,use=True)",
                _fm_typed(_ref_filter(use_zone=False, zone_name="zone_id"),
                          "zone_region_filter_args=ZoneRegionFilter (zone=1, region=None)",
                          _ref_zrp(use="True", zone="1"))))
    # --- X: дискретный шаблон свойства ЗОН + эталонная форма вызова -----------------
    # Мануал 26.2 (стр. 2584/2733): свойство попадает в список зон ТОЛЬКО если ему
    # задан ДИСКРЕТНЫЙ шаблон. Поэтому: палитра + привязка к `zone_id`, затем вызов.
    out.append(("X1 палитра зон + W2 (zone=zone_id)",
                palette_zone + "\n" + map_zone + "\n" + _fm_typed(
                    _ref_filter(use_zone=True, zone_name="zone_id"),
                    "zone_region_filter_args=ZoneRegionFilter (zone=1, region=None)",
                    _ref_zrp(use="True", zone="1"))))
    out.append(("X2 палитра зон + W1 (row use=False)",
                palette_zone + "\n" + map_zone + "\n" + _fm_typed(
                    _ref_filter(use_zone=True, zone_name="zone_id"),
                    "zone_region_filter_args=ZoneRegionFilter (zone=4, region=None)",
                    _ref_zrp(use="False", zone="1"))))
    out.append(("X3 палитра зон + W2 беззонная (use_zone=False)",
                palette_zone + "\n" + map_zone + "\n" + _fm_typed(
                    _ref_filter(use_zone=False, zone_name=""),
                    "zone_region_filter_args=ZoneRegionFilter (zone=None, region=None)",
                    _ref_zrp(use="True", zone="None"))))
    out.append(("X4 палитра зон + W2 + zone_region_filter_args без зон",
                palette_zone + "\n" + map_zone + "\n" + _fm_typed(
                    _ref_filter(use_zone=True, zone_name="zone_id"),
                    _ref_zrp(use="True", zone="1"))))
    # --- R: «Создать свойство по зонам/значениям» — тип СТРОКИ таблицы -------------
    # Мануал 26.2 (стр. 2733): «Созданному свойству АВТОМАТИЧЕСКИ присваивается
    # дискретный шаблон» → это документированный путь к ДИСКРЕТНОМУ свойству.
    # Схема строки не закрыта (B4): перебираем КЛАССЫ-кандидаты из `dir(wf)`.
    for cls_name in ("ZoneRegionParameters", "ZonesToUpdateTableParameters",
                     "ZonesToUpdateByHorizonParameters", "ZonesToUpdateByMarkerParameters",
                     "ZonesToUpdateLSParameters", "ZonesRegionsEmptyParametersItem",
                     "ZoneRegionFilterParameters", "ZoneRegionFilterInfo"):
        row = (cls_name + " (use=True, value=1, K1=1, K2=2, name='Z1')")
        out.append((f"R1 create_by_zones rows=[{cls_name}]",
                    "grid_property_create_by_zones ("
                    "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d'), "
                    "result_grid_property=typed_object_name (obj_name='ZONES_D', "
                    "obj_type='Grid3dProperty'), zones_table=[" + row + "])"))
    out.append(("R2 create_by_zones rows=[ZoneRegionParameters(k1,k2,zone)]",
                "grid_property_create_by_zones ("
                "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d'), "
                "result_grid_property=typed_object_name (obj_name='ZONES_D', "
                "obj_type='Grid3dProperty'), zones_table=[ZoneRegionParameters (use=True, "
                "value=1, k1=1, k2=2, zone='Z1')])"))
    out.append(("R3 create_by_values rows=[ZoneRegionParameters(use,K1,K2,value)]",
                "grid_property_create_by_values ("
                "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d'), "
                "result_grid_property=typed_object_name (obj_name='ZONES_DV', "
                "obj_type='Grid3dProperty'), zones_table=[ZoneRegionParameters (use=True, "
                "value=1, K1=1, K2=2)])"))
    # --- B: CLOUD1.2-связка (калькулятор discrete_output + палитра) — B4 не пробовал --
    palette_facies = ("create_object_template (name='FACIES', type='Discrete palette', "
                      "units='no', numeric_precision=2, discrete_data=["
                      "ColorDataDiscrete (value=0, name='UNKNOWN', red=200, green=200, blue=200, pattern='608'), "
                      "ColorDataDiscrete (value=1, name='SANDSTONE', red=255, green=255, blue=0, pattern='620'), "
                      "ColorDataDiscrete (value=2, name='SHALE', red=0, green=170, blue=0, pattern='608'), "
                      "ColorDataDiscrete (value=3, name='HARD', red=170, green=0, blue=0, pattern='608'), "
                      "ColorDataDiscrete (value=8, name='COAL', red=0, green=0, blue=0, pattern='608')])")
    map_facies = ("object_template_mapping (folder=find_object (name='3D-Grids', "
                  "type='TypedFolder'), use_grid=True, grid=find_object (name='main_grid', "
                  "type='Grid3d'), object_template_table=[{'object' : 'FACIES', "
                  "'template_data' : 'FACIES', 'use_local_palette' : False, "
                  "'object_type' : 'Property'}])")
    calc = ("grid_property_calculator (mesh=typed_object_name (obj_name='main_grid', "
            "obj_type='Grid3d'), result_grid_property=typed_object_name (obj_name='FACIES', "
            "obj_type='Grid3dProperty'), discrete_output=True, use_filter=False, "
            "user_cut_for_filter=typed_object_name (obj_name='', obj_type='Grid3dProperty'), "
            "filter_comparator=Comparator (rule='not_equals', value=0), "
            "formula='{formula}', variables={{}})")
    out.append(("B1 палитра + калькулятор(discrete)+маппинг + exists",
                palette_facies + "\n" + calc.format(formula="zone_id") + "\n" + map_facies))
    out.append(("B2 то же, formula='1'",
                palette_facies + "\n" + calc.format(formula="1") + "\n" + map_facies))
    # --- R4: поля строки `ZonesToUpdateTableParameters` (класс ПРИНЯТ тНавом) -------
    for cand in ("k1", "k2", "zone", "zone_name", "name", "value", "code", "facies",
                 "layer_from", "layer_to", "start_layer", "end_layer", "k_from", "k_to",
                 "k_start", "k_end", "k_min", "k_max", "min_k", "max_k", "first_layer",
                 "last_layer", "from_layer", "to_layer", "iz1", "iz2", "z_from", "z_to"):
        out.append((f"R4 ZonesToUpdateTableParameters {cand}=1",
                    "grid_property_create_by_zones ("
                    "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d'), "
                    "result_grid_property=typed_object_name (obj_name='ZONES_D', "
                    "obj_type='Grid3dProperty'), zones_table=[ZonesToUpdateTableParameters "
                    f"(use=True, {cand}=1)])"))
    # --- C: калькулятор(discrete)+палитра → ЧТЕНИЕ шаблона → фациальное заполнение ----
    tmpl_info = ("_p = get_grid_by_name (name='main_grid').get_property_by_name "
                 "(name='FACIES')\n"
                 "out.append('   template-атрибуты: ' + '|'.join([a for a in dir(_p) "
                 "if 'templ' in a.lower() or 'palett' in a.lower()])[:300])\n"
                 "_flush ()")
    out.append(("C1 калькулятор(discrete)+маппинг: FACIES есть? шаблон?",
                palette_facies + "\n" + calc.format(formula="zone_id") + "\n" + map_facies
                + "\n" + tmpl_info))
    facies_fill = ("grid_property_facies_by_wells_log_3d ("
                   "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d'), "
                   "input_data_type='blocked_wells', "
                   "input_partial_cube=typed_object_name (obj_name='', obj_type='InitialBlocks'), "
                   "blocked_wells=typed_object_name (obj_name='FaciesU', obj_type='BlockedWells'), "
                   "statistics=typed_object_name (obj_name='Statistics', "
                   "obj_type='BlockedWellsStatistics'), "
                   "result_grid_property=typed_object_name (obj_name='FACIES', "
                   "obj_type='Grid3dProperty'), use_filter=False, space_type='ijk', "
                   "fade_to_border=False, clear_values=False, "
                   "i3_params=Interpolation3dParameters ("
                   "zone_region_filter=ZoneRegionFilterInfo (use_zone=False, use_region=False, "
                   "zone=typed_object_name (obj_name='', obj_type='Grid3dProperty'), "
                   "region=typed_object_name (obj_name='', obj_type='Grid3dProperty'), "
                   "zone_log=typed_object_name (obj_name='', obj_type=''), "
                   "region_log=typed_object_name (obj_name='', obj_type='')), "
                   "zone_region_filter_args=ZoneRegionFilter (zone=None, region=None), "
                   "ZoneRegionParameters=[ZoneRegionParameters (use=True, zone=None, "
                   "region=None, facies_modeling_method='sis_ordering_cubes', classic_sis=False, "
                   "classic_sis_random_seed=0, facies_order=[], current_facies=None, "
                   + _REF_RESTRICT + ", parameters=["
                   "ZoneRegionFaciesParameters (facies=None, params=InterpolationParametersItem "
                   "(use=True, interpolator_type='kriging')), "
                   "ZoneRegionFaciesParameters (facies=0, params=InterpolationParametersItem "
                   "(use=True, interpolator_type='kriging')), "
                   "ZoneRegionFaciesParameters (facies=1, params=InterpolationParametersItem "
                   "(use=True, interpolator_type='kriging')), "
                   "ZoneRegionFaciesParameters (facies=2, params=InterpolationParametersItem "
                   "(use=True, interpolator_type='kriging')), "
                   "ZoneRegionFaciesParameters (facies=3, params=InterpolationParametersItem "
                   "(use=True, interpolator_type='kriging')), "
                   "ZoneRegionFaciesParameters (facies=8, params=InterpolationParametersItem "
                   "(use=True, interpolator_type='kriging'))])]))")
    out.append(("C2 C1 + facies_by_wells_log_3d (дискретный куб из палитры)",
                palette_facies + "\n" + calc.format(formula="zone_id") + "\n" + map_facies
                + "\n" + facies_fill))
    # --- S: ФУНКЦИИ ФАЦИЙ, КОТОРЫЕ СОЗДАЮТ КУБ САМИ (мануал 26.2, стр. 2616/2628/2636/2683)
    # Методика: тНав сам называет недостающий аргумент → строим цепочку по одному аргументу.
    mesh_t = "mesh=typed_object_name (obj_name='main_grid', obj_type='Grid3d')"
    result_t = ("result_grid_property=typed_object_name (obj_name='FACIES', "
                "obj_type='Grid3dProperty')")
    blocked_t = ("blocked_wells=typed_object_name (obj_name='FaciesU', "
                 "obj_type='BlockedWells')")
    stats_t = ("statistics=typed_object_name (obj_name='Statistics', "
               "obj_type='BlockedWellsStatistics')")
    i3_min = ("i3_params=Interpolation3dParameters (zone_region_filter=ZoneRegionFilterInfo "
              "(use_zone=False, use_region=False, "
              "zone=typed_object_name (obj_name='', obj_type='Grid3dProperty'), "
              "region=typed_object_name (obj_name='', obj_type='Grid3dProperty'), "
              "zone_log=typed_object_name (obj_name='', obj_type=''), "
              "region_log=typed_object_name (obj_name='', obj_type='')), "
              "zone_region_filter_args=ZoneRegionFilter (zone=None, region=None))")
    chains = (
        "grid_property_object_based_simulation",
        "grid_property_facies_by_wells_log_tgs_3d",
        "grid_property_facies_by_wells_log_pgs_3d",
        "grid_property_facies_by_wells_log_mps_3d",
        "grid_property_interpolate_by_wells_log_sgs_multilayer_facies",
    )
    for fn in chains:
        steps = ("", mesh_t, f"{mesh_t}, {result_t}",
                 f"{mesh_t}, {blocked_t}, {result_t}",
                 f"{mesh_t}, {blocked_t}, {stats_t}, {result_t}",
                 f"{mesh_t}, {blocked_t}, {stats_t}, {result_t}, {i3_min}")
        for step_no, args in enumerate(steps):
            out.append((f"S {fn} шаг{step_no}", f"{fn} ({args})" if args else f"{fn} ()"))
    # --- U: ПОСЛОЙНОЕ ФАЦИАЛЬНОЕ МОДЕЛИРОВАНИЕ (мануал 26.2, 57.3.12, стр. 2692+) ---
    # «Сетка. Выбор сетки для СОЗДАНИЯ СВОЙСТВА», «Свойство. Выбрать название свойства,
    # для которого интерполируются данные», «Исходные данные: Кривая ГИС»; в конце —
    # «присвойте шаблон литологии к свойству» (то есть куб СОЗДАЁТСЯ функцией, а палитра
    # назначается ПОСЛЕ). Это прямо снимает блокер B4 «нужен предсозданный куб».
    well_log_t = "well_log=typed_object_name (obj_name='LIT', obj_type='WellLog')"
    for fn in ("grid_property_interpolate_by_wells_log_sgs_multilayer_facies",
               "grid_property_interpolate_by_wells_log_idw_multilayer_facies",
               "grid_property_interpolate_by_wells_log_kriging_multilayer_facies"):
        u_steps = (
            f"{mesh_t}, {result_t}, {well_log_t}",
            f"{mesh_t}, {result_t}, {well_log_t}, use_filter=False, space_type='ijk'",
            f"{mesh_t}, {result_t}, {well_log_t}, use_filter=False, space_type='ijk', "
            "use_selected_wells=False",
            f"{mesh_t}, {result_t}, {well_log_t}, use_filter=False, space_type='ijk', "
            + i3_min,
            f"{mesh_t}, {result_t}, {well_log_t}, use_filter=False, space_type='ijk', "
            "statistics=typed_object_name (obj_name='Statistics', "
            "obj_type='WellLogStatistics')",
        )
        for step_no, args in enumerate(u_steps):
            out.append((f"U {fn} шаг{step_no}", f"{fn} ({args})"))
    # --- K: ПОДТВЕРЖДЁННЫЙ путь к кубу FACIES (проба 10.10, 26.2) ------------------
    # `grid_property_interpolate_by_wells_log_sgs_multilayer_facies (mesh, result,
    # well_log)` СОЗДАЁТ свойство FACIES со значениями кодов литологии (min 0 / max 8 —
    # коды LIT поля). Дальше — палитра: мануал 26.2 (57.3.12, стр. 2692): «В конце
    # расчёта присвойте шаблон литологии к свойству для визуализации фаций».
    sgs_fill = ("grid_property_interpolate_by_wells_log_sgs_multilayer_facies ("
                + mesh_t + ", " + result_t + ", " + well_log_t + ")")
    out.append(("K1 палитра + SGS-multilayer-facies(создаёт FACIES)",
                palette_facies + "\n" + sgs_fill))
    out.append(("K2 K1 + привязка дискретного шаблона к FACIES",
                palette_facies + "\n" + sgs_fill + "\n" + map_facies))
    out.append(("K3 только SGS-multilayer-facies (без палитры)",
                sgs_fill))
    # --- L: НЕОБЯЗАТЕЛЬНЫЕ аргументы подтверждённой функции (для patch_codes) -------
    for cand_label, cand in (
        ("i3_params", i3_min),
        ("variogram", "variogram=VariogramParameters (variogram_type='exponential', sill=1, "
                      "nugget_effect=0.15, range_main=3500, range_normal=3500, "
                      "range_vertical=1750, azimuth=0, dip=0)"),
        ("seed", "use_global_random_seed=True, global_random_seed=7"),
        ("statistics_WLS", "statistics=typed_object_name (obj_name='Statistics', "
                           "obj_type='WellLogStatistics')"),
        ("facies_parameters", "facies_parameters=[ZoneRegionFaciesParameters (facies=None, "
                              "params=InterpolationParametersItem (use=True, "
                              "interpolator_type='sgs'))]"),
    ):
        out.append((f"L {cand_label} на подтверждённом вызове",
                    "grid_property_interpolate_by_wells_log_sgs_multilayer_facies ("
                    + mesh_t + ", " + result_t + ", " + well_log_t + ", " + cand + ")"))
    return out


def build_code(out_path: str, *, only: list[str] | None = None) -> str:
    """Код перебора вариантов (исполняется ВНУТРИ тНава). `only` — подстроки меток."""
    lines: list[str] = [
        "out = []",
        f"OUT = r'{out_path}'",
        "def _flush():",
        "    try:",
        "        fh = open (OUT, 'w', encoding='utf-8')",
        "        fh.write ('\\n'.join (out))",
        "        fh.close ()",
        "    except Exception as e:",
        "        pass",
        "def _rec(label, code):",
        "    try:",
        "        exec(code, globals())",
        "        out.append(label + ': OK')",
        "    except Exception as e:",
        "        out.append(label + ': ' + type(e).__name__ + ': ' + str(e)[:400])",
        "    _flush ()",
        "def _call(label, code):",
        "    _rec (label, code)",
        "def _exists(label, name):",
        "    try:",
        "        ok = get_grid_by_name (name='main_grid').property_exists (name=name)",
        "        out.append('   exists(' + label + ', ' + name + '): ' + str(bool(ok)))",
        "    except Exception as e:",
        "        out.append('   exists(' + label + ', ' + name + '): ' + str(e)[:200])",
        "    _flush ()",
        "def _drop(name):",
        "    try:",
        "        get_grid_by_name (name='main_grid').delete_property_by_name (name=name)",
        "    except Exception as e:",
        "        out.append('   drop ' + name + ': ' + str(e)[:120])",
        "    _flush ()",
        "def _stat(name):",
        "    g = get_grid_by_name (name='main_grid')",
        "    for kind in ('min', 'max', 'mean'):",
        "        try:",
        "            p = g.get_property_by_name (name=name)",
        "            v = p.compute_statistics (type=kind)",
        "            if isinstance (v, dict):",
        "                v = v.get (kind)",
        "            out.append('   stat ' + name + ' ' + kind + ' = ' + str(v)[:40])",
        "        except Exception as e:",
        "            out.append('   stat ' + name + ' ' + kind + ': ' + str(e)[:120])",
        "    _flush ()",
        "out.append('== проба фаций: старт ==')",
        "_flush ()",
        "_stat('zone_id')",
        "_stat('FACIES')",
        "try:",
        "    from __main__.tnav import workflow as wf",
        "    names = [str(n) for n in dir(wf)]",
        "    interest = [n for n in names if 'one' in n and ('ilter' in n or 'arameter' in n)]",
        "    out.append('api: Zone*-классы: ' + '|'.join(sorted(interest))[:1500])",
        "except Exception as e:",
        "    out.append('api: dir(wf) недоступен: ' + str(e)[:200])",
        "_flush ()",
        "_exists('до', 'FACIES')",
    ]
    for label, code in variants():
        if only and not any(sub.lower() in label.lower() for sub in only):
            continue
        lines.append("_call(" + repr(label) + ", " + repr(code) + ")")
        if label.startswith("V0"):
            lines.append("_exists('после палитры', 'FACIES')")
        if label.startswith(("V1 ", "V2 ", "V3 ", "S ", "U ", "K1", "K2", "K3", "L ")):
            lines.append("_exists('после варианта', 'FACIES')")
            lines.append("_stat('FACIES')")
            if label.startswith(("S ", "U ", "K3")):
                lines.append("_drop('FACIES')")
        if label.startswith(("V1 ", "V2 ", "V3 ")):
            lines.append("_drop('FACIES')")
        if label.startswith(("V8 ", "V9 ", "V10 ", "V11 ")):
            lines.append("_drop('ZONES_PROBE')")
            lines.append("_drop('ZONES_PROBE_V')")
    lines += ["out.append('== проба фаций: конец ==')", "_flush ()", "'probe-done'"]
    return "\n".join(lines)


def build_introspect_code(out_path: str) -> str:
    """Схема аргументов тНава: имена полей классов и кандидаты значений (без repr).

    тНав не публикует списки допустимых значений параметров (в мануалах их нет),
    поэтому схема снимается интроспекцией: только ИМЕНА атрибутов (строки), без
    вывода объектов (`__repr__` удалённого объекта роняет задачу тНава).
    """
    return "\n".join([
        "out = []",
        f"OUT = r'{out_path}'",
        "def _flush():",
        "    try:",
        "        fh = open (OUT, 'w', encoding='utf-8')",
        "        fh.write ('\\n'.join (out))",
        "        fh.close ()",
        "    except Exception:",
        "        pass",
        "def _names(obj, label):",
        "    try:",
        "        ns = [str(n) for n in dir(obj) if not str(n).startswith('_')]",
        "        out.append(label + ': ' + '|'.join(ns)[:2000])",
        "    except Exception as e:",
        "        out.append(label + ': ERR ' + str(e)[:200])",
        "from __main__.tnav import workflow as wf",
        "import inspect",
        "for nm in ('grid_property_facies_modeling', 'grid_property_facies_by_wells_log_3d', "
        "'grid_property_create_by_zones', 'grid_property_create_by_values', "
        "'create_object_template', 'object_template_mapping', 'geobody_create_by_property'):",
        "    fn = getattr(wf, nm, None)",
        "    try:",
        "        out.append(nm + ' SIG: ' + str(inspect.signature(fn)))",
        "    except Exception as e:",
        "        out.append(nm + ' SIG ERR: ' + str(e)[:120])",
        "    try:",
        "        out.append(nm + ' DOC: ' + str(getattr(fn, '__doc__', ''))[:1200])",
        "    except Exception as e:",
        "        out.append(nm + ' DOC ERR: ' + str(e)[:120])",
        "    _flush ()",
        "for nm in ('Interpolation3dParameters', 'InterpolationParametersItem', "
        "'ZoneRegionFaciesParameters', 'ZoneRegionParameters', 'ZoneRegionFilterInfo'):",
        "    cls = getattr(wf, nm, None)",
        "    try:",
        "        out.append(nm + ' SIG: ' + str(inspect.signature(cls)))",
        "    except Exception as e:",
        "        out.append(nm + ' SIG ERR: ' + str(e)[:120])",
        "    try:",
        "        out.append(nm + ' CLASSDOC: ' + str(getattr(cls, '__doc__', ''))[:600])",
        "    except Exception as e:",
        "        out.append(nm + ' CLASSDOC ERR: ' + str(e)[:120])",
        "    _flush ()",
        "try:",
        "    names = [str(n) for n in dir(wf)]",
        "    cand = [n for n in names if ('nterpolator' in n or 'ossible' in n "
        "or 'alue' in n.lower() or 'ethod' in n)]",
        "    out.append('wf: кандидаты (interpolator/possible/value/method): ' "
        "+ '|'.join(sorted(cand))[:2500])",
        "except Exception as e:",
        "    out.append('wf: ERR ' + str(e)[:200])",
        "_flush ()",
        "_names(wf.InterpolationParametersItem, 'schema InterpolationParametersItem')",
        "_flush ()",
        "_names(wf.ZoneRegionFaciesParameters, 'schema ZoneRegionFaciesParameters')",
        "_flush ()",
        "_names(wf.ZoneRegionParameters, 'schema ZoneRegionParameters')",
        "_flush ()",
        "try:",
        "    doc = getattr(wf.InterpolationParametersItem, '__doc__', '')",
        "    out.append('doc InterpolationParametersItem: ' + str(doc)[:800])",
        "except Exception as e:",
        "    out.append('doc: ERR ' + str(e)[:200])",
        "_flush ()",
        "out.append('== интроспекция: конец ==')",
        "_flush ()",
        "'introspect-done'",
    ])


def build_schema_code(out_path: str) -> str:
    """СХЕМА: механический поиск списка допустимых аргументов тНава (без вывода объектов).

    Печатаем ТОЛЬКО строки (имена в `dir`, ключи `__dict__`, имена типов значений):
    вывод tNav-объектов через `__repr__` роняет задачу тНава (access violation,
    проверено пробой). Цель — найти генератор/wrapper, перечисляющий аргументы.
    """
    return "\n".join([
        "out = []",
        f"OUT = r'{out_path}'",
        "def _flush():",
        "    try:",
        "        fh = open (OUT, 'w', encoding='utf-8')",
        "        fh.write ('\\n'.join (out))",
        "        fh.close ()",
        "    except Exception:",
        "        pass",
        "from __main__.tnav import workflow as wf",
        "try:",
        "    names = [str(n) for n in dir(wf)]",
        "    keys = ('nterpolat', 'api_', 'struct', 'Field', 'field', 'chema', "
        "'rgument', 'ignature', 'Wrapper', 'wrapper', 'Descriptor')",
        "    interest = [n for n in names if any(k in n for k in keys)]",
        "    out.append('NAMES(' + str(len(names)) + '): ' + '|'.join(sorted(interest))[:4500])",
        "except Exception as e:",
        "    out.append('NAMES ERR: ' + str(e)[:200])",
        "_flush ()",
        "for nm in ('Interpolation3dParameters_class', 'InterpolationParametersItem_class', "
        "'ZoneRegionParameters_class', 'ZoneRegionFaciesParameters_class', "
        "'ZoneRegionFilterInfo_class', 'ZoneRegionFilter_class'):",
        "    obj = getattr(wf, nm, None)",
        "    if obj is None:",
        "        out.append(nm + ': НЕТ'); continue",
        "    try:",
        "        out.append(nm + ' DIR: ' + '|'.join(str(n) for n in dir(obj) "
        "if not str(n).startswith('__'))[:1500])",
        "    except Exception as e:",
        "        out.append(nm + ' DIR ERR: ' + str(e)[:150])",
        "    try:",
        "        holder = getattr(obj, '__dict__', None)",
        "        if isinstance(holder, dict):",
        "            out.append(nm + ' DICT: ' + '|'.join(sorted(map(str, holder)))[:1500])",
        "    except Exception as e:",
        "        out.append(nm + ' DICT ERR: ' + str(e)[:150])",
        "    _flush ()",
        "for nm in ('ZoneRegionParameters', 'InterpolationParametersItem', "
        "'ZoneRegionFaciesParameters', 'Interpolation3dParameters'):",
        "    cls = getattr(wf, nm, None)",
        "    if cls is None:",
        "        out.append(nm + ': НЕТ'); continue",
        "    try:",
        "        inst = cls(use=True)",
        "        out.append(nm + ' INST DIR: ' + '|'.join(str(n) for n in dir(inst) "
        "if not str(n).startswith('__'))[:1500])",
        "        holder = getattr(inst, '__dict__', None)",
        "        if isinstance(holder, dict):",
        "            pairs = [str(k) + ':' + type(v).__name__ for k, v in holder.items()]",
        "            out.append(nm + ' INST DICT: ' + '|'.join(sorted(pairs))[:2000])",
        "        else:",
        "            out.append(nm + ' INST DICT: тип ' + type(holder).__name__)",
        "    except Exception as e:",
        "        out.append(nm + ' INST ERR: ' + str(e)[:200])",
        "    _flush ()",
        "try:",
        "    out.append('begin_wf_item: ' + str(type(getattr(wf, 'begin_wf_item', None)).__name__))",
        "except Exception as e:",
        "    out.append('begin_wf_item ERR: ' + str(e)[:150])",
        "out.append('== схема: конец ==')",
        "_flush ()",
        "'schema-done'",
    ])


def build_check_code(out_path: str) -> str:
    return "\n".join([
        "out = []",
        f"OUT = r'{out_path}'",
        "def _stat(name):",
        "    g = get_grid_by_name (name='main_grid')",
        "    for kind in ('min', 'max', 'mean'):",
        "        try:",
        "            v = g.get_property_by_name (name=name).compute_statistics (type=kind)",
        "            if isinstance (v, dict):",
        "                v = v.get (kind)",
        "            out.append('check: ' + name + ' ' + kind + ' = ' + str(v)[:40])",
        "        except Exception as e:",
        "            out.append('check: ' + name + ' ' + kind + ' ERR ' + str(e)[:120])",
        "def _snap():",
        "    try:",
        "        ok = get_grid_by_name (name='main_grid').property_exists (name='FACIES')",
        "        out.append('check: FACIES exists = ' + str(bool(ok)))",
        "    except Exception as e:",
        "        out.append('check: ' + str(e)[:300])",
        "    try:",
        "        ps = get_grid_by_name (name='main_grid').get_all_properties ()",
        "        names = []",
        "        for p in ps:",
        "            n = getattr(p, 'name', None)",
        "            names.append(n if isinstance(n, str) else '?')",
        "        out.append('check: props = ' + '|'.join(names))",
        "    except Exception as e:",
        "        out.append('check props: ' + str(e)[:300])",
        "    for nm in ('zone_id', 'LIT', 'FACIES', 'PORO'):",
        "        _stat(nm)",
        "    for label, name, typ in (('blocked_wells', 'FaciesU', 'BlockedWells'), "
        "('statistics', 'Statistics', 'BlockedWellsStatistics'), "
        "('grid', 'main_grid', 'Grid3d'), "
        "('zone_prop', 'zone_id', 'Grid3dProperty')):",
        "        try:",
        "            find_object (name=name, type=typ)",
        "            out.append('check: object ' + label + ' (' + name + '/' + typ + ') = OK')",
        "        except Exception as e:",
        "            out.append('check: object ' + label + ' (' + name + '/' + typ + ') = ' "
        "+ str(e)[:160])",
        "    try:",
        "        fh = open (OUT, 'w', encoding='utf-8')",
        "        fh.write ('\\n'.join (out))",
        "        fh.close ()",
        "    except Exception:",
        "        pass",
        "_snap ()",
        "'check-done'",
    ])


def _donor(explicit: str | None, cfg) -> Path:
    """Донор: явный каталог (--donor) либо первый models/* с файлом проекта."""
    if explicit:
        return Path(explicit)
    models_dir = cfg.path("project.models_dir", "models")
    for cand in sorted(p for p in Path(models_dir).glob("*") if p.is_dir()):
        if list(cand.glob("*.snp")) or list(cand.glob("*.tnavproject")):
            return cand
    raise SystemExit(f"не найден проект-донор в {models_dir}: укажите --donor")


def _project_file(donor: Path) -> Path:
    for pat in ("*.snp", "*.tnavproject"):
        for p in sorted(donor.glob(pat)):
            return p
    raise SystemExit(f"в доноре {donor} нет файла проекта (*.snp/*.tnavproject)")


def main() -> int:
    parser = argparse.ArgumentParser(description="проба фациального моделирования")
    parser.add_argument("--donor", default=None, help="каталог проекта-донора")
    parser.add_argument("--field", default=None, help="имя поля (по умолчанию из config)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="файл результата пробы")
    parser.add_argument("--stage", default=None,
                        help="исполнить готовый отрендеренный этап (проверка артефакта)")
    parser.add_argument("--introspect", action="store_true",
                        help="снять СХЕМУ аргументов тНава (имена полей классов), без расчётов")
    parser.add_argument("--schema", action="store_true",
                        help="механический поиск списка допустимых аргументов (dir/__dict__)")
    parser.add_argument("--state", action="store_true",
                        help="снимок проекта: свойства сетки + статистики (зон/литологии/фаций)")
    parser.add_argument("--variants", default=None,
                        help="подстроки меток вариантов через запятую (напр. V2,V3)")
    args = parser.parse_args()

    cfg = load_config(None)
    field = args.field or str(cfg.get("project.default_field", "") or "")
    donor = _donor(args.donor, cfg)
    models_dir = cfg.path("project.models_dir", "models")
    probe = Path(models_dir) / PROBE_DIR_NAME
    wf_dir = Path(models_dir) / WF_DIR_NAME

    if cfg.get("tnavigator.runtime_env_dir"):
        print("окружение тНава: изоляция — общим механизмом клиента "
              "(tnavigator.runtime_env_dir, данные конфига)", flush=True)
    else:
        print("ВНИМАНИЕ: в конфиге нет `tnavigator.runtime_env_dir` — процессам тНава "
              "может быть отказано в записи вне рабочего каталога", flush=True)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = cfg.resolve(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    wf_dir.mkdir(parents=True, exist_ok=True)
    if probe.exists():
        shutil.rmtree(probe, ignore_errors=True)
    shutil.copytree(donor, probe)
    project_file = _project_file(probe)
    print(f"донор: {donor}\nпроба: {probe}\nпроект: {project_file.name}\n"
          f"результат: {out_path}", flush=True)

    body = None
    if args.stage:
        body = Path(args.stage).read_text(encoding="utf-8")
    only = [x.strip() for x in args.variants.split(",")] if args.variants else None
    if args.schema:
        code: str | None = build_schema_code(out_path.as_posix())
    elif args.state:
        code = build_check_code(out_path.as_posix())
    elif args.introspect:
        code = build_introspect_code(out_path.as_posix())
    elif body is None:
        code = build_code(out_path.as_posix(), only=only)
    else:
        code = None
    cfg.set("tnavigator.dry_run", False)
    client = TnavClient(cfg)
    client.dry_run = False
    client.set_log(lambda line: print(f"  · {line[:200]}", flush=True))
    try:
        client.open(project_path=project_file, create=False)
        if code is not None:
            wf = wf_dir / "probe_facies.py"
            wf.write_text(code, encoding="utf-8")
            res = client.run_workflow(wf, save=False, timeout_sec=1800)
            print("проба (перебор): ok=", res.ok, str(res.error or "")[:400], flush=True)
        else:
            # проверка ГОТОВОГО артефакта: исполняем отрендеренный этап, затем снимок
            stage_out = out_path.with_name(out_path.stem + "_stage.txt")
            res = client.run_workflow(Path(args.stage), save=False, timeout_sec=1800)
            print("этап:", Path(args.stage).name, "ok=", res.ok,
                  str(res.error or "")[:400], flush=True)
            stage_out.write_text("этап: " + Path(args.stage).name + " ok=" + str(res.ok)
                                 + "\n" + str(res.error or "")[:4000] + "\n",
                                 encoding="utf-8")
            wf = wf_dir / "probe_facies_check.py"
            wf.write_text(build_check_code(out_path.as_posix()), encoding="utf-8")
            res2 = client.run_workflow(wf, save=False, timeout_sec=600)
            print("проверка свойств: ok=", res2.ok, str(res2.error or "")[:200], flush=True)
            print(f"результат этапа: {stage_out}", flush=True)
    finally:
        client.close()

    if out_path.exists():
        print("\n=== СЫРОЙ РЕЗУЛЬТАТ ПРОБЫ ===", flush=True)
        print(out_path.read_text(encoding="utf-8"), flush=True)
    else:
        print("файл результата не создан (проба не дошла до записи)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
