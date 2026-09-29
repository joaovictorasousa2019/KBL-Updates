from __future__ import annotations
import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.request, urllib.parse, zipfile, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

HUB_VERSION = "2.2.0"
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

def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": f"KBL-Hub/{HUB_VERSION}"})
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

def _gh_run(args, *, input_path=None, binary_stdout_path=None, timeout=300):
    gh = gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI não está instalado.")
    if not github_connected():
        raise RuntimeError("GitHub não está conectado. Abra Administração > Conectar GitHub.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [str(gh), *args]
    stderr = subprocess.PIPE
    if binary_stdout_path:
        with open(binary_stdout_path, "wb") as out:
            r = subprocess.run(cmd, stdin=open(input_path, "rb") if input_path else None,
                               stdout=out, stderr=stderr, creationflags=flags, timeout=timeout)
    else:
        r = subprocess.run(cmd, stdin=open(input_path, "rb") if input_path else None,
                           stdout=subprocess.PIPE, stderr=stderr, creationflags=flags, timeout=timeout)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(err or f"GitHub CLI retornou código {r.returncode}.")
    return r.stdout if not binary_stdout_path else b""

def gh_api_json(endpoint):
    raw = _gh_run(["api", endpoint], timeout=60)
    return json.loads(raw.decode("utf-8"))

def gh_private_download(repository, path, target):
    encoded = urllib.parse.quote(path, safe="/")
    _gh_run(["api", f"repos/{repository}/contents/{encoded}",
             "-H", "Accept: application/vnd.github.raw+json"],
            binary_stdout_path=str(target), timeout=300)

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

    tmp = Path(tempfile.mkstemp(prefix="kbl_gh_upload_", suffix=".json")[1])
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        _gh_run(["api", "--method", "PUT", endpoint, "--input", str(tmp)], timeout=600)
    finally:
        tmp.unlink(missing_ok=True)

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
    tmp = Path(tempfile.mkstemp(prefix="kbl_gh_text_", suffix=".json")[1])
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        _gh_run(["api", "--method", "PUT", endpoint, "--input", str(tmp)], timeout=120)
    finally:
        tmp.unlink(missing_ok=True)

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
        "repository": APPS_REPO,
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
    url = f"https://raw.githubusercontent.com/{UPDATES_REPO}/main/apps/{app_id}/version.json"
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

class Hub(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.registry = load_registry()
        self.bundled = bundled_catalog()
        self.remote_root = {}
        self.remote_apps = {}
        self.local_descriptors = {}
        self.running = {}
        self.title(f"KBL Hub • v{HUB_VERSION}")
        self.geometry("1020x650")
        self.minsize(880, 560)
        self.configure(bg="#111214")
        self._style()
        self._build()
        self.after(200, self.refresh_remote)
        self.after(1500, self._runtime_tick)

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
        s.configure("TButton", padding=(11, 8))

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
        for c, t, w, a in defs:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())

        a = ttk.Frame(root)
        a.pack(fill="x", pady=(16, 0))
        ttk.Button(a, text="Instalar", command=self.install_selected).pack(side="left")
        ttk.Button(a, text="Abrir", command=self.open_selected).pack(side="left", padx=7)
        ttk.Button(a, text="Encerrar", command=self.close_selected).pack(side="left")
        ttk.Button(a, text="Atualizar", command=self.update_selected).pack(side="left", padx=7)
        ttk.Button(a, text="Desinstalar", command=self.uninstall_selected).pack(side="left", padx=7)
        ttk.Button(a, text="Administração", command=self.open_admin).pack(side="left", padx=(14, 0))

        ttk.Button(a, text="Atualizar todos", command=self.update_all).pack(side="right")
        ttk.Button(a, text="Instalar todos", command=self.install_all).pack(side="right", padx=7)
        ttk.Button(a, text="Verificar", command=self.refresh_remote).pack(side="right")

        self.info = ttk.Label(root,
                              text="Dados dos módulos são preservados. GitHub privado é usado apenas para os pacotes.",
                              style="Sub.TLabel")
        self.info.pack(anchor="w", pady=(12, 0))

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
        self.net.config(text="Verificando versões...")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            root = get_json(MANIFEST_URL)
            apps = {}
            for item in root.get("apps", []):
                try:
                    apps[item["app_id"]] = get_json(item["manifest_url"])
                except Exception as exc:
                    apps[item["app_id"]] = {
                        "name": item.get("name", item["app_id"]),
                        "version": "0.0.0",
                        "published": False,
                        "error": str(exc),
                    }
            self.remote_root = root
            self.remote_apps = apps
            globals()["_HUB_REMOTE_CACHE"] = apps
            self.after(0, self.render)
        except Exception:
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
                status = "Atualizado" if cand else "Instalado"            self.tree.insert("", "end", iid=app_id, values=(name, local, avail, source, status))

        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)

        if offline:
            text = "Modo local"
        elif github_connected():
            text = f"{updates} atualização(ões)" if updates else "Conectado"
        else:
            text = "GitHub privado não conectado"
        self.net.config(text=text)

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
                gh_private_download(c["repository"], c["path"], pkg)
            else:
                shutil.copy2(c["file"], pkg)

            if sha256(pkg) != str(c["sha256"]).lower():
                raise RuntimeError("SHA-256 inválido. Operação cancelada.")

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
                self.after(350, self.iconify)
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
            self.after(350, self.iconify)
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
            msg = ("ATENÇÃO: aplicativo e dados preservados serão apagados.\n\nDeseja continuar?"
                   if wipe.get() else
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
        current = self.remote_apps.get(app_id, {}).get("version", "—")
        msg = (f"Aplicativo: {name}\n"
               f"Versão do pacote: {version}\n"
               f"Versão publicada: {current}\n\n"
               f"Publicar no KBL-Apps privado e ativar no KBL-Updates?")
        if not messagebox.askyesno("Publicar atualização", msg, parent=parent):
            return
        threading.Thread(target=self._publish_worker,
                         args=(app_id, version, Path(file_path), label, parent), daemon=True).start()

    def _publish_worker(self, app_id, version, file_path, label, parent):
        try:
            self.after(0, lambda: label.config(text=f"Publicando {app_id} v{version}..."))
            self._publish_package(app_id, version, file_path)
            self.after(0, lambda: label.config(text=f"{app_id} v{version} publicado com sucesso."))
            self.after(0, self.refresh_remote)
            self.after(0, lambda: messagebox.showinfo("KBL Hub",
                                                       f"{app_id} v{version} publicado.",
                                                       parent=parent))
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
        gh_upload_private(APPS_REPO, package_path, file_path,
                          f"Publica {DEFAULT_APPS.get(app_id, app_id)} v{version}")
        meta = detect_package_metadata(file_path)
        gh_update_public_manifest(app_id, version, file_path.name, digest, package_path, meta)

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
    Hub().mainloop()