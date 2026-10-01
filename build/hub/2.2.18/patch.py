from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

if 'HUB_VERSION = "2.2.17"' not in t:
    raise RuntimeError("KBL Hub 2.2.17 base não encontrada")
t = t.replace('HUB_VERSION = "2.2.17"', 'HUB_VERSION = "2.2.18"', 1)

old = '''        self._last_runtime_signature = {}
        self._build()
'''
new = '''        self._last_runtime_signature = {}
        self._runtime_scan_busy = False
        self._runtime_rows_cache = {}
        self._github_connected_cache = None
        self._build()
'''
if old not in t:
    raise RuntimeError("estado 2.2.17 não encontrado")
t = t.replace(old, new, 1)

start = t.find('    def _runtime_tick(self):')
end = t.find('    def _on_unmap', start)
if start < 0 or end < 0:
    raise RuntimeError("bloco de runtime 2.2.17 não encontrado")

new_runtime = r'''    def _runtime_tick(self):
        """Agenda leitura de processos/status fora da thread da interface."""
        if self._really_quitting:
            return
        if not self._runtime_scan_busy:
            self._runtime_scan_busy = True
            threading.Thread(target=self._runtime_scan_worker, daemon=True).start()
        self.after(6500, self._runtime_tick)

    def _runtime_scan_worker(self):
        try:
            rows = {}
            updates = 0
            # Toda leitura de disco/processo fica fora da thread do Tk.
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

                rows[app_id] = (name, local, avail, source, status)

            self._runtime_rows_cache = rows
            self.after(0, lambda r=rows, u=updates: self._apply_runtime_rows(r, u))
        finally:
            self._runtime_scan_busy = False

    def _apply_runtime_rows(self, rows, updates):
        if self._really_quitting:
            return
        try:
            for app_id, new_vals in rows.items():
                if not self.tree.exists(app_id):
                    continue
                sig = tuple(new_vals)
                if self._last_runtime_signature.get(app_id) != sig:
                    self.tree.item(app_id, values=new_vals)
                    self._last_runtime_signature[app_id] = sig

            if self._github_connected_cache is True:
                self.net.config(text=f"{updates} atualização(ões)" if updates else "Conectado")
            elif self._github_connected_cache is False:
                self.net.config(text="GitHub privado não conectado")
        except Exception:
            pass

'''
t = t[:start] + new_runtime + t[end:]

# render must not invoke gh synchronously on the UI thread
old = '''        if offline:
            text = "Modo local"
        elif github_connected():
            text = f"{updates} atualização(ões)" if updates else "Conectado"
        else:
            text = "GitHub privado não conectado"
        self.net.config(text=text)
'''
new = '''        if offline:
            text = "Modo local"
        elif self._github_connected_cache is True:
            text = f"{updates} atualização(ões)" if updates else "Conectado"
        elif self._github_connected_cache is False:
            text = "GitHub privado não conectado"
        else:
            text = "Verificando conexão..."
        self.net.config(text=text)
'''
if old not in t:
    raise RuntimeError("render connection block não encontrado")
t = t.replace(old, new, 1)

# Connection check happens in existing background refresh worker.
old = '''            self.remote_root = root
            self.remote_apps = apps
            globals()["_HUB_REMOTE_CACHE"] = apps
            self.after(0, self.render)
'''
new = '''            self.remote_root = root
            self.remote_apps = apps
            globals()["_HUB_REMOTE_CACHE"] = apps
            try:
                self._github_connected_cache = github_connected()
            except Exception:
                self._github_connected_cache = False
            self.after(0, self.render)
'''
if old not in t:
    raise RuntimeError("refresh worker block não encontrado")
t = t.replace(old, new, 1)

# Avoid a synchronous gh call when confirming an install.
old = '''        if c["source"] == "KBL-Apps privado" and not github_connected():
            return messagebox.showwarning("KBL Hub",
'''
new = '''        if c["source"] == "KBL-Apps privado" and self._github_connected_cache is False:
            return messagebox.showwarning("KBL Hub",
'''
if old not in t:
    raise RuntimeError("confirm install github check não encontrado")
t = t.replace(old, new, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.18")
