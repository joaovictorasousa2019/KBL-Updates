from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

if 'HUB_VERSION = "2.2.16"' not in t:
    raise RuntimeError("KBL Hub 2.2.16 base não encontrada")
t = t.replace('HUB_VERSION = "2.2.16"', 'HUB_VERSION = "2.2.17"', 1)

# imports for tray
old = 'import tkinter as tk\nfrom tkinter import ttk, messagebox, filedialog\n'
new = '''import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageDraw = None
'''
if old not in t:
    raise RuntimeError("imports base não encontrados")
t = t.replace(old, new, 1)

# init: tray state, protocol and minimize binding
old = '''        self._build()
        self.after(200, self.refresh_remote)
        self.after(1500, self._runtime_tick)
'''
new = '''        self._tray_icon = None
        self._tray_thread = None
        self._really_quitting = False
        self._last_runtime_signature = {}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        self.bind("<Unmap>", self._on_unmap, add="+")
        self.after(200, self.refresh_remote)
        self.after(1800, self._runtime_tick)
'''
if old not in t:
    raise RuntimeError("init base não encontrado")
t = t.replace(old, new, 1)

# restore definitive close button on the simplified 2.2.2 UI
old = '''        self.btn_more = ttk.Button(a, text="⋯", width=3, style="More.TButton", command=self._show_more_menu)
        self.btn_more.grid(row=0, column=4, sticky="e", padx=(8, 0))
'''
new = '''        self.btn_more = ttk.Button(a, text="⋯", width=3, style="More.TButton", command=self._show_more_menu)
        self.btn_more.grid(row=0, column=4, sticky="e", padx=(8, 0))

        self.btn_quit = ttk.Button(a, text="Fechar definitivo", style="Action.TButton",
                                   command=self.quit_definitively)
        self.btn_quit.grid(row=0, column=5, sticky="e", padx=(8, 0))
'''
if old not in t:
    raise RuntimeError("barra simplificada do Hub não encontrada")
t = t.replace(old, new, 1)

# Replace expensive runtime tick with lightweight row update and tray helpers.
old = '''    def _runtime_tick(self):
        try:
            self.render()
        except Exception:
            pass
        self.after(2500, self._runtime_tick)

'''
new = r'''    def _runtime_tick(self):
        """Atualiza somente o status das linhas já existentes.
        Evita apagar/recriar toda a Treeview a cada poucos segundos."""
        if self._really_quitting:
            return
        try:
            self._update_runtime_rows()
        except Exception:
            pass
        self.after(4500, self._runtime_tick)

    def _update_runtime_rows(self):
        children = self.tree.get_children()
        if not children:
            return
        updates = 0
        for app_id in children:
            vals = list(self.tree.item(app_id, "values") or ())
            if len(vals) < 5:
                continue
            folder = app_dir(app_id)
            installed = folder.exists() and any(folder.iterdir())
            local = local_version(app_id, self.registry) if installed else "—"
            cand = self.candidate(app_id)
            remote = self.remote_apps.get(app_id, {})
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

            new_vals = (vals[0], local, avail, source, status)
            sig = tuple(new_vals)
            if self._last_runtime_signature.get(app_id) != sig:
                self.tree.item(app_id, values=new_vals)
                self._last_runtime_signature[app_id] = sig

        if github_connected():
            self.net.config(text=f"{updates} atualização(ões)" if updates else "Conectado")

    def _on_unmap(self, _event=None):
        if self._really_quitting:
            return
        try:
            if self.state() == "iconic":
                self.after(40, self.minimize_to_tray)
        except Exception:
            pass

    def _tray_image(self):
        if Image is None or ImageDraw is None:
            return None
        img = Image.new("RGB", (64, 64), "#111214")
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((5, 5, 59, 59), radius=12, fill="#202329", outline="#FFFFFF", width=2)
        d.text((13, 22), "KBL", fill="#FFFFFF")
        return img

    def _ensure_tray(self):
        if pystray is None or self._tray_icon is not None:
            return
        image = self._tray_image()
        if image is None:
            return

        def show(icon=None, item=None):
            self.after(0, self.restore_from_tray)

        def quit_all(icon=None, item=None):
            self.after(0, self.quit_definitively)

        menu = pystray.Menu(
            pystray.MenuItem("Abrir KBL Hub", show, default=True),
            pystray.MenuItem("Fechar definitivamente", quit_all),
        )
        self._tray_icon = pystray.Icon("KBL Hub", image, "KBL Hub", menu)

        def runner():
            try:
                self._tray_icon.run()
            except Exception:
                pass

        self._tray_thread = threading.Thread(target=runner, daemon=True)
        self._tray_thread.start()

    def minimize_to_tray(self):
        if self._really_quitting:
            return
        self._ensure_tray()
        try:
            self.withdraw()
            self.info.config(text="KBL Hub continua em execução na bandeja do sistema.")
        except Exception:
            pass

    def restore_from_tray(self):
        if self._really_quitting:
            return
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def quit_definitively(self):
        if self._really_quitting:
            return
        self._really_quitting = True
        try:
            if self._tray_icon is not None:
                self._tray_icon.stop()
        except Exception:
            pass
        self._tray_icon = None
        try:
            self.destroy()
        except Exception:
            pass

'''
if old not in t:
    raise RuntimeError("runtime tick base não encontrado")
t = t.replace(old, new, 1)

# render should refresh signatures and avoid full descriptor rescans immediately after runtime tick
old = '''            self.tree.insert("", "end", iid=app_id, values=(name, local, avail, source, status))

        if keep and self.tree.exists(keep):
'''
new = '''            row_values = (name, local, avail, source, status)
            self.tree.insert("", "end", iid=app_id, values=row_values)
            self._last_runtime_signature[app_id] = tuple(row_values)

        if keep and self.tree.exists(keep):
'''
if old not in t:
    raise RuntimeError("render insert base não encontrado")
t = t.replace(old, new, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.17")
