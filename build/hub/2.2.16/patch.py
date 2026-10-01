from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

if 'HUB_VERSION = "2.2.7"' not in t:
    raise RuntimeError("KBL Hub 2.2.7 base não encontrada")
t = t.replace('HUB_VERSION = "2.2.7"', 'HUB_VERSION = "2.2.16"', 1)

old = '''            if st.get("_alive"):
                title = st.get("window_title") or descriptor_for(app_id).get("window_title") or name
                if bring_window_to_front(title, st.get("pid")):
                    self.after(0, lambda: self.info.config(text=f"{name} já estava aberto."))
                    self.after(350, self.iconify)
                    return
                # O processo existe, mas não possui a janela esperada. Não bloqueia
                # a abertura; isso cobre app oculto, status antigo e PID reutilizado.
                self.after(0, lambda: self.info.config(text=f"Abrindo nova janela de {name}..."))
'''
new = '''            if st.get("_alive"):
                title = st.get("window_title") or descriptor_for(app_id).get("window_title") or name
                if bring_window_to_front(title, st.get("pid")):
                    self.after(0, lambda: self.info.config(text=f"{name} já estava aberto."))
                    self.after(350, self.iconify)
                    return

                # Processo do app existe, mas não há janela visível. Para o COLETOR
                # isso significa processo órfão/travado. Encerra somente o PID já
                # validado como pertencente ao próprio app e abre uma instância nova.
                if app_id == "kbl-coletor":
                    pid = st.get("pid")
                    if pid and runtime_pid_matches_app(app_id, pid, st):
                        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=flags, timeout=8)
                        time.sleep(0.35)
                    try:
                        runtime_status_path(app_id).unlink(missing_ok=True)
                    except Exception:
                        pass
                    self.after(0, lambda: self.info.config(text=f"Reiniciando {name}..."))
                else:
                    self.after(0, lambda: self.info.config(text=f"Abrindo nova janela de {name}..."))
'''
if old not in t:
    raise RuntimeError("Bloco _open_worker 2.2.7 não encontrado")
t = t.replace(old, new, 1)

old_summary = '''    state = str(st.get("state") or "")
    if state.casefold() in {"fechado", "closed"}:
        return ""
'''
new_summary = '''    state = str(st.get("state") or "")
    if state.casefold() in {"fechado", "closed"}:
        return ""
    if app_id == "kbl-coletor" and state.casefold() == "erro":
        title = st.get("window_title") or descriptor_for(app_id).get("window_title") or DEFAULT_APPS.get(app_id, app_id)
        if st.get("_alive") and _find_app_window(title, st.get("pid")):
            state = "Aberto • última operação com erro"
        elif st.get("_alive"):
            state = "Processo travado"
        else:
            return ""
'''
if old_summary not in t:
    raise RuntimeError("runtime_summary base não encontrado")
t = t.replace(old_summary, new_summary, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.16")
