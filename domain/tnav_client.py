"""C7 — АДАПТЕР tNavigator через Python API (Сервер Управления) — СОЗДАЁТ ПРОЕКТ.

Реальный протокол (подтверждён по исходнику `tNavigator_python_API.py` v26.1):

    opts    = tnav.ConnectionOptions(license_settings='...license.ini', license_type='network')
    conn    = tnav.Connection(path_to_exe='.../tNavigator-con.exe', connection_options=opts)
    project = conn.create_project(path='...snp', project_type=ProjectType.GD)   # GD = Geology Designer
    #   либо conn.open_project(path='...snp', project_type=ProjectType.GD)
    project.init_api_license()                            # лицензия API (метод проекта)
    project.run_py_code(code=<workflow>, save=True)       # исполняет воркфлоу -> строит модель
    project.close_project()                               # -> .snp-проект

`tNavigator-con.exe` выступает «Сервером Управления» — работает headless, без GUI.
Итог — проект `.snp`/`.tnavproject`, который можно открыть в тНаве.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from core.config import Config


class TnavError(RuntimeError):
    pass


@dataclass
class TnavRunResult:
    ok: bool
    kind: str                      # "workflow" | "deck" | "dry_run"
    target: str
    returncode: int | None = None
    results_dir: str = ""
    project: str = ""              # путь к созданному .snp/.tnavproject
    command: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    error: str = ""
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "kind": self.kind, "target": self.target,
                "returncode": self.returncode, "results_dir": self.results_dir,
                "project": self.project, "command": self.command,
                "stdout_tail": self.stdout_tail, "error": self.error,
                "artifacts": self.artifacts}


class TnavClient:
    """Граница вокруг тНава: сборка модели через Python API + сохранение проекта."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        sec = cfg.section("tnavigator")
        self.install_dir = Path(str(sec.get("install_dir", "")))
        self.executable = Path(str(sec.get("executable", "")))
        self.flags = [str(f) for f in (sec.get("flags") or [])]
        self.cpu_num = int(sec.get("cpu_num", 0) or 0)
        self.cpu_flag = str(sec.get("cpu_flag", "--cpu-num") or "--cpu-num")
        self.timeout_sec = int(sec.get("timeout_sec", 3600) or 3600)
        self.dry_run = bool(sec.get("dry_run", True))
        self.license_features = list(sec.get("license_features") or ["FEAT_GEOLOGY_DESIGNER"])
        self._conn = None
        self._project = None
        self._log = None
        self._api_mod = None
        # Переменные окружения процессов тНава — ДАННЫЕ (`tnavigator.runtime_env_*`).
        self.env_dir = cfg.resolve(sec.get("runtime_env_dir")) \
            if sec.get("runtime_env_dir") else None
        self.env_vars = [str(v) for v in (sec.get("runtime_env_vars") or [])]
        self._env_ready = False

    def prepare_runtime_env(self) -> list[str]:
        """Перенаправить переменные окружения процессов тНава в рабочий каталог.

        На этой машине процессам тНава запрещена запись вне рабочего каталога
        (подтверждено пробой на живой лицензии: `local_dispatcher_*.log`,
        `tnav_py_run_*` → «Отказано в доступе»). Каталог и список переменных —
        ДАННЫЕ (`tnavigator.runtime_env_dir` / `runtime_env_vars`); нет данных —
        ничего не меняется («неизвестное != ложь»).
        """
        if self._env_ready or self.env_dir is None or not self.env_vars:
            return []
        prepared: list[str] = []
        try:
            # ПОРЯДОК ВАЖЕН: лицензионный ini читается из ИСХОДНОГО APPDATA
            # (там `main__license_type_setting` и ключи `*_local` для `tnav://`),
            # копируется в новый рабочий каталог и только затем APPDATA подменяется.
            # Подтверждено пробой на живой лицензии: минимальный набор —
            # APPDATA + TEMP + TMP (падали local_dispatcher_*.log и tnav_py_run_*).
            src_appdata = os.environ.get("APPDATA") or ""
            if src_appdata:
                candidates = [Path(self.cfg.get("tnavigator.license_settings_file", "")
                                   or Path(src_appdata) / "tNavigator")]
                for src_dir in candidates:
                    ini_src = src_dir if src_dir.suffix.lower() == ".ini" \
                        else src_dir / "tNavigator.ini"
                    if not ini_src.is_file():
                        continue
                    ini_dst = Path(self.env_dir) / "APPDATA" / "tNavigator" \
                        / ini_src.name
                    ini_dst.parent.mkdir(parents=True, exist_ok=True)
                    if not ini_dst.is_file():
                        shutil.copy2(ini_src, ini_dst)
                    break
            for name in self.env_vars:
                target = Path(self.env_dir) / name
                target.mkdir(parents=True, exist_ok=True)
                os.environ[name] = str(target)
                prepared.append(name)
            self._env_ready = True
            self._emit(f"тНав: окружение переведено в {self.env_dir} ({', '.join(prepared)})")
        except OSError as exc:                      # noqa: PERF203 — причина в лог, не молча
            self._emit(f"тНав: окружение не перенаправлено — {exc}")
        return prepared

    def set_log(self, log) -> None:
        """Колбэк логирования (подключение, создание проекта, лицензия, воркфлоу…)."""
        self._log = log

    def _emit(self, text: str) -> None:
        if callable(self._log):
            try:
                self._log(text)
            except Exception:                 # noqa: BLE001
                pass

    # -- preflight ----------------------------------------------------------
    def preflight(self) -> dict:
        self.prepare_runtime_env()          # процессы тНава пишут только в рабочий каталог
        info = {"executable": str(self.executable), "present": self.executable.exists(),
                "version": "", "api_available": self._api_available(),
                "license_features": self.license_features, "ok": False}
        if self.executable.exists():
            try:
                proc = subprocess.run([str(self.executable), "--version"], capture_output=True,
                                      text=True, timeout=int(self.cfg.get(
                                          "tnavigator.preflight_timeout_sec", 60) or 60),
                                      check=False)
                text = ((proc.stdout or "") + (proc.stderr or "")).strip()
                info["version"] = text.splitlines()[0] if text else ""
            except Exception as exc:          # noqa: BLE001
                info["version"] = f"n/a ({exc})"
        info["ok"] = info["present"]
        return info

    def _api_available(self) -> bool:
        if not self.install_dir.exists():
            return False
        return bool(list(self.install_dir.glob("tNavigator_python_API*"))
                    or list(self.install_dir.glob("**/tNavigator_python_API*")))

    def _import_api(self):
        """Ленивый импорт `tNavigator_python_API` (для исполнения — из каталога).

        Библиотека поставляется zip-пакетом `libs/python/tNavigator_python_API.zip`,
        но импорт ИЗ АРХИВА не работает для подключения: `Connection` запускает
        `tNavigator-API-client.exe`, путь к которому вычисляется от `__file__`
        (внутри архива файла на диске нет → `Popen` падает с WinError 2). Поэтому
        zip распаковывается в локальный кэш (`tnavigator.api_cache_dir`, данные) и
        импортируется оттуда.
        """
        mod = getattr(self, "_api_mod", None)
        if mod is not None:
            return mod
        cache = self._api_cache_dir()
        for z in self.install_dir.glob("**/tNavigator_python_API*.zip"):
            marker = cache / "tNavigator_python_API" / "tNavigator_python_API.py"
            if not marker.is_file():
                self._emit(f"тНав: распаковываю Python API из {z.name} в {cache}")
                import zipfile
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(cache)
        if str(cache) not in sys.path:
            sys.path.insert(0, str(cache))
        for pkg in self.install_dir.glob("**/tNavigator_python_API"):
            if pkg.is_dir() and str(pkg.parent) not in sys.path:
                sys.path.insert(0, str(pkg.parent))
        sys.path.insert(0, str(self.install_dir))
        import importlib
        try:
            self._api_mod = importlib.import_module("tNavigator_python_API")
        except ImportError as exc:                 # noqa: N999
            raise TnavError(
                f"не удалось импортировать tNavigator_python_API "
                f"(искали zip/пакет в {self.install_dir}): {exc}") from exc
        return self._api_mod

    def _api_cache_dir(self) -> Path:
        """Каталог распакованного API (относительный — от корня сервиса)."""
        cache = Path(str(self.cfg.get("tnavigator.api_cache_dir", ".tnav_api")
                         or ".tnav_api"))
        if not cache.is_absolute():
            cache = self.cfg.resolve(cache)
        cache.mkdir(parents=True, exist_ok=True)
        return cache

    # -- лицензия tNavigator -------------------------------------------------
    def _connection_options(self, tnav):
        """Собрать `ConnectionOptions` для сетевой лицензии (из config.local.yaml).

        API v26.1: `ConnectionOptions(license_settings=..., license_type=...)`.
        API v26.2: конструктор БЕЗ аргументов — поля выставляются атрибутами
        (`opts.license_settings = …`). Версия определяется в рантайме: сначала
        kwargs, при TypeError — setattr; если и это не удалось — None (тНав
        возьмёт настройки из %APPDATA%/tNavigator.ini, фичи — request_license_features).
        """
        sec = self.cfg.section("tnavigator")
        lic = dict(sec.get("license") or {})
        url = str(lic.get("url") or "").strip()
        login = str(lic.get("login") or "").strip()
        pwd = str(lic.get("pass") or lic.get("password") or "")
        if not url:
            return None
        if url.lower().startswith("tnav://"):
            # tnav:// — сервер задан в %APPDATA%/tNavigator/tNavigator.ini
            # (ключи *_local): API-клиент получает лицензию сам; файл настроек
            # по пути с кириллицей клиент открыть не может, а без опций лицензия
            # выдаётся корректно (проверено вручную, license.log).
            self._emit("тНав: лицензия tnav:// — полагаюсь на %APPDATA%/tNavigator")
            return None
        opts_cls = getattr(tnav, "ConnectionOptions", None)
        if opts_cls is None:                  # API без ConnectionOptions — None
            return None
        kw: dict = {}
        settings = self._write_license_settings(url, login, pwd)
        if settings is not None:
            kw["license_settings"] = str(settings)
        else:
            kw["license_server_url"] = url
        kw["license_type"] = str(lic.get("type") or "network")
        wait = int(lic.get("wait_sec") or sec.get("license_wait_sec") or 0)
        if wait > 0:
            kw["license_wait_time_limit__secs"] = wait
        try:
            return opts_cls(**kw)
        except TypeError:
            pass
        # API 26.2: конструктор `ConnectionOptions()` БЕЗ аргументов — поля
        # (license_settings/license_server_url/license_type/…) выставляются
        # атрибутами ПОСЛЕ создания объекта.
        try:
            opts = opts_cls()
            for key, value in kw.items():
                setattr(opts, key, value)
            return opts
        except Exception:                     # noqa: BLE001
            self._emit("тНав: ConnectionOptions не принимает настройки — "
                       "лицензия из %APPDATA%/tNavigator")
            return None

    def _write_license_settings(self, url: str, login: str, pwd: str):
        """Записать .ini `[tNavigator_license_settings]` (url/login/pass) — если есть логин.

        Путь по умолчанию — системный temp (ASCII-safe: клиент тНава не открывает
        пути с кириллицей); переопределяется данными `license_settings_file`.
        """
        if not login:
            return None
        raw = self.cfg.get("tnavigator.license_settings_file")
        if raw:
            out = Path(str(raw))
            if not out.is_absolute():
                out = self.cfg.resolve(out)
        else:
            out = Path(tempfile.gettempdir()) / "tnav_license_settings.ini"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("[tNavigator_license_settings]\n"
                       f"url={url}\nlogin={login}\npass={pwd}\n", encoding="utf-8")
        return out

    # -- Python API: проект + воркфлоу --------------------------------------
    def open(self, project_path: str | Path | None = None, *, create: bool = True) -> "TnavClient":
        """Подключиться к тНав, создать/открыть проект, запросить лицензии."""
        if self.dry_run:
            return self
        if not self.executable.is_file():
            raise TnavError(f"Не найден tNavigator-con.exe: {self.executable}")
        self.prepare_runtime_env()          # права записи: окружение → рабочий каталог
        self._emit(f"тНав: подключаюсь к {self.executable.name}")
        tnav = self._import_api()
        try:
            conn_kw: dict = {}
            opts = self._connection_options(tnav)
            if opts is not None:
                conn_kw["connection_options"] = opts
            try:
                self._conn = tnav.Connection(path_to_exe=str(self.executable), **conn_kw)
            except TypeError:
                # API 26.2: Connection без `connection_options` (туториал
                # Markers_statistics.py) — лицензия из локального ini.
                self._emit("тНав: Connection не принимает connection_options — "
                           "подключаюсь без опций")
                self._conn = tnav.Connection(path_to_exe=str(self.executable))
        except Exception as exc:              # noqa: BLE001
            self._emit(f"тНав: ошибка подключения — {exc}")
            raise TnavError(f"не удалось подключиться к тНав: {exc}") from exc
        self._emit("тНав: соединение установлено")

        target = Path(project_path) if project_path else self.cfg.path(
            "project.snp_path", "runs/geology.snp")
        try:
            if Path(target).exists():
                self._emit(f"тНав: открываю проект {target}")
                self._project = self._open_project(target)
            elif create:
                self._emit(f"тНав: создаю проект {target}")
                self._project = self._create_project(target)
            else:
                raise TnavError(f"проект не найден: {target}")
        except TnavError:
            raise
        except Exception as exc:              # noqa: BLE001
            self._emit(f"тНав: ошибка проекта — {exc}")
            raise TnavError(f"не удалось создать/открыть проект тНав: {exc}") from exc
        self._request_license()
        return self

    def _gd_type(self):
        """`ProjectType.GD` ("gd" = Geology Designer) — тип проекта КГМ (или None)."""
        ptype = getattr(self._import_api(), "ProjectType", None)
        return getattr(ptype, "GD", None) if ptype is not None else None

    def _open_project(self, target: Path):
        """Открыть существующий проект (`open_project(path, project_type=GD)`)."""
        gd = self._gd_type()
        if gd is not None:
            try:
                return self._conn.open_project(path=str(target), project_type=gd)
            except Exception:                 # noqa: BLE001 — фолбэк на сигнатуру по умолчанию
                pass
        return self._conn.open_project(path=str(target))

    def _create_project(self, target: Path):
        """Создать проект тНава (подтверждённая сигнатура API v26.1).

        `Connection.create_project(path, project_type, cpu_core_count=None, ...)`.
        Для КГМ используется `ProjectType.GD` ("gd" = Geology Designer).
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        fn = getattr(self._conn, "create_project", None)
        if fn is None:
            raise TnavError("в API тНава нет create_project")
        gd = self._gd_type()
        variants: list[dict] = []
        if gd is not None:
            variants.append({"path": str(target), "project_type": gd})
        variants.append({"path": str(target)})
        variants.append({"file_path": str(target)})
        last = None
        for kwargs in variants:
            try:
                return fn(**kwargs)
            except Exception as exc:          # noqa: BLE001 — пробуем следующую сигнатуру
                last = exc
                continue
        raise TnavError(f"не удалось создать проект (create_project): {last}")

    def _request_license(self) -> None:
        """Активировать фичи лицензии В ПРОЕКТЕ (`request_license_features`).

        Подтверждено туториалом API1.1 (`Markers_statistics.py`):
            project.run_py_code(code='request_license_features '
                                     '(requested_features=[{"feature": "FEAT_GEOLOGY_DESIGNER"}])')

        Это функция самого тНава (исполняется в контексте проекта), её нет в
        клиентской библиотеке `tNavigator_python_API.py`. Без неё функции модулей
        падают с «... is not available due to missing license, it requires one of
        the following features to work: Geology Designer, ...».
        """
        feats = ", ".join('{"feature": "%s"}' % f for f in self.license_features)
        code = f"request_license_features (requested_features=[{feats}])"
        self._emit(f"тНав: активирую фичи лицензии {self.license_features}")
        try:
            self._project.run_py_code(code=code)
        except Exception as exc:              # noqa: BLE001
            self._emit(f"тНав: ошибка активации лицензии — {exc}")
            raise TnavError(f"не удалось активировать фичи тНав ({self.license_features}): {exc}") from exc
        self._emit("тНав: фичи лицензии активированы")

    def run_workflow(self, workflow_path: Path, *, save: bool = True,
                     timeout_sec: int | None = None) -> TnavRunResult:
        """Исполнить воркфлоу в проекте (тНав строит модель) и сохранить проект.

        Ожидание ограничено `timeout_sec` (по умолчанию `tnavigator.timeout_sec`):
        зависший вызов `run_py_code` не должен блокировать прогон навсегда.
        """
        workflow_path = Path(workflow_path)
        if not workflow_path.is_file():
            raise TnavError(f"воркфлоу не найден: {workflow_path}")
        if self.dry_run:
            return TnavRunResult(ok=True, kind="dry_run", target=str(workflow_path),
                                 returncode=0, stdout_tail="dry-run: воркфлоу не исполнялся")
        code = workflow_path.read_text(encoding="utf-8")
        self._emit(f"тНав: исполняю воркфлоу {workflow_path.name} "
                   f"({len(code.splitlines())} строк, save={save})")
        timeout = float(timeout_sec if timeout_sec is not None else self.timeout_sec)
        box: dict = {}

        def worker() -> None:
            try:
                self._project.run_py_code(code=code, save=save)
                box["ok"] = True
            except Exception as exc:          # noqa: BLE001 — ошибку отдаём в результат
                box["error"] = str(exc)

        thread = threading.Thread(target=worker, name="tnav-workflow", daemon=True)
        thread.start()
        thread.join(timeout=timeout if timeout > 0 else None)
        if thread.is_alive():
            self._emit(f"тНав: таймаут воркфлоу ({timeout:g} с) — ожидание прервано")
            return TnavRunResult(ok=False, kind="workflow", target=str(workflow_path),
                                 error=f"таймаут исполнения воркфлоу ({timeout:g} с)")
        if box.get("error"):
            self._emit(f"тНав: ошибка воркфлоу — {box['error']}")
            return TnavRunResult(ok=False, kind="workflow", target=str(workflow_path),
                                 error=str(box["error"]))
        self._emit("тНав: воркфлоу выполнен")
        return TnavRunResult(ok=True, kind="workflow", target=str(workflow_path),
                             returncode=0, project=self.project_path())

    def save_project(self) -> bool:
        if self.dry_run or self._project is None:
            return False
        self._emit("тНав: сохраняю проект")
        try:
            self._project.run_py_code(code="save_project()")
            return True
        except Exception:                     # noqa: BLE001
            return False

    def project_path(self) -> str:
        """Путь проекта (`Project.path`) или пустая строка."""
        if self._project is None:
            return ""
        return str(getattr(self._project, "path", "") or "")

    def close(self) -> None:
        """Закрыть проект И соединение (иначе консоль тНава держит лицензию).

        `Connection.stop()` — задокументированный способ (см. `Connection.__exit__`
        в `tNavigator_python_API.py`): шлёт `stop()` и ждёт до 60 с. Без него каждая
        сессия оставляет процесс `tNavigator-con`, а они исчерпывают лицензию
        «API Client, API Server».
        """
        if self._project is not None:
            self._emit("тНав: закрываю проект")
            try:
                self._project.close_project()
            except Exception:                 # noqa: BLE001
                pass
            finally:
                self._project = None
        if self._conn is not None:
            self._emit("тНав: останавливаю соединение (освобождаю лицензию)")
            try:
                stop = getattr(self._conn, "stop", None)
                if callable(stop):
                    stop()
            except Exception:                 # noqa: BLE001
                pass
            finally:
                self._conn = None

    def open_gui(self, project_path: Path) -> bool:
        """Открыть созданный проект в GUI тНава (tNavigator.exe)."""
        project_path = Path(project_path)
        gui = self.install_dir / "tNavigator.exe"
        if not gui.is_file() or not project_path.exists():
            self._emit(f"открытие в GUI: не найден tNavigator.exe или проект {project_path}")
            return False
        try:
            subprocess.Popen([str(gui), str(project_path)])
            self._emit(f"открываю проект в тНаве (GUI): {project_path.name}")
            return True
        except Exception as exc:              # noqa: BLE001
            self._emit(f"не удалось открыть GUI тНава: {exc}")
            return False

    def __enter__(self) -> "TnavClient":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- fallback: запуск дека (консольный симулятор) ----------------------
    def _build_deck_command(self, deck: Path) -> list[str]:
        cmd = [str(self.executable), *self.flags]
        if self.cpu_num > 0:
            cmd.append(f"{self.cpu_flag}={self.cpu_num}")
        cmd.append(deck.name)
        return cmd

    def run_deck(self, deck: Path) -> TnavRunResult:
        deck = Path(deck)
        if self.dry_run:
            return TnavRunResult(ok=True, kind="dry_run", target=str(deck), returncode=0,
                                 results_dir=str(deck.parent / "RESULTS"),
                                 stdout_tail="dry-run: дек не исполнялся")
        if not self.executable.exists():
            raise TnavError(f"tNavigator-con.exe не найден: {self.executable}")
        cmd = self._build_deck_command(deck)
        try:
            proc = subprocess.run(cmd, cwd=str(deck.parent), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=self.timeout_sec, check=False)
        except subprocess.TimeoutExpired as exc:
            raise TnavError(f"таймаут расчёта тНава ({self.timeout_sec} с)") from exc
        marker = deck.with_suffix(".eclend")
        ok = marker.exists() and proc.returncode == 0
        return TnavRunResult(ok=ok, kind="deck", target=str(deck), returncode=proc.returncode,
                             results_dir=str(deck.parent / "RESULTS"), command=cmd,
                             stdout_tail=(proc.stdout or "")[-2000:],
                             error="" if ok else f"rc={proc.returncode}")


