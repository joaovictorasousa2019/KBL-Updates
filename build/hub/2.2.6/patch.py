from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

if 'HUB_VERSION = "2.2.5"' not in t:
    raise RuntimeError("KBL Hub 2.2.5 base não encontrada")
t = t.replace('HUB_VERSION = "2.2.5"', 'HUB_VERSION = "2.2.6"', 1)

old_bring = '''def bring_window_to_front(title):
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
'''
new_bring = '''def _find_app_window(title, pid=None):
    if os.name != "nt" or not title:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        matches = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            if pid:
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if int(owner.value) != int(pid):
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
        return matches[0] if matches else None
    except Exception:
        return None

def bring_window_to_front(title, pid=None):
    hwnd = _find_app_window(title, pid)
    if not hwnd:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False

def _process_command_line(pid):
    if os.name != "nt" or not pid:
        return ""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-Command",
            f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId = {int(pid)}\" -ErrorAction SilentlyContinue; "
            "if($p){[Console]::Out.Write($p.CommandLine)}"
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags, timeout=4)
        return (r.stdout or "").strip()
    except Exception:
        return ""

def runtime_pid_matches_app(app_id, pid, status=None):
    """Confirma que o PID ainda pertence ao aplicativo correto.

    O Windows reutiliza PIDs. Um runtime_status.json antigo podia apontar para um
    PID que depois passava a pertencer a outro módulo KBL. O Hub então achava
    que o app antigo ainda estava aberto e recusava iniciar o aplicativo real.
    """
    if not pid or not pid_alive(pid):
        return False

    status = status or {}
    d = descriptor_for(app_id)
    title = status.get("window_title") or d.get("window_title") or DEFAULT_APPS.get(app_id, app_id)
    if title and _find_app_window(title, pid):
        return True

    cmdline = _process_command_line(pid)
    if not cmdline:
        return False
    norm = cmdline.casefold().replace("/", "\\\\")

    folder = str(app_dir(app_id)).casefold().replace("/", "\\\\")
    if folder and folder in norm:
        return True

    candidates = []
    declared = d.get("entry") or d.get("entrypoint")
    if declared:
        candidates.append(Path(str(declared)).name.casefold())
    for hint in ENTRYPOINT_HINTS.get(app_id, []):
        candidates.append(Path(hint).name.casefold())
    return any(name and name in norm for name in candidates)
'''
if old_bring not in t:
    raise RuntimeError("bring_window_to_front antigo não encontrado")
t = t.replace(old_bring, new_bring, 1)

old_status = '''        pid = obj.get("pid")
        obj["_alive"] = pid_alive(pid) if pid else False
        return obj
'''
new_status = '''        pid = obj.get("pid")
        obj["_pid_alive"] = pid_alive(pid) if pid else False
        obj["_alive"] = runtime_pid_matches_app(app_id, pid, obj) if pid else False
        obj["_stale_pid"] = bool(obj["_pid_alive"] and not obj["_alive"])
        return obj
'''
if old_status not in t:
    raise RuntimeError("read_runtime_status antigo não encontrado")
t = t.replace(old_status, new_status, 1)

old_open = '''            if st.get("_alive"):
                title = st.get("window_title") or descriptor_for(app_id).get("window_title") or name
                bring_window_to_front(title)
                self.after(0, lambda: self.info.config(text=f"{name} já estava aberto."))
                self.after(350, self.iconify)
                return
'''
new_open = '''            if st.get("_alive"):
                title = st.get("window_title") or descriptor_for(app_id).get("window_title") or name
                if bring_window_to_front(title, st.get("pid")):
                    self.after(0, lambda: self.info.config(text=f"{name} já estava aberto."))
                    self.after(350, self.iconify)
                    return
                # O processo existe, mas não possui a janela esperada. Não bloqueia
                # a abertura; isso cobre app oculto, status antigo e PID reutilizado.
                self.after(0, lambda: self.info.config(text=f"Abrindo nova janela de {name}..."))
'''
if old_open not in t:
    raise RuntimeError("_open_worker antigo não encontrado")
t = t.replace(old_open, new_open, 1)

old_close = '''def close_runtime_app(app_id):
    st = read_runtime_status(app_id)
    pid = st.get("pid")
    if pid and pid_alive(pid):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=flags)
        return True
    return False
'''
new_close = '''def close_runtime_app(app_id):
    st = read_runtime_status(app_id)
    pid = st.get("pid")
    # Nunca encerra um PID apenas porque ele existe: o Windows pode ter
    # reutilizado esse número para outro aplicativo KBL.
    if pid and st.get("_alive"):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=flags)
        return True
    return False
'''
if old_close not in t:
    raise RuntimeError("close_runtime_app antigo não encontrado")
t = t.replace(old_close, new_close, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.6")
