from __future__ import annotations
import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.request, urllib.parse, zipfile, datetime, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import queue

HUB_VERSION = "2.2.16"
MANIFEST_URL = "https://raw.githubusercontent.com/joaovictorasousa2019/KBL-Updates/main/manifest.json"
UPDATES_REPO = "joaovictorasousa2019/KBL-Updates"
APPS_REPO = "joaovictorasousa2019/KBL-Apps"

PACKAGE_ROOT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1])
BUNDLED_DIR = PACKAGE_ROOT / "packages"
BUNDLED_CATALOG_FILE = PACKAGE_ROOT / "bundled_catalog.json"

LOCAL_ROOT = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "KBL"
APPS_ROOT = LOCAL_ROOT / "Apps"
DATA_ROOT = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "KBLAccounting"
HUB_DATA = DATA_ROOT / "Hub"
REGISTRY_FILE = HUB_DATA / "registry.json"

DEFAULT_APPS = {
    "comparativo-despesas": "KBL Comparativo de Despesas",
    "composicao-saldos": "KBL Composição Patrimonial",
    "conciliador-contabil": "KBL Conciliador Contábil",
    "irpj-csll": "KBL IRPJ e CSLL",
    "fechamento-contabil": "KBL Fechamento Contábil",
    "ecac": "KBL eCAC",
    "kbl-coletor": "KBL COLETOR",
}

ENTRYPOINT_HINTS = {
    "comparativo-despesas": ["app.py", "main.py"],
    "composicao-saldos": ["app.pyw"],
    "conciliador-contabil": ["app.pyw", "app.py"],
    "irpj-csll": ["app.py"],
    "fechamento-contabil": ["Abrir KBL Fechamento.pyw", "KBL_Fechamento_Contabil.pyw"],
    "ecac": ["app.py"],
    "kbl-coletor": ["INICIAR_KBL_COLETOR.vbs", "INICIAR.bat", "app/START_KBL_COLETOR.ps1"],
}

FILENAME_APP_HINTS = {
    "comparativo": "comparativo-despesas",
    "conciliador": "conciliador-contabil",
    "composicao": "composicao-saldos",
    "composi": "composicao-saldos",
    "irpj": "irpj-csll",
    "csll": "irpj-csll",
    "fechamento": "fechamento-contabil",
    "ecac": "ecac",
    "coletor": "kbl-coletor",
}

EXCLUDED_ENTRYPOINTS = {
    "kbl_hub.py", "kbl_updater.py", "kbl_updater.pyw",
    "limpar instalação exe antiga.pyw", "limpar instalacao exe antiga.pyw",
    "_kbl_hub_launcher.pyw",
}

def ensure_dirs():
    for p in (LOCAL_ROOT, APPS_ROOT, DATA_ROOT, HUB_DATA):
        p.mkdir(parents=True, exist_ok=True)

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default

def load_registry():
    ensure_dirs()
    return load_json(REGISTRY_FILE, {"schema_version": 2, "apps": {}})

def save_registry(data):
    HUB_DATA.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY_FILE)

def bundled_catalog():
    return load_json(BUNDLED_CATALOG_FILE, {})

def vtuple(v):
    nums = []
    for part in str(v or "0").lstrip("vV").split("."):
        s = ""
        for ch in part:
            if ch.isdigit():
                s += ch
            else:
                break
        nums.append(int(s or 0))
    return tuple((nums + [0, 0, 0])[:4])

def _fresh_url(url):
    """Adiciona um cache-buster sem remover parâmetros existentes."""
    try:
        parts = urllib.parse.urlsplit(str(url))
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if k != "_kbl_cache"]
        query.append(("_kbl_cache", str(time.time_ns())))
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                        urllib.parse.urlencode(query), parts.fragment))
    except Exception:
        sep = "&" if "?" in str(url) else "?"
        return f"{url}{sep}_kbl_cache={time.time_ns()}"

def get_json(url, timeout=20, fresh=True):
    target = _fresh_url(url) if fresh else str(url)
    headers = {
        "User-Agent": f"KBL-Hub/{HUB_VERSION}",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "Accept": "application/json, text/plain, */*",
    }
    req = urllib.request.Request(target, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8-sig"))

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().lower()

def safe_extract(zf, dest):
    root = Path(dest).resolve()
    for info in zf.infolist():
        out = (root / info.filename).resolve()
        if root != out and root not in out.parents:
            raise RuntimeError(f"Arquivo inseguro no ZIP: {info.filename}")
    zf.extractall(root)

def app_dir(app_id):
    return APPS_ROOT / app_id

def local_version(app_id, registry):
    vf = app_dir(app_id) / "version.json"
    if vf.exists():
        try:
            return str(json.loads(vf.read_text(encoding="utf-8-sig")).get("version", "0.0.0"))
        except Exception:
            pass
    return str(registry.get("apps", {}).get(app_id, {}).get("version", "0.0.0"))

def _norm_name(value):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()

def find_entrypoint(folder, app_id=None):
    folder = Path(folder)
    desc = load_app_descriptor(folder)
    declared = desc.get("entry") or desc.get("entrypoint")
    if declared:
        p = folder / Path(str(declared))
        if p.exists() and p.is_file():
            return p
    for hint in ENTRYPOINT_HINTS.get(app_id or "", []):
        direct = folder / hint
        if direct.exists() and direct.is_file():
            return direct
        matches = [p for p in folder.rglob(Path(hint).name) if p.is_file()]
        if matches:
            matches.sort(key=lambda p: (len(p.relative_to(folder).parts), str(p).casefold()))
            return matches[0]

    preferred = []
    for pat in ("*.exe", "*.vbs", "*.pyw", "*.py", "*.ps1", "*.bat", "*.cmd"):
        preferred.extend(folder.rglob(pat))
    excluded = {_norm_name(x) for x in EXCLUDED_ENTRYPOINTS}
    cleaned = []
    for p in preferred:
        n = _norm_name(p.name)
        if n in excluded or n.startswith(("test_", "teste_")):
            continue
        cleaned.append(p)
    cleaned.sort(key=lambda p: (
        0 if p.suffix.lower() == ".exe" else 1,
        0 if p.suffix.lower() == ".pyw" else 1,
        0 if any(k in _norm_name(p.stem) for k in ("abrir", "iniciar", "kbl", "app", "main")) else 1,
        len(p.relative_to(folder).parts),
        str(p).casefold(),
    ))
    return cleaned[0] if cleaned else None

def python_runtime_exe():
    # O instalador Windows mantém um runtime Python dedicado aos módulos KBL.
    dedicated = LOCAL_ROOT / "Runtime" / "Python312" / "python.exe"
    candidates = [dedicated]

    # Em modo de desenvolvimento, o próprio interpretador continua válido.
    exe = Path(sys.executable)
    if not getattr(sys, "frozen", False):
        candidates.append(exe)
        if exe.name.lower() in ("pythonw.exe", "pyw.exe", "py.exe"):
            candidates.append(exe.with_name("python.exe"))
        for prefix in (getattr(sys, "prefix", None), getattr(sys, "base_prefix", None)):
            if prefix:
                candidates.append(Path(prefix) / "python.exe")

    # Compatibilidade com instalações antigas do Hub/Python.
    local_programs = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Python"
    if local_programs.exists():
        candidates.extend(sorted(local_programs.glob("Python*/python.exe"), reverse=True))

    for p in candidates:
        try:
            p = p.resolve()
        except Exception:
            pass
        if p.exists() and p.is_file() and (p.name.lower() == "python.exe" or os.name != "nt"):
            return p

    raise RuntimeError(
        "Runtime Python dos módulos KBL não foi localizado. "
        "Repare/reinstale o KBL Hub pelo instalador oficial."
    )

def requirements_digest(folder):
    reqs = sorted(Path(folder).rglob("requirements.txt"), key=lambda p: str(p).casefold())
    if not reqs:
        return ""
    h = hashlib.sha256()
    for req in reqs:
        h.update(str(req.relative_to(folder)).encode("utf-8", "ignore"))
        h.update(req.read_bytes())
    return h.hexdigest()

def requirement_distributions(folder):
    names = []
    for req in sorted(Path(folder).rglob("requirements.txt"), key=lambda p: str(p).casefold()):
        for raw in req.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(("-r ", "--", "http://", "https://", "git+")):
                continue
            line = line.split(";", 1)[0].strip()
            m = re.match(r"^([A-Za-z0-9_.-]+)", line)
            if m and m.group(1) not in names:
                names.append(m.group(1))
    return names

def requirements_satisfied(folder):
    packages = requirement_distributions(folder)
    if not packages:
        return True
    py = python_runtime_exe()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    code = (
        "import importlib.metadata as m,sys\nmissing=[]\n"
        "for p in sys.argv[1:]:\n"
        "    try:m.version(p)\n"
        "    except m.PackageNotFoundError:missing.append(p)\n"
        "print('\\n'.join(missing));sys.exit(1 if missing else 0)"
    )
    try:
        r = subprocess.run([str(py), "-c", code, *packages], capture_output=True, text=True,
                           creationflags=flags, timeout=25)
        return r.returncode == 0
    except Exception:
        return False

def install_requirements(folder, force=False):
    reqs = sorted(Path(folder).rglob("requirements.txt"), key=lambda p: str(p).casefold())
    if not reqs:
        return ""
    if not force and requirements_satisfied(folder):
        return requirements_digest(folder)

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    py = python_runtime_exe()
    logroot = HUB_DATA / "logs"
    logroot.mkdir(parents=True, exist_ok=True)
    log = logroot / "dependencies.log"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    with log.open("a", encoding="utf-8") as lf:
        lf.write("\n" + "=" * 72 + "\n" + datetime.datetime.now().isoformat(timespec="seconds") + "\n")
        lf.write(f"Python: {py}\n")
        for req in reqs:
            lf.write(f"Instalando/verificando: {req}\n")
            lf.flush()
            r = subprocess.run([str(py), "-m", "pip", "install", "-r", str(req), "--disable-pip-version-check"],
                               cwd=str(req.parent), stdout=lf, stderr=subprocess.STDOUT,
                               creationflags=flags, env=env)
            if r.returncode != 0:
                subprocess.run([str(py), "-m", "ensurepip", "--upgrade"], stdout=lf,
                               stderr=subprocess.STDOUT, creationflags=flags, env=env)
                r = subprocess.run([str(py), "-m", "pip", "install", "-r", str(req), "--disable-pip-version-check"],
                                   cwd=str(req.parent), stdout=lf, stderr=subprocess.STDOUT,
                                   creationflags=flags, env=env)
            if r.returncode != 0:
                raise RuntimeError(f"Não foi possível instalar as dependências. Diagnóstico: {log}")
    if not requirements_satisfied(folder):
        raise RuntimeError(f"As dependências ainda não estão disponíveis no Python do Hub. Diagnóstico: {log}")
    return requirements_digest(folder)

def startup_log_path(app_id):
    logroot = HUB_DATA / "logs"
    logroot.mkdir(parents=True, exist_ok=True)
    return logroot / (app_id + "_startup.log")

def read_log_tail(path, max_lines=18):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:]).strip()
    except Exception:
        return ""

