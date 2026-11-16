"""Пробники тНава: генераторы py-сниппетов для файлового канала «код → tmp → разбор».

`run_py_code` не возвращает значения наружу (проверено на 26.1), поэтому все
runtime-свидетельства читаются единым каналом: сниппет пишет результат в tmp-файл,
координатор разбирает его (`_read_py_capture`). Сниппеты защищены try/except —
ошибка API не роняет прогон, свидетельство просто не прикладывается.
"""
from __future__ import annotations


def _s(path) -> str:
    return str(path).replace("\\", "/")


def property_mean_code(grid_name: str, prop_name: str, out_path) -> str:
    """Среднее значение свойства сетки (`prop.compute_statistics(type='mean')`)."""
    return (
        f"g = get_grid_by_name (name='{grid_name}')\n"
        "v = None\n"
        "try:\n"
        f"    p = g.get_property_by_name (name='{prop_name}')\n"
        "    v = p.compute_statistics (type='mean')\n"
        "except Exception:\n"
        "    v = None\n"
        "if isinstance (v, dict):\n"
        "    v = v.get ('mean')\n"
        f"open (r'{_s(out_path)}', 'w').write (repr (float (v)) if isinstance (v, (int, float)) else '')\n"
        "'ok'\n"
    )


def horizon_stats_code(horizon_name: str, out_path) -> str:
    """Статистика горизонта: ячейки|бланк|min|max|mean (для будущих проверок G-STRUCT)."""
    return (
        "import numpy as np\n"
        f"h = get_horizon_by_name (name='{horizon_name}')\n"
        "a = np.asarray (h.get_2d_np_array (), dtype=float)\n"
        "flat = a.reshape (-1)\n"
        "blank = int (np.sum (np.abs (flat) >= 1.0e6))\n"
        "finite = flat[np.abs (flat) < 1.0e6]\n"
        "stats = ('%d|%d|%.6f|%.6f|%.6f' % (flat.size, blank,\n"
        "         float (finite.min ()) if finite.size else 0.0,\n"
        "         float (finite.max ()) if finite.size else 0.0,\n"
        "         float (finite.mean ()) if finite.size else 0.0))\n"
        f"open (r'{_s(out_path)}', 'w').write (stats)\n"
        "'ok'\n"
    )
