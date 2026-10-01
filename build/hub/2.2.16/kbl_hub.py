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
        "provider": "github-private-repo",