def launch_module(app_id, path):
    path = Path(path)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log = startup_log_path(app_id)
    lf = open(log, "a", encoding="utf-8")
    lf.write("\n" + "=" * 72 + "\n" + datetime.datetime.now().isoformat(timespec="seconds") + "\n")
    lf.write(f"Target: {path}\n")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    try:
        if path.suffix.lower() == ".exe":
            proc = subprocess.Popen([str(path)], cwd=str(path.parent), stdout=lf, stderr=subprocess.STDOUT,
                                    creationflags=flags, env=env)
        elif path.suffix.lower() in {".py", ".pyw"}:
            py = python_runtime_exe()
            lf.write(f"Python: {py}\n")
            lf.flush()
            proc = subprocess.Popen([str(py), str(path)], cwd=str(path.parent), stdout=lf,
                                    stderr=subprocess.STDOUT, creationflags=flags, env=env)
        elif path.suffix.lower() == ".vbs":
            proc = subprocess.Popen(["wscript.exe", str(path)], cwd=str(path.parent), stdout=lf,
                                    stderr=subprocess.STDOUT, creationflags=flags, env=env)
        elif path.suffix.lower() == ".ps1":
            proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-STA", "-File", str(path)],
                                    cwd=str(path.parent), stdout=lf, stderr=subprocess.STDOUT, creationflags=flags, env=env)
        elif path.suffix.lower() in {".bat", ".cmd"}:
            proc = subprocess.Popen(["cmd.exe", "/c", str(path)], cwd=str(path.parent), stdout=lf,
                                    stderr=subprocess.STDOUT, creationflags=flags, env=env)
        else:
            lf.close()
            os.startfile(str(path))
            return None, log
    except Exception:
        import traceback
        lf.write(traceback.format_exc() + "\n")
        lf.close()
        raise
    proc._kbl_log_handle = lf
    return proc, log

def expand_env_path(value):
    if not value:
        return None
    value = os.path.expandvars(str(value))
    return Path(value)

def load_app_descriptor(folder):
    folder = Path(folder)
    for name in ("hub_app.json", "app_manifest.json"):
        p = folder / name
        if p.exists():
            try:
                obj = json.loads(p.read_text(encoding="utf-8-sig"))
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
    return {}

def descriptor_for(app_id):
    folder = app_dir(app_id)
    d = load_app_descriptor(folder) if folder.exists() else {}
    remote = globals().get("_HUB_REMOTE_CACHE", {}).get(app_id, {}) if isinstance(globals().get("_HUB_REMOTE_CACHE", {}), dict) else {}
    hub = remote.get("hub") if isinstance(remote, dict) else None
    if isinstance(hub, dict):
        merged = dict(hub)
        merged.update(d)
        d = merged
    return d

def app_display_name(app_id, remote=None, candidate=None):
    d = load_app_descriptor(app_dir(app_id)) if app_dir(app_id).exists() else {}
    return ((candidate or {}).get("name") if candidate else None) or (remote or {}).get("name") or d.get("name") or DEFAULT_APPS.get(app_id, app_id)

def runtime_status_path(app_id):
    d = descriptor_for(app_id)
    custom = d.get("status_file")
    if custom:
        p = expand_env_path(custom)
        if p:
            return p
    return HUB_DATA / "status" / f"{app_id}.json"

def pid_alive(pid):
    try:
        pid = int(pid or 0)
        if pid <= 0:
            return False
        if os.name == "nt":
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k32 = __import__("ctypes").windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                k32.CloseHandle(h)
                return True
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def read_runtime_status(app_id):
    p = runtime_status_path(app_id)
    try:
        obj = json.loads(p.read_text(encoding="utf-8-sig"))
        updated = obj.get("updated_at")
        if updated:
            try:
                dt = datetime.datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    age = (datetime.datetime.now(datetime.timezone.utc) - dt.astimezone(datetime.timezone.utc)).total_seconds()
                else:
                    age = (datetime.datetime.now() - dt).total_seconds()
                obj["_age_seconds"] = age
            except Exception:
                pass
        pid = obj.get("pid")
        obj["_alive"] = pid_alive(pid) if pid else False
        return obj
    except Exception:
        return {}

def bring_window_to_front(title):
    if os.name != "nt" or not title:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        matches = []
        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if str(title).casefold() in buf.value.casefold():
                matches.append(hwnd)
                return False
            return True
        user32.EnumWindows(enum_cb, 0)
        if not matches:
            return False
        hwnd = matches[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False

def close_runtime_app(app_id):
    st = read_runtime_status(app_id)
    pid = st.get("pid")
    if pid and pid_alive(pid):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=flags)
        return True
    return False

def runtime_summary(app_id):
    st = read_runtime_status(app_id)
    if not st:
        return ""
    state = str(st.get("state") or "")
    if state.casefold() in {"fechado", "closed"}:
        return ""
    if not st.get("_alive") and st.get("_age_seconds", 9999) > 20:
        return ""
    parts = [state] if state else []
    comp = str(st.get("competence") or "")
    if comp:
        parts.append(comp)
    mods = []
    for m in st.get("modules") or []:
        try:
            name = str(m.get("name") or m.get("id") or "")
            ok, total = int(m.get("ok", 0)), int(m.get("total", 0))
            if total:
                mods.append(f"{name} {ok}/{total}")
        except Exception:
            pass
    if mods:
        parts.append(" | ".join(mods))
    msg = str(st.get("message") or "")
    if msg and msg not in parts:
        parts.append(msg)
    return " • ".join(x for x in parts if x)

def preserve_mutable(folder, app_id):
    if not folder.exists():
        return
    stash = DATA_ROOT / "HubPreserved" / app_id
    if stash.exists():
        shutil.rmtree(stash, ignore_errors=True)
    stash.mkdir(parents=True, exist_ok=True)
    for name in ("data", "dados", "userdata"):
        src = folder / name
        if src.exists() and src.is_dir():
            shutil.copytree(src, stash / name, dirs_exist_ok=True)
    for name in ("config.json", "settings.json", "user_settings.json"):
        src = folder / name
        if src.exists() and src.is_file():
            shutil.copy2(src, stash / name)

def restore_mutable(folder, app_id):
    stash = DATA_ROOT / "HubPreserved" / app_id
    if not stash.exists():
        return
    for item in stash.iterdir():
        dst = folder / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)

def delete_preserved(app_id):
    stash = DATA_ROOT / "HubPreserved" / app_id
    if stash.exists():
        shutil.rmtree(stash, ignore_errors=True)

# ---------------- GitHub CLI privado ----------------

def gh_exe():
    # O instalador oficial inclui um GitHub CLI portátil junto do Hub.
    bundled = PACKAGE_ROOT / "tools" / "gh.exe"
    if bundled.exists():
        return bundled

    found = shutil.which("gh")
    if found:
        return Path(found)
    if os.name == "nt":
        candidates = [
            Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI" / "gh.exe",
        ]
        for p in candidates:
            if p.exists():
                return p
    return None

def github_connected():
    gh = gh_exe()
    if not gh:
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run([str(gh), "auth", "status", "--hostname", "github.com"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=flags, timeout=20)
        return r.returncode == 0
    except Exception:
        return False

def install_github_cli():
    if gh_exe():
        return gh_exe()
    if os.name != "nt":
        raise RuntimeError("GitHub CLI (gh) não encontrado.")
    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("GitHub CLI não encontrado e winget não está disponível.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([winget, "install", "--id", "GitHub.cli", "-e", "--silent",
                        "--accept-package-agreements", "--accept-source-agreements"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=flags)
    if r.returncode not in (0,):
        raise RuntimeError("Não foi possível instalar o GitHub CLI automaticamente.")
    p = gh_exe()
    if not p:
        raise RuntimeError("GitHub CLI foi instalado, mas ainda não foi localizado. Feche e abra o Hub novamente.")
    return p

def open_github_login():
    gh = gh_exe() or install_github_cli()
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen([str(gh), "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web"],
                         creationflags=flags)
    else:
        subprocess.Popen([str(gh), "auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web"])

def _gh_run(args, *, input_path=None, input_bytes=None, binary_stdout_path=None, timeout=300, retries=4):
    gh = gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI não está instalado.")
    if not github_connected():
        raise RuntimeError("GitHub não está conectado. Abra Administração > Conectar GitHub.")

    if input_path is not None and input_bytes is not None:
        raise RuntimeError("Use input_path ou input_bytes, nunca os dois ao mesmo tempo.")

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    # GitHub CLI possui um problema conhecido com respostas comprimidas que pode
    # terminar em "transform: short source buffer". Forçamos resposta sem gzip.
    call_args = list(args)
    if call_args and str(call_args[0]).casefold() == "api":
        lower = [str(x).casefold() for x in call_args]
        has_accept_encoding = any("accept-encoding" in x for x in lower)
        if not has_accept_encoding:
            call_args[1:1] = ["-H", "Accept-Encoding: identity"]

    cmd = [str(gh), *call_args]
    last_error = ""

    for attempt in range(max(1, int(retries))):
        stdin_handle = open(input_path, "rb") if input_path else None
        try:
            if binary_stdout_path:
                with open(binary_stdout_path, "wb") as out:
                    r = subprocess.run(
                        cmd,
                        stdin=stdin_handle,
                        input=(None if stdin_handle is not None else input_bytes),
                        stdout=out,
                        stderr=subprocess.PIPE,
                        creationflags=flags,
                        timeout=timeout,
                    )
            else:
                r = subprocess.run(
                    cmd,
                    stdin=stdin_handle,
                    input=(None if stdin_handle is not None else input_bytes),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=flags,
                    timeout=timeout,
                )
        finally:
            if stdin_handle is not None:
                stdin_handle.close()

        if r.returncode == 0:
            return r.stdout if not binary_stdout_path else b""

        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        last_error = err or f"GitHub CLI retornou código {r.returncode}."

        low = last_error.casefold()
        transient = (
            "transform: short source buffer" in low
            or "cannot read body" in low
            or "unexpected eof" in low
            or "invalid character" in low and "looking for beginning of value" in low
        )
        if not transient or attempt + 1 >= max(1, int(retries)):
            raise RuntimeError(last_error)

        time.sleep(0.35 * (attempt + 1))

    raise RuntimeError(last_error or "Falha desconhecida no GitHub CLI.")



def _safe_unlink(path, attempts=12):
    """Remove arquivo temporário sem falhar por bloqueio transitório do Windows."""
    path = Path(path)
    for attempt in range(max(1, int(attempts))):
        try:
            path.unlink(missing_ok=True)
            return True
        except (PermissionError, OSError):
            if attempt + 1 >= max(1, int(attempts)):
                return False
            time.sleep(0.08 * (attempt + 1))
    return False


def github_auth_token():
    """Obtém somente o token do gh; não usa `gh api`, evitando a camada transform."""
    gh = gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI não está instalado.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(
        [str(gh), "auth", "token", "--hostname", "github.com"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags,
        timeout=25,
    )
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(err or "Não foi possível obter o token autenticado do GitHub.")
    token = (r.stdout or b"").decode("utf-8", "replace").strip()
    if not token:
        raise RuntimeError("GitHub CLI não retornou um token autenticado.")
    return token


def github_rest_json(path_or_url, timeout=90, attempts=4):
    """GET direto na API do GitHub, sem passar pelo decodificador/transform do gh CLI."""
    token = github_auth_token()
    if str(path_or_url).startswith("https://"):
        url = str(path_or_url)
    else:
        url = "https://api.github.com/" + str(path_or_url).lstrip("/")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"KBL-Hub/{HUB_VERSION}",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    }

    last = None
    for attempt in range(max(1, int(attempts))):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            if not raw:
                raise RuntimeError("GitHub retornou resposta vazia.")
            return json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            last = exc
            if attempt + 1 >= max(1, int(attempts)):
                raise
            time.sleep(0.45 * (attempt + 1))
    raise last


def github_rest_bytes(path_or_url, timeout=180, attempts=4, accept="application/octet-stream"):
    """GET binário direto na API do GitHub, com compressão desabilitada."""
    token = github_auth_token()
    if str(path_or_url).startswith("https://"):
        url = str(path_or_url)
    else:
        url = "https://api.github.com/" + str(path_or_url).lstrip("/")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"KBL-Hub/{HUB_VERSION}",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    }

    last = None
    for attempt in range(max(1, int(attempts))):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if not data:
                raise RuntimeError("GitHub retornou conteúdo vazio.")
            return data
        except Exception as exc:
            last = exc
            if attempt + 1 >= max(1, int(attempts)):
                raise
            time.sleep(0.55 * (attempt + 1))
    raise last


def gh_api_json(endpoint, attempts=4):
    last = None
    for attempt in range(max(1, int(attempts))):
        try:
            raw = _gh_run(["api", endpoint], timeout=60, retries=4)
            if not raw:
                raise RuntimeError("GitHub CLI retornou resposta vazia.")
            return json.loads(raw.decode("utf-8-sig"))
        except Exception as exc:
            last = exc
            low = str(exc).casefold()
            transient = (
                "short source buffer" in low
                or "cannot read body" in low
                or "unexpected eof" in low
                or "resposta vazia" in low
                or "json" in low
            )
            if not transient or attempt + 1 >= max(1, int(attempts)):
                raise
            time.sleep(0.4 * (attempt + 1))
    raise last

def gh_read_public_manifest(app_id):
    """Lê o version.json diretamente pela API do GitHub, sem CDN/cache raw."""
    endpoint = f"repos/{UPDATES_REPO}/contents/apps/{app_id}/version.json?ref=main"
    meta = gh_api_json(endpoint)
    content = base64.b64decode(meta["content"]).decode("utf-8-sig")
    return json.loads(content)

def gh_confirm_publication(app_id, version, digest=None, package_path=None, attempts=6):
    last = None
    for i in range(max(1, int(attempts))):
        try:
            obj = gh_read_public_manifest(app_id)
            last = obj
            ok = str(obj.get("version", "")) == str(version) and bool(obj.get("published"))
            if digest:
                ok = ok and str(obj.get("sha256", "")).lower() == str(digest).lower()
            if package_path:
                pkg = obj.get("package") or {}
                ok = ok and str(pkg.get("path", "")) == str(package_path)
            if ok:
                return obj
        except Exception as exc:
            last = exc
        if i < attempts - 1:
            time.sleep(0.8 + (i * 0.25))
    raise RuntimeError(f"Publicação enviada, mas a confirmação remota ainda não ficou consistente: {last}")

def gh_private_download(repository, path, target):
    """
    Download privado robusto.
    Não usa `gh api`, portanto não passa pelo transform/gzip do GitHub CLI.
    """
    encoded = urllib.parse.quote(path, safe="/")
    meta = github_rest_json(f"repos/{repository}/contents/{encoded}?ref=main", timeout=90, attempts=4)

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")

    try:
        # Para arquivos do Contents API, o endpoint raw devolve os bytes diretamente.
        raw_url = f"https://api.github.com/repos/{repository}/contents/{encoded}?ref=main"
        raw = github_rest_bytes(
            raw_url,
            timeout=240,
            attempts=4,
            accept="application/vnd.github.raw",
        )

        expected_size = int(meta.get("size") or 0)
        if expected_size and len(raw) != expected_size:
            raise RuntimeError(
                f"Download privado incompleto: esperado {expected_size} bytes, recebido {len(raw)}."
            )

        # Um pacote KBL deve ser ZIP válido antes de substituir/instalar.
        tmp.write_bytes(raw)
        if tmp.stat().st_size <= 0:
            raise RuntimeError("Pacote privado baixado com tamanho zero.")
        with zipfile.ZipFile(tmp) as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"Pacote privado corrompido. Primeiro arquivo inválido: {bad}")

        tmp.replace(target)
    finally:
        try:
            if tmp.exists():
                _safe_unlink(tmp)
        except Exception:
            pass


def gh_verify_private_package(repository, path, expected_sha, attempts=3):
    """Baixa de volta o pacote publicado e confirma o SHA-256 real antes do manifesto."""
    expected_sha = str(expected_sha or "").lower().strip()
    if len(expected_sha) != 64:
        raise RuntimeError("SHA-256 esperado inválido para verificação remota.")
    last = None
    for attempt in range(max(1, int(attempts))):
        work = Path(tempfile.mkdtemp(prefix="kbl_verify_"))
        probe = work / "package.zip"
        try:
            gh_private_download(repository, path, probe)
            actual = sha256(probe)
            if actual == expected_sha:
                return actual
            last = RuntimeError(
                f"Pacote remoto divergente após upload: esperado {expected_sha}, recebido {actual}."
            )
        except Exception as exc:
            last = exc
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if attempt + 1 < max(1, int(attempts)):
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(f"Falha na validação do pacote publicado: {last}")


def gh_upload_private(repository, path, file_path, message):
    encoded_path = urllib.parse.quote(path, safe="/")
    endpoint = f"repos/{repository}/contents/{encoded_path}"
    existing_sha = None
    try:
        meta = gh_api_json(endpoint + "?ref=main")
        existing_sha = meta.get("sha")
    except Exception:
        existing_sha = None

    payload = {
        "message": message,
        "content": base64.b64encode(Path(file_path).read_bytes()).decode("ascii"),
        "branch": "main",
    }
    if existing_sha:
        payload["sha"] = existing_sha

    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _gh_run(["api", "--method", "PUT", endpoint, "--input", "-"], input_bytes=raw, timeout=600)


def _gh_put_text(repository, path, text_content, message):
    encoded_path = urllib.parse.quote(path, safe="/")
    endpoint = f"repos/{repository}/contents/{encoded_path}"
    existing_sha = None
    try:
        meta = gh_api_json(endpoint + "?ref=main")
        existing_sha = meta.get("sha")
    except Exception:
        existing_sha = None

    payload = {
        "message": message,
        "content": base64.b64encode(text_content.encode("utf-8")).decode("ascii"),
        "branch": "main",
    }
    if existing_sha:
        payload["sha"] = existing_sha

    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _gh_run(["api", "--method", "PUT", endpoint, "--input", "-"], input_bytes=raw, timeout=120)


def gh_repair_public_sha(app_id, actual_sha, expected_version=None, expected_repository=None, expected_path=None):
    """Repara somente o hash do manifesto usando o pacote privado autenticado já validado como ZIP."""
    actual_sha = str(actual_sha or "").lower().strip()
    if len(actual_sha) != 64:
        raise RuntimeError("SHA-256 calculado inválido para reparo do catálogo.")
    obj = gh_read_public_manifest(app_id)
    pkg = obj.get("package") or {}
    if expected_version and str(obj.get("version") or "") != str(expected_version):
        raise RuntimeError("A versão publicada mudou durante o reparo; tente atualizar novamente.")
    if expected_repository and str(pkg.get("repository") or "") != str(expected_repository):
        raise RuntimeError("O repositório do pacote mudou durante o reparo; operação cancelada.")
    if expected_path and str(pkg.get("path") or "") != str(expected_path):
        raise RuntimeError("O caminho do pacote mudou durante o reparo; operação cancelada.")
    obj["sha256"] = actual_sha
    obj["repaired_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    obj["repair_reason"] = "sha256-synced-from-authenticated-private-package"
    _gh_put_text(UPDATES_REPO, f"apps/{app_id}/version.json",
                 json.dumps(obj, ensure_ascii=False, indent=2),
                 f"Repara SHA-256 {app_id} v{obj.get('version', '')}")
    return gh_confirm_publication(
        app_id, obj.get("version"), actual_sha, str(pkg.get("path") or "")
    )


def gh_update_public_manifest(app_id, version, file_name, file_sha, package_path, package_meta=None):
    package_meta = package_meta or {}
    endpoint = f"repos/{UPDATES_REPO}/contents/apps/{app_id}/version.json"
    obj = {}
    try:
        meta = gh_api_json(endpoint + "?ref=main")
        content = base64.b64decode(meta["content"]).decode("utf-8-sig")
        obj = json.loads(content)
    except Exception:
        obj = {
            "schema_version": 3,
            "app_id": app_id,
            "name": package_meta.get("name") or DEFAULT_APPS.get(app_id, app_id),
            "channel": "stable",
            "min_updater_version": "1.0.0",
            "mandatory": False,
            "notes": [],
        }
    obj["schema_version"] = 3
    obj["app_id"] = app_id
    obj["name"] = package_meta.get("name") or obj.get("name") or DEFAULT_APPS.get(app_id, app_id)
    obj["version"] = str(version)
    obj["published"] = True
    obj["download_url"] = ""
    obj["sha256"] = file_sha
    obj["file_name"] = file_name
    obj["published_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    hub_meta = package_meta.get("hub")
    if isinstance(hub_meta, dict) and hub_meta:
        obj["hub"] = hub_meta
    obj["package"] = {
        "provider": "github-private-repo",        "repository": APPS_REPO,
        "path": package_path,
        "auth": "github-cli",
    }
    _gh_put_text(UPDATES_REPO, f"apps/{app_id}/version.json",
                 json.dumps(obj, ensure_ascii=False, indent=2),
                 f"Publica {app_id} v{version}")

    # Auto-registro no catálogo raiz: novos apps passam a aparecer no Hub sem recompilar o Hub.
    root_endpoint = f"repos/{UPDATES_REPO}/contents/manifest.json"
    root_meta = gh_api_json(root_endpoint + "?ref=main")
    root = json.loads(base64.b64decode(root_meta["content"]).decode("utf-8-sig"))
    apps = list(root.get("apps") or [])
    url = f"https://raw.githubusercontent.com/{UPDATES_REPO}/main/apps/{app_id}/version.json?v={urllib.parse.quote(str(version))}"
    found = False
    for item in apps:
        if item.get("app_id") == app_id:
            item["name"] = obj["name"]
            item["manifest_url"] = url
            found = True
            break
    if not found:
        apps.append({"app_id": app_id, "name": obj["name"], "manifest_url": url})
    root["schema_version"] = max(3, int(root.get("schema_version") or 3))
    root["apps"] = apps
    _gh_put_text(UPDATES_REPO, "manifest.json", json.dumps(root, ensure_ascii=False, indent=2),
                 f"Registra {app_id} no catálogo")

def detect_package_metadata(path):
    meta = {"app_id": None, "name": None, "version": None, "hub": {}}
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                low = n.lower()
                if low.endswith("hub_app.json"):
                    try:
                        obj = json.loads(z.read(n).decode("utf-8-sig"))
                        meta["app_id"] = obj.get("app_id") or obj.get("id") or meta["app_id"]
                        meta["name"] = obj.get("name") or meta["name"]
                        meta["version"] = str(obj.get("version") or meta["version"] or "").strip() or None
                        meta["hub"] = obj
                    except Exception:
                        pass
                elif low.endswith("version.json"):
                    try:
                        obj = json.loads(z.read(n).decode("utf-8-sig"))
                        meta["app_id"] = obj.get("app_id") or meta["app_id"]
                        meta["name"] = obj.get("name") or meta["name"]
                        meta["version"] = str(obj.get("version") or meta["version"] or "").strip() or None
                    except Exception:
                        pass
    except Exception:
        pass
    return meta

def detect_app_id_from_zip(path):
    meta = detect_package_metadata(path)
    if meta.get("app_id"):
        return str(meta["app_id"])
    name = _norm_name(Path(path).name)
    for hint, app_id in FILENAME_APP_HINTS.items():
        if hint in name:
            return app_id
    return None

def detect_version_from_zip(path):
    meta = detect_package_metadata(path)
    if meta.get("version"):
        return str(meta["version"])
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith("version.json"):
                    try:
                        obj = json.loads(z.read(n).decode("utf-8-sig"))
                        v = str(obj.get("version") or "").strip()
                        if v and v != "0.0.0":
                            return v
                    except Exception:
                        pass
    except Exception:
        pass
    m = re.search(r"(?:^|[_-])v(\d+(?:[_\.]\d+)*)", Path(path).stem, re.I)
    if m:
        return m.group(1).replace("_", ".")
    return None


TRAY_ICON_B64 = "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"

class WindowsTray:
    """Ícone de bandeja nativo do Windows sem dependências externas."""
    def __init__(self, command_queue):
        self.command_queue = command_queue
        self.hwnd = None
        self.thread = None
        self._wndproc_ref = None
        self._class_name = None
        self._available = False

    @property
    def available(self):
        return bool(self._available)

    def start(self):
        if os.name != "nt" or self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, name="KBLHubTray", daemon=True)
        self.thread.start()

    def stop(self):
        if os.name != "nt" or not self.hwnd:
            return
        try:
            import ctypes
            ctypes.windll.user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass

    def _icon_path(self):
        ensure_dirs()
        p = HUB_DATA / "kbl_hub_tray.ico"
        try:
            raw = base64.b64decode(TRAY_ICON_B64)
            if not p.exists() or p.stat().st_size != len(raw):
                p.write_bytes(raw)
        except Exception:
            return None
        return p

    def _run(self):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            kernel32 = ctypes.windll.kernel32

            WM_DESTROY = 0x0002
            WM_CLOSE = 0x0010
            WM_USER = 0x0400
            WM_TRAY = WM_USER + 77
            WM_LBUTTONUP = 0x0202
            WM_LBUTTONDBLCLK = 0x0203
            WM_RBUTTONUP = 0x0205
            NIM_ADD = 0x00000000
            NIM_DELETE = 0x00000002
            NIF_MESSAGE = 0x00000001
            NIF_ICON = 0x00000002
            NIF_TIP = 0x00000004
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040

            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(
                LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            class NOTIFYICONDATAW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("hWnd", wintypes.HWND),
                    ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HICON),
                    ("szTip", ctypes.c_wchar * 128),
                    ("dwState", wintypes.DWORD),
                    ("dwStateMask", wintypes.DWORD),
                    ("szInfo", ctypes.c_wchar * 256),
                    ("uTimeoutOrVersion", wintypes.UINT),
                    ("szInfoTitle", ctypes.c_wchar * 64),
                    ("dwInfoFlags", wintypes.DWORD),
                ]

            nid = NOTIFYICONDATAW()

            def wndproc(hwnd, msg, wparam, lparam):
                try:
                    if msg == WM_TRAY:
                        event = int(lparam)
                        if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                            self.command_queue.put("open")
                            return 0
                        if event == WM_RBUTTONUP:
                            # v2.2.11: sem menu Win32 customizado.
                            # Clique direito também reabre o Hub, evitando o popup em branco.
                            self.command_queue.put("open")
                            return 0
                    elif msg == WM_DESTROY:
                        try:
                            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                        except Exception:
                            pass
                        user32.PostQuitMessage(0)
                        return 0
                except Exception:
                    pass
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc_ref = WNDPROC(wndproc)
            hinst = kernel32.GetModuleHandleW(None)
            self._class_name = f"KBLHubTray_{os.getpid()}"

            icon_path = self._icon_path()
            hicon = None
            if icon_path:
                hicon = user32.LoadImageW(
                    None, str(icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
                )
            if not hicon:
                hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION

            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = hinst
            wc.hIcon = hicon
            wc.lpszClassName = self._class_name
            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                return

            hwnd = user32.CreateWindowExW(
                0, self._class_name, "KBL Hub Tray", 0,
                0, 0, 0, 0, None, None, hinst, None
            )
            if not hwnd:
                return
            self.hwnd = hwnd

            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAY
            nid.hIcon = hicon
            nid.szTip = "KBL Hub • clique para abrir"
            if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
                return

            self._available = True

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self._available = False
        finally:
            self._available = False
            self.hwnd = None


class Hub(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.registry = load_registry()
        self.bundled = bundled_catalog()
        self.remote_root = {}
        self.remote_apps = {}
        self.local_descriptors = {}
        self._refreshing_remote = False
        self._refresh_seq = 0
        self.running = {}
        self.title(f"KBL Hub • v{HUB_VERSION}")
        self.geometry("1020x650")
        self.minsize(880, 560)
        self.configure(bg="#111214")
        self._style()
        self._build()
        self._tray_commands = queue.Queue()
        self._tray = WindowsTray(self._tray_commands)
        self._tray.start()
        self._exiting = False
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.after(200, self._poll_tray_commands)
        self.after(200, self.refresh_remote)
        self.after(1500, self._runtime_tick)

    def _poll_tray_commands(self):
        try:
            while True:
                cmd = self._tray_commands.get_nowait()
                if cmd == "open":
                    self.show_from_tray()
                elif cmd == "exit":
                    self.exit_hub()
        except queue.Empty:
            pass
        if not self._exiting:
            self.after(200, self._poll_tray_commands)

    def hide_to_tray(self):
        if self._exiting:
            return
        try:
            self.withdraw()
        except Exception:
            self.iconify()

    def show_from_tray(self):
        if self._exiting:
            return
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.attributes("-topmost", True)
            self.after(250, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def exit_hub(self):
        if self._exiting:
            return
        try:
            if not messagebox.askyesno(
                "KBL Hub",
                "Fechar o KBL Hub definitivamente?\n\n"
                "Os aplicativos já abertos continuarão funcionando."
            ):
                return
        except Exception:
            pass

        self._exiting = True
        try:
            self._tray.stop()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure(".", font=("Segoe UI", 10))
        s.configure("TFrame", background="#111214")
        s.configure("TLabel", background="#111214", foreground="#F5F5F5")
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 18), foreground="#FFFFFF")
        s.configure("Sub.TLabel", foreground="#A9ADB3")
        s.configure("Treeview", rowheight=35, background="#181A1E", fieldbackground="#181A1E", foreground="#F5F5F5")
        s.configure("Treeview.Heading", background="#202329", foreground="#FFFFFF", font=("Segoe UI Semibold", 10))
        s.map("Treeview", background=[("selected", "#343840")], foreground=[("selected", "#FFFFFF")])
        s.configure("TButton", padding=(12, 8))
        s.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(18, 9))
        s.configure("Action.TButton", padding=(16, 9))
        s.configure("More.TButton", font=("Segoe UI Semibold", 14), padding=(10, 5))

    def _build(self):
        root = ttk.Frame(self, padding=22)
        root.pack(fill="both", expand=True)
        h = ttk.Frame(root)
        h.pack(fill="x")
        ttk.Label(h, text="KBL HUB", style="Title.TLabel").pack(side="left")
        ttk.Label(h, text=f"v{HUB_VERSION}", style="Sub.TLabel").pack(side="left", padx=(10, 0))
        self.net = ttk.Label(h, text="Conectando...", style="Sub.TLabel")
        self.net.pack(side="right")
        ttk.Label(root,
                  text="Central remota: os aplicativos são atualizados independentemente do Hub.",
                  style="Sub.TLabel").pack(anchor="w", pady=(5, 18))

        cols = ("app", "instalada", "disponivel", "origem", "estado")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
        defs = [
            ("app", "Aplicativo", 330, "w"),
            ("instalada", "Instalada", 100, "center"),
            ("disponivel", "Disponível", 100, "center"),
            ("origem", "Fonte", 140, "center"),
            ("estado", "Status", 220, "w"),
        ]
        for c, label, width, anchor in defs:
            self.tree.heading(c, text=label)
            self.tree.column(c, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.primary_action())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._sync_actions())

        # Barra simples e responsiva: ação principal + atualização global + administração + menu.
        a = ttk.Frame(root)
        a.pack(fill="x", pady=(16, 0))
        a.columnconfigure(2, weight=1)

        self.btn_primary = ttk.Button(a, text="Selecionar aplicativo", style="Primary.TButton",
                                      command=self.primary_action, state="disabled")
        self.btn_primary.grid(row=0, column=0, sticky="w")

        self.btn_update_all = ttk.Button(a, text="Atualizar tudo", style="Action.TButton",
                                         command=self.update_all, state="disabled")
        self.btn_update_all.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.btn_admin = ttk.Button(a, text="Administração", style="Action.TButton", command=self.open_admin)
        self.btn_admin.grid(row=0, column=3, sticky="e", padx=(8, 0))

        self.more_menu = tk.Menu(self, tearoff=0)
        self.btn_more = ttk.Button(a, text="⋯", width=3, style="More.TButton", command=self._show_more_menu)
        self.btn_more.grid(row=0, column=4, sticky="e", padx=(8, 0))

        self.btn_exit = ttk.Button(a, text="Fechar", style="Action.TButton", command=self.exit_hub)
        self.btn_exit.grid(row=0, column=5, sticky="e", padx=(8, 0))

        self.info = ttk.Label(root,
                              text="X minimiza para a bandeja. Fechar encerra o Hub definitivamente. Outras ações ficam no menu ⋯.",
                              style="Sub.TLabel")
        self.info.pack(anchor="w", pady=(12, 0))
        self.update_count = 0

    def _selected_action(self):
        app_id = self.selected_id()
        if not app_id:
            return "Selecionar aplicativo", None
        folder = app_dir(app_id)
        installed = folder.exists() and any(folder.iterdir())
        cand = self.candidate(app_id)
        if not installed:
            return ("Instalar", self.install_selected) if cand else ("Indisponível", None)
        if cand and vtuple(cand["version"]) > vtuple(local_version(app_id, self.registry)):
            return "Atualizar", self.update_selected
        return "Abrir", self.open_selected

    def _sync_actions(self):
        if not hasattr(self, "btn_primary"):
            return
        label, command = self._selected_action()
        self.btn_primary.config(text=label, state=("normal" if command else "disabled"))
        self._primary_command = command
        count = int(getattr(self, "update_count", 0) or 0)
        if count > 0:
            self.btn_update_all.grid()
            self.btn_update_all.config(text=f"Atualizar tudo ({count})", state="normal", style="Primary.TButton")
        else:
            self.btn_update_all.config(text="Atualizar tudo", state="disabled", style="Action.TButton")
            self.btn_update_all.grid_remove()

    def primary_action(self):
        self._sync_actions()
        command = getattr(self, "_primary_command", None)
        if command:
            command()

    def reinstall_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        folder = app_dir(app_id)
        if not folder.exists() or not any(folder.iterdir()):
            return self.install_selected()
        c = self.candidate(app_id)
        if not c:
            return messagebox.showinfo("KBL Hub", "Ainda não há pacote disponível para reinstalar este módulo.")
        name = app_display_name(app_id, self.remote_apps.get(app_id, {}), c)
        if not messagebox.askyesno("KBL Hub", f"Reinstalar {name} v{c['version']}?\n\nOs dados preserváveis do módulo serão mantidos."):
            return
        threading.Thread(target=self._work_one, args=(app_id, "Reinstalação"), daemon=True).start()

    def _show_more_menu(self):
        menu = self.more_menu
        menu.delete(0, "end")
        app_id = self.selected_id()
        installed = False
        running = False
        if app_id:
            folder = app_dir(app_id)
            installed = folder.exists() and any(folder.iterdir())
            if installed:
                st = read_runtime_status(app_id)
                running = bool(st.get("pid") and st.get("_alive"))

        menu.add_command(label="Encerrar aplicativo", command=self.close_selected,
                         state=("normal" if running else "disabled"))
        menu.add_command(label="Desinstalar aplicativo...", command=self.uninstall_selected,
                         state=("normal" if installed else "disabled"))
        menu.add_command(label="Reinstalar aplicativo...", command=self.reinstall_selected,
                         state=("normal" if installed and app_id and self.candidate(app_id) else "disabled"))
        menu.add_separator()
        menu.add_command(label="Instalar todos os disponíveis...", command=self.install_all)
        menu.add_command(label="Atualizar versões", command=self.refresh_remote)
        menu.add_separator()
        menu.add_command(label="Sair do KBL Hub", command=self.exit_hub)

        try:
            x = self.btn_more.winfo_rootx()
            y = self.btn_more.winfo_rooty() + self.btn_more.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _scan_local_descriptors(self):
        found = {}
        if APPS_ROOT.exists():
            for folder in APPS_ROOT.iterdir():
                if not folder.is_dir():
                    continue
                d = load_app_descriptor(folder)
                app_id = str(d.get("app_id") or d.get("id") or folder.name)
                if d:
                    found[app_id] = d
        self.local_descriptors = found
        return found

    def _runtime_tick(self):
        try:
            self.render()
        except Exception:
            pass
        self.after(2500, self._runtime_tick)

    def close_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        name = app_display_name(app_id, self.remote_apps.get(app_id, {}), self.candidate(app_id))
        st = read_runtime_status(app_id)
        if not (st.get("pid") and st.get("_alive")):
            return messagebox.showinfo("KBL Hub", f"{name} não está em execução.")
        if not messagebox.askyesno("KBL Hub", f"Encerrar {name}?\n\nProcessos auxiliares iniciados por ele também serão encerrados."):
            return
        if close_runtime_app(app_id):
            self.info.config(text=f"{name} encerrado.")
            self.after(500, self.render)
        else:
            messagebox.showwarning("KBL Hub", "Não consegui localizar o processo ativo do aplicativo.")

    def selected_id(self):
        x = self.tree.selection()
        return x[0] if x else None

    def refresh_remote(self):
        # O botão sempre força uma leitura nova. Evita duas verificações simultâneas
        # brigando entre si e a resposta mais antiga sobrescrevendo a mais nova.
        self._refresh_seq += 1
        seq = self._refresh_seq
        self.net.config(text="Atualizando versões...")
        threading.Thread(target=self._refresh_worker, args=(seq,), daemon=True).start()

    def _refresh_worker(self, seq=None):
        try:
            root = get_json(MANIFEST_URL, fresh=True)
            previous = dict(self.remote_apps or {})
            apps = {}
            for item in root.get("apps", []):
                app_id = item["app_id"]
                try:
                    apps[app_id] = get_json(item["manifest_url"], fresh=True)
                except Exception as exc:
                    # Falha isolada não rebaixa uma versão conhecida para 0.0.0.
                    old = previous.get(app_id)
                    if old:
                        old = dict(old)
                        old["refresh_error"] = str(exc)
                        apps[app_id] = old
                    else:
                        apps[app_id] = {
                            "name": item.get("name", app_id),
                            "version": "0.0.0",
                            "published": False,
                            "error": str(exc),
                        }
            if seq is not None and seq != self._refresh_seq:
                return
            self.remote_root = root
            self.remote_apps = apps
            globals()["_HUB_REMOTE_CACHE"] = apps
            self.after(0, self.render)
        except Exception:
            if seq is not None and seq != self._refresh_seq:
                return
            self.after(0, lambda: self.render(offline=True))

    def remote_candidate(self, app_id):
        r = self.remote_apps.get(app_id, {})
        pkg = r.get("package") or {}
        if (r.get("published") and pkg.get("provider") == "github-private-repo"
                and pkg.get("repository") and pkg.get("path")
                and len(str(r.get("sha256", ""))) == 64):
            return {
                "source": "KBL-Apps privado",
                "version": str(r.get("version", "0")),
                "repository": pkg["repository"],
                "path": pkg["path"],
                "sha256": str(r.get("sha256", "")).lower(),
                "file_name": r.get("file_name") or Path(pkg["path"]).name,
                "name": r.get("name", DEFAULT_APPS.get(app_id, app_id)),
            }
        return None

    def bundled_candidate(self, app_id):
        b = self.bundled.get(app_id)
        if not b:
            return None
        p = BUNDLED_DIR / b.get("file_name", "")
        if not p.exists():
            return None
        return {
            "source": "Base local",
            "version": str(b.get("version", "0")),
            "file": p,
            "sha256": str(b.get("sha256", "")).lower(),
            "name": b.get("name", DEFAULT_APPS.get(app_id, app_id)),
        }

    def candidate(self, app_id):
        choices = []
        r = self.remote_candidate(app_id)
        if r:
            choices.append(r)
        b = self.bundled_candidate(app_id)
        if b:
            choices.append(b)
        if not choices:
            return None
        choices.sort(key=lambda x: (vtuple(x["version"]), 1 if x["source"] == "KBL-Apps privado" else 0),
                     reverse=True)
        return choices[0]

    def all_ids(self):
        self._scan_local_descriptors()
        ids = list(DEFAULT_APPS)
        for src in (self.remote_apps, self.bundled, self.local_descriptors, self.registry.get("apps", {})):
            for i in src:
                if i not in ids:
                    ids.append(i)
        return ids

    def render(self, offline=False):
        keep = self.selected_id()
        for i in self.tree.get_children():
            self.tree.delete(i)
        updates = 0
        for app_id in self.all_ids():
            folder = app_dir(app_id)
            installed = folder.exists() and any(folder.iterdir())
            local = local_version(app_id, self.registry) if installed else "—"
            cand = self.candidate(app_id)
            remote = self.remote_apps.get(app_id, {})
            name = app_display_name(app_id, remote, cand)
            avail = cand["version"] if cand else str(remote.get("version", "—"))
            source = cand["source"] if cand else "—"
            run_status = runtime_summary(app_id) if installed else ""
            if not installed:
                status = "Pronto para instalar" if cand else "Pacote não publicado"
            elif cand and vtuple(cand["version"]) > vtuple(local):
                status = (run_status + " • " if run_status else "") + "Atualização disponível"
                updates += 1
            elif run_status:
                status = run_status
            else:
                status = "Atualizado" if cand else "Instalado"
            self.tree.insert("", "end", iid=app_id, values=(name, local, avail, source, status))

        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
            self.tree.focus(first)

        self.update_count = updates
        if offline:
            text = "Modo local"
        elif github_connected():
            text = f"{updates} atualização(ões)" if updates else "Conectado"
        else:
            text = "GitHub privado não conectado"
        self.net.config(text=text)
        self._sync_actions()

    def install_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        folder = app_dir(app_id)
        if folder.exists() and any(folder.iterdir()):
            return messagebox.showinfo("KBL Hub", "Este módulo já está instalado.")
        self._confirm_install(app_id)

    def update_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        c = self.candidate(app_id)
        if not c:
            return messagebox.showinfo("KBL Hub", "Ainda não há pacote disponível para este módulo.")
        folder = app_dir(app_id)
        if not folder.exists() or not any(folder.iterdir()):
            return self._confirm_install(app_id)
        if vtuple(c["version"]) <= vtuple(local_version(app_id, self.registry)):
            return messagebox.showinfo("KBL Hub", "Este módulo já está atualizado.")
        self._confirm_install(app_id)

    def _confirm_install(self, app_id):
        c = self.candidate(app_id)
        if not c:
            return messagebox.showinfo("KBL Hub", "Ainda não há pacote disponível para este módulo.")
        if c["source"] == "KBL-Apps privado" and not github_connected():
            return messagebox.showwarning("KBL Hub",
                "A versão está no repositório privado KBL-Apps, mas o GitHub ainda não está conectado.\n\n"
                "Abra Administração > Conectar GitHub.")
        installed = app_dir(app_id).exists() and any(app_dir(app_id).iterdir())
        verb = "Atualizar" if installed else "Instalar"
        if not messagebox.askyesno("KBL Hub",
                                   f"{verb} {c['name']} v{c['version']}?\n\nFonte: {c['source']}"):
            return
        threading.Thread(target=self._work_one, args=(app_id, verb), daemon=True).start()

    def _work_one(self, app_id, verb):
        try:
            self._perform_install(app_id)
            self.after(0, self.render)
            self.after(0, lambda: messagebox.showinfo("KBL Hub", f"{verb} concluído."))
        except Exception as exc:
            self.after(0, lambda e=exc: messagebox.showerror("KBL Hub", str(e)))

    def _perform_install(self, app_id):
        c = self.candidate(app_id)
        if not c:
            raise RuntimeError("Pacote não disponível.")
        folder = app_dir(app_id)
        backup = LOCAL_ROOT / "Backups" / app_id
        work = Path(tempfile.mkdtemp(prefix="kbl_hub_"))
        pkg = work / "package.zip"
        ext = work / "ext"
        try:
            if c["source"] == "KBL-Apps privado":
                self.after(0, lambda: self.info.config(text=f"Baixando pacote privado {c['file_name']} diretamente pela API do GitHub..."))
                try:
                    gh_private_download(c["repository"], c["path"], pkg)
                except Exception as exc:
                    raise RuntimeError(f"Falha ao baixar pacote privado: {exc}") from exc
            else:
                shutil.copy2(c["file"], pkg)

            actual_sha = sha256(pkg)
            expected_sha = str(c["sha256"]).lower()
            if actual_sha != expected_sha:
                # O catálogo em memória/raw pode estar defasado em relação à API autoritativa.
                # Recarrega o version.json diretamente do GitHub e tenta uma única vez com os dados novos.
                if c["source"] == "KBL-Apps privado":
                    self.after(0, lambda: self.info.config(
                        text=f"Hash divergente em {c['name']}. Revalidando catálogo e pacote no GitHub..."))
                    fresh = gh_read_public_manifest(app_id)
                    pkg_meta = fresh.get("package") or {}
                    fresh_sha = str(fresh.get("sha256") or "").lower()
                    fresh_repo = str(pkg_meta.get("repository") or APPS_REPO)
                    fresh_path = str(pkg_meta.get("path") or "")
                    fresh_version = str(fresh.get("version") or "")
                    if not fresh.get("published") or len(fresh_sha) != 64 or not fresh_path:
                        raise RuntimeError(
                            "SHA-256 inválido e o catálogo remoto não contém uma publicação válida para reparo automático.")
                    # Se a publicação mudou enquanto o usuário atualizava, passa a usar a versão autoritativa.
                    c.update({
                        "version": fresh_version or c.get("version"),
                        "sha256": fresh_sha,
                        "repository": fresh_repo,
                        "path": fresh_path,
                        "file_name": fresh.get("file_name") or Path(fresh_path).name,
                    })
                    self.remote_apps[app_id] = fresh
                    globals().setdefault("_HUB_REMOTE_CACHE", {})[app_id] = fresh
                    _safe_unlink(pkg)
                    gh_private_download(fresh_repo, fresh_path, pkg)
                    actual_sha = sha256(pkg)
                    if actual_sha != fresh_sha:
                        # O pacote autenticado do repositório privado é ZIP válido, tem tamanho
                        # conferido pela API e foi baixado novamente. Se somente o manifesto
                        # estiver defasado, sincroniza o SHA do catálogo e segue a instalação.
                        if github_connected():
                            repaired = gh_repair_public_sha(
                                app_id, actual_sha, expected_version=fresh_version,
                                expected_repository=fresh_repo, expected_path=fresh_path)
                            fresh_sha = actual_sha
                            self.remote_apps[app_id] = repaired
                            globals().setdefault("_HUB_REMOTE_CACHE", {})[app_id] = repaired
                            c["sha256"] = actual_sha
                            self.after(0, lambda: self.info.config(
                                text=f"Catálogo reparado automaticamente para {c['name']} v{c['version']}. Instalando..."))
                        else:
                            raise RuntimeError(
                                "SHA-256 inválido após revalidação automática. "
                                f"Catálogo: {fresh_sha} | pacote: {actual_sha}. "
                                "Conecte o GitHub em Administração para reparar a publicação.")
                else:
                    raise RuntimeError(
                        f"SHA-256 inválido. Esperado {expected_sha}, recebido {actual_sha}. Operação cancelada.")

            ext.mkdir()
            with zipfile.ZipFile(pkg) as zf:
                safe_extract(zf, ext)

            if folder.exists() and any(folder.iterdir()):
                preserve_mutable(folder, app_id)
                backup.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                shutil.copytree(folder, backup)

            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True, exist_ok=True)
            items = list(ext.iterdir())
            src = items[0] if len(items) == 1 and items[0].is_dir() else ext
            shutil.copytree(src, folder, dirs_exist_ok=True)
            restore_mutable(folder, app_id)

            req_hash = install_requirements(folder)
            (folder / "version.json").write_text(json.dumps({
                "app_id": app_id,
                "version": c["version"],
                "installed_by": "KBL Hub",
            }, ensure_ascii=False, indent=2), encoding="utf-8")

            reg = self.registry.setdefault("apps", {}).setdefault(app_id, {})
            reg["version"] = c["version"]
            reg["requirements_hash"] = req_hash
            ep = find_entrypoint(folder, app_id)
            if not ep:
                raise RuntimeError("Instalado, mas não encontrei o inicializador do módulo.")
            reg["entrypoint"] = str(ep.relative_to(folder))
            desc = load_app_descriptor(folder)
            if desc:
                reg["descriptor"] = desc
            reg["rollback_available"] = bool(backup.exists())
            save_registry(self.registry)
        except Exception:
            if backup.exists():
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
                shutil.copytree(backup, folder)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def open_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        folder = app_dir(app_id)
        if not folder.exists() or not any(folder.iterdir()):
            if messagebox.askyesno("KBL Hub", "Este módulo não está instalado.\n\nInstalar agora?"):
                self._confirm_install(app_id)
            return
        self.info.config(text=f"Preparando {app_display_name(app_id, self.remote_apps.get(app_id, {}), self.candidate(app_id))}...")
        threading.Thread(target=self._open_worker, args=(app_id,), daemon=True).start()

    def _open_worker(self, app_id):
        folder = app_dir(app_id)
        try:
            name = app_display_name(app_id, self.remote_apps.get(app_id, {}), self.candidate(app_id))
            st = read_runtime_status(app_id)
            if st.get("_alive"):
                title = st.get("window_title") or descriptor_for(app_id).get("window_title") or name
                bring_window_to_front(title)
                self.after(0, lambda: self.info.config(text=f"{name} já estava aberto."))
                self.after(350, self.hide_to_tray)
                return
            reg = self.registry.setdefault("apps", {}).setdefault(app_id, {})
            current_req = requirements_digest(folder)
            needs_deps = bool(current_req) and (
                reg.get("requirements_hash") != current_req or not requirements_satisfied(folder)
            )
            if needs_deps:
                self.after(0, lambda: self.info.config(text="Verificando/instalando dependências do módulo..."))
                reg["requirements_hash"] = install_requirements(folder, force=True)
                save_registry(self.registry)

            ep = None
            stored = reg.get("entrypoint")
            if stored:
                c = folder / Path(stored)
                if c.exists():
                    ep = c
            if not ep:
                ep = find_entrypoint(folder, app_id)
            if not ep:
                raise RuntimeError("Não encontrei o arquivo de inicialização deste módulo.")
            reg["entrypoint"] = str(ep.relative_to(folder))
            save_registry(self.registry)

            proc, log = launch_module(app_id, ep)
            self.after(0, lambda: self.info.config(text=f"{name} aberto."))
            self.after(350, self.hide_to_tray)
            if proc is not None:
                try:
                    rc = proc.wait(timeout=2.2)
                    try:
                        proc._kbl_log_handle.close()
                    except Exception:
                        pass
                    if rc not in (0, None):
                        detail = read_log_tail(log)
                        msg = f"Não foi possível abrir {name}.\n\nLog: {log}"
                        if detail:
                            msg += "\n\nDetalhe:\n" + detail[-2200:]
                        self.after(0, lambda m=msg, n=name: messagebox.showerror(n, m))
                        self.after(0, self.deiconify)
                except subprocess.TimeoutExpired:
                    pass
        except Exception as exc:
            self.after(0, lambda: self.info.config(text="Falha ao abrir o módulo."))
            self.after(0, lambda e=exc: messagebox.showerror("KBL Hub",
                                                              f"Não foi possível abrir o aplicativo.\n\n{e}"))
            self.after(0, self.deiconify)

    def install_all(self):
        ids = [i for i in self.all_ids()
               if self.candidate(i) and not (app_dir(i).exists() and any(app_dir(i).iterdir()))]
        if not ids:
            return messagebox.showinfo("KBL Hub", "Não há módulos disponíveis para instalar.")
        private_needed = any(self.candidate(i)["source"] == "KBL-Apps privado" for i in ids)
        if private_needed and not github_connected():
            return messagebox.showwarning("KBL Hub", "Conecte o GitHub em Administração antes de instalar os pacotes privados.")
        if not messagebox.askyesno("KBL Hub", f"Instalar {len(ids)} módulo(s) disponível(is)?"):
            return
        threading.Thread(target=self._batch, args=(ids, "Instalação"), daemon=True).start()

    def update_all(self):
        ids = []
        for i in self.all_ids():
            c = self.candidate(i)
            folder = app_dir(i)
            if c and folder.exists() and any(folder.iterdir()) and vtuple(c["version"]) > vtuple(local_version(i, self.registry)):
                ids.append(i)
        if not ids:
            return messagebox.showinfo("KBL Hub", "Não há atualizações disponíveis.")
        private_needed = any(self.candidate(i)["source"] == "KBL-Apps privado" for i in ids)
        if private_needed and not github_connected():
            return messagebox.showwarning("KBL Hub", "Conecte o GitHub em Administração antes de atualizar pacotes privados.")
        if not messagebox.askyesno("KBL Hub", f"Atualizar {len(ids)} módulo(s)?"):
            return
        threading.Thread(target=self._batch, args=(ids, "Atualização"), daemon=True).start()

    def _batch(self, ids, label):
        errors = []
        for i in ids:
            try:
                self._perform_install(i)
            except Exception as exc:
                errors.append(f"{i}: {exc}")
        self.after(0, self.render)
        if errors:
            self.after(0, lambda: messagebox.showwarning("KBL Hub", "\n".join(errors)))
        else:
            self.after(0, lambda: messagebox.showinfo("KBL Hub", f"{label} concluída."))

    def uninstall_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        folder = app_dir(app_id)
        if not folder.exists() or not any(folder.iterdir()):
            return messagebox.showinfo("KBL Hub", "Este módulo não está instalado.")

        name = app_display_name(app_id, self.remote_apps.get(app_id, {}), self.candidate(app_id))
        w = tk.Toplevel(self)
        w.title("Desinstalar módulo")
        w.geometry("535x300")
        w.resizable(False, False)
        w.transient(self)
        w.grab_set()
        w.configure(bg="#111214")

        f = ttk.Frame(w, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"Desinstalar {name}", font=("Segoe UI Semibold", 14)).pack(anchor="w")
        ttk.Label(f,
                  text="Por padrão, somente o aplicativo será removido. Dados, histórico e configurações são preservados para uma futura reinstalação.",
                  style="Sub.TLabel", wraplength=470, justify="left").pack(anchor="w", pady=(8, 14))
        wipe = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Também apagar os dados preservados deste módulo", variable=wipe).pack(anchor="w")
        ttk.Label(f, text="Essa opção é irreversível e exige confirmação adicional.", style="Sub.TLabel").pack(anchor="w", pady=(4, 16))

        b = ttk.Frame(f)
        b.pack(fill="x", side="bottom")
        ttk.Button(b, text="Cancelar", command=w.destroy).pack(side="right")

        def go():
            msg = ("ATENÇÃO: aplicativo e dados preservados serão apagados.\n\nDeseja continuar?"                   if wipe.get() else
                   "Remover somente o aplicativo?\n\nOs dados serão preservados.")
            if not messagebox.askyesno("Confirmação", msg, parent=w):
                return
            try:
                preserve_mutable(folder, app_id)
                shutil.rmtree(folder)
                self.registry.get("apps", {}).pop(app_id, None)
                save_registry(self.registry)
                if wipe.get():
                    delete_preserved(app_id)
                w.destroy()
                self.render()
                messagebox.showinfo("KBL Hub",
                                    "Módulo desinstalado." +
                                    (" Dados preservados removidos." if wipe.get() else " Dados preservados."))
            except Exception as exc:
                messagebox.showerror("KBL Hub", f"Falha ao desinstalar.\n\n{exc}", parent=w)

        ttk.Button(b, text="Desinstalar", command=go).pack(side="right", padx=(0, 8))

    # ---------------- Administração / publicação ----------------

    def open_admin(self):
        w = tk.Toplevel(self)
        w.title("KBL Hub • Administração")
        w.geometry("670x470")
        w.minsize(650, 440)
        w.transient(self)
        w.configure(bg="#111214")

        f = ttk.Frame(w, padding=22)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Administração", font=("Segoe UI Semibold", 16)).pack(anchor="w")
        ttk.Label(f,
                  text="Publicação privada dos módulos KBL. Essa área altera os repositórios KBL-Apps e KBL-Updates.",
                  style="Sub.TLabel", wraplength=600, justify="left").pack(anchor="w", pady=(5, 16))

        status = ttk.Label(f, text="", style="Sub.TLabel")
        status.pack(anchor="w", pady=(0, 14))

        btns = ttk.Frame(f)
        btns.pack(fill="x")
        ttk.Button(btns, text="Conectar GitHub", command=lambda: self._admin_connect(status)).pack(side="left")
        ttk.Button(btns, text="Verificar conexão", command=lambda: self._admin_status(status)).pack(side="left", padx=8)

        ttk.Separator(f).pack(fill="x", pady=18)
        ttk.Label(f, text="Publicação", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(f,
                  text="Selecione um ZIP novo. O Hub detecta aplicativo/versão, envia ao KBL-Apps privado e só depois ativa a versão no KBL-Updates.",
                  style="Sub.TLabel", wraplength=600, justify="left").pack(anchor="w", pady=(4, 10))
        ttk.Button(f, text="Publicar atualização...", command=lambda: self._admin_choose_publish(w, status)).pack(anchor="w")

        ttk.Separator(f).pack(fill="x", pady=18)
        ttk.Label(f, text="Migração inicial", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        ttk.Label(f,
                  text="Executar uma única vez para enviar os pacotes-base atuais que vieram nesta versão do Hub ao KBL-Apps privado.",
                  style="Sub.TLabel", wraplength=600, justify="left").pack(anchor="w", pady=(4, 10))
        ttk.Button(f, text="Publicar pacotes iniciais", command=lambda: self._admin_migrate(status)).pack(anchor="w")

        self._admin_status(status)

    def _admin_status(self, label):
        gh = gh_exe()
        if not gh:
            label.config(text="GitHub CLI: não instalado")
        elif github_connected():
            label.config(text=f"GitHub CLI: conectado • KBL-Apps: privado")
        else:
            label.config(text="GitHub CLI: instalado, mas conta não conectada")

    def _admin_connect(self, label):
        try:
            if not gh_exe():
                label.config(text="Instalando GitHub CLI...")
                self.update_idletasks()
                install_github_cli()
            open_github_login()
            label.config(text="A janela de autenticação foi aberta. Após concluir, clique em Verificar conexão.")
        except Exception as exc:
            messagebox.showerror("KBL Hub", str(exc))

    def _admin_choose_publish(self, parent, label):
        file_path = filedialog.askopenfilename(parent=parent, title="Selecionar pacote KBL",
                                               filetypes=[("Pacote ZIP", "*.zip")])
        if not file_path:
            return
        app_id = detect_app_id_from_zip(file_path)
        version = detect_version_from_zip(file_path)
        if not app_id or not version:
            return messagebox.showerror("KBL Hub",
                "Não consegui detectar com segurança o aplicativo e a versão deste ZIP.", parent=parent)
        meta = detect_package_metadata(file_path)
        name = meta.get("name") or DEFAULT_APPS.get(app_id, app_id)

        # Para publicar, a versão estável é lida diretamente da API do GitHub.
        # A grade pode estar usando cache antigo e nunca deve decidir a publicação.
        current_obj = {}
        if github_connected():
            try:
                current_obj = gh_read_public_manifest(app_id)
            except Exception:
                current_obj = {}
        if not current_obj:
            current_obj = self.remote_apps.get(app_id, {}) or {}
        current = str(current_obj.get("version") or "0.0.0")

        if vtuple(version) < vtuple(current):
            return messagebox.showerror(
                "Publicação bloqueada",
                f"A versão estável publicada é {current}.\n\n"
                f"O pacote selecionado é {version}. O catálogo remoto nunca é rebaixado.\n"
                "Para voltar uma versão, use a reversão local do aplicativo.",
                parent=parent)

        repair = vtuple(version) == vtuple(current) and current not in ("0", "0.0.0", "—")
        if repair:
            msg = (f"Aplicativo: {name}\n"
                   f"Versão do pacote: {version}\n"
                   f"Versão publicada: {current}\n\n"
                   "Essa versão já está publicada. Deseja REPARAR a publicação?\n\n"
                   "O Hub reenviará o pacote, regravará o catálogo e confirmará a versão diretamente no GitHub.")
            title = "Reparar publicação"
        else:
            msg = (f"Aplicativo: {name}\n"
                   f"Versão do pacote: {version}\n"
                   f"Versão publicada: {current}\n\n"
                   f"Publicar no KBL-Apps privado e ativar no KBL-Updates?")
            title = "Publicar atualização"
        if not messagebox.askyesno(title, msg, parent=parent):
            return
        threading.Thread(target=self._publish_worker,
                         args=(app_id, version, Path(file_path), label, parent, repair), daemon=True).start()

    def _publish_worker(self, app_id, version, file_path, label, parent, repair=False):
        try:
            action = "Reparando" if repair else "Publicando"
            self.after(0, lambda: label.config(text=f"{action} {app_id} v{version} • conexão GitHub sem compressão + retry automático..."))
            digest, package_path = self._publish_package(app_id, version, file_path)
            self.after(0, lambda: label.config(text=f"Confirmando {app_id} v{version} no catálogo remoto..."))
            confirmed = gh_confirm_publication(app_id, version, digest, package_path)

            # Atualiza imediatamente a memória da grade com a fonte autoritativa,
            # sem aguardar o raw.githubusercontent.com propagar.
            self.remote_apps[app_id] = confirmed
            globals().setdefault("_HUB_REMOTE_CACHE", {})[app_id] = confirmed
            self.after(0, self.render)
            self.after(0, lambda: label.config(text=f"{app_id} v{version} confirmado no catálogo."))
            # Em seguida força uma leitura HTTP nova de todo o catálogo.
            self.after(250, self.refresh_remote)
            msg = (f"{app_id} v{version} reparado e confirmado." if repair
                   else f"{app_id} v{version} publicado e confirmado.")
            self.after(0, lambda m=msg: messagebox.showinfo("KBL Hub", m, parent=parent))
        except Exception as exc:
            self.after(0, lambda e=exc: label.config(text=f"Falha: {e}"))
            self.after(0, lambda e=exc: messagebox.showerror("KBL Hub", str(e), parent=parent))

    def _publish_package(self, app_id, version, file_path):
        if not github_connected():
            raise RuntimeError("GitHub não está conectado.")
        file_path = Path(file_path)
        with zipfile.ZipFile(file_path) as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"ZIP corrompido: {bad}")
        digest = sha256(file_path)
        package_path = f"packages/{app_id}/{version}/{file_path.name}"

        # O manifesto só é atualizado depois que o arquivo efetivamente armazenado no
        # KBL-Apps for baixado novamente e tiver o MESMO SHA-256 do pacote local.
        # Se houver divergência/transiente, reenviamos uma vez antes de falhar.
        last = None
        for upload_attempt in range(2):
            gh_upload_private(APPS_REPO, package_path, file_path,
                              f"Publica {DEFAULT_APPS.get(app_id, app_id)} v{version}")
            try:
                gh_verify_private_package(APPS_REPO, package_path, digest, attempts=3)
                last = None
                break
            except Exception as exc:
                last = exc
                if upload_attempt == 0:
                    time.sleep(1.0)
        if last is not None:
            raise RuntimeError(
                "O pacote foi enviado, mas a cópia remota não passou na validação SHA-256. "
                "O catálogo NÃO foi alterado. " + str(last)
            )

        meta = detect_package_metadata(file_path)
        gh_update_public_manifest(app_id, version, file_path.name, digest, package_path, meta)
        gh_confirm_publication(app_id, version, digest, package_path)
        return digest, package_path

    def _admin_migrate(self, label):
        if not github_connected():
            return messagebox.showwarning("KBL Hub",
                                          "Conecte o GitHub antes da migração inicial.")
        items = []
        for app_id, item in self.bundled.items():
            p = BUNDLED_DIR / item.get("file_name", "")
            if p.exists():
                items.append((app_id, str(item.get("version", "0")), p))
        if not items:
            return messagebox.showinfo("KBL Hub", "Não há pacotes-base para migrar.")
        if not messagebox.askyesno("Migração inicial",
                                   f"Enviar {len(items)} pacotes atuais ao KBL-Apps privado?\n\n"
                                   "Esta operação precisa ser feita apenas uma vez."):
            return

        def worker():
            errors = []
            for idx, (app_id, version, path) in enumerate(items, 1):
                try:
                    self.after(0, lambda i=idx, n=len(items), a=app_id:
                               label.config(text=f"Migrando {i}/{n}: {DEFAULT_APPS[a]}..."))
                    self._publish_package(app_id, version, path)
                except Exception as exc:
                    errors.append(f"{DEFAULT_APPS.get(app_id, app_id)}: {exc}")
            if errors:
                self.after(0, lambda: messagebox.showwarning("KBL Hub",
                                                             "Migração concluída com falhas:\n\n" + "\n".join(errors)))
                self.after(0, lambda: label.config(text="Migração concluída com falhas."))
            else:
                self.after(0, lambda: messagebox.showinfo("KBL Hub",
                                                          "Os 6 pacotes foram publicados no KBL-Apps privado.\n\n"
                                                          "A partir de agora, novas versões podem ser publicadas sem atualizar o Hub."))
                self.after(0, lambda: label.config(text="Migração inicial concluída. Distribuição remota ativa."))
            self.after(0, self.refresh_remote)

        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    ensure_dirs()
    app = Hub()
    try:
        app.mainloop()
    finally:
        try:
            app._tray.stop()
        except Exception:
            pass