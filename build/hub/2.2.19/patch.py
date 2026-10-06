from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

if 'HUB_VERSION = "2.2.18"' not in t:
    raise RuntimeError("KBL Hub 2.2.18 base não encontrada")
t = t.replace('HUB_VERSION = "2.2.18"', 'HUB_VERSION = "2.2.19"', 1)

# Estado visual: arquivados começam ocultos a cada abertura, mas a lista arquivada é persistida.
old = '''        self._runtime_rows_cache = {}
        self._github_connected_cache = None
        self._build()
'''
new = '''        self._runtime_rows_cache = {}
        self._github_connected_cache = None
        self.show_archived = False
        self._build()
'''
if old not in t:
    raise RuntimeError("estado 2.2.18 não encontrado")
t = t.replace(old, new, 1)

# Helpers e ações de arquivamento. Arquivar nunca remove instalação, dados ou histórico.
anchor = '''    def _selected_action(self):
'''
helpers = '''    def archived_ids(self):
        raw = self.registry.get("archived_apps", [])
        if not isinstance(raw, list):
            return set()
        return {str(x) for x in raw if str(x).strip()}

    def is_archived(self, app_id):
        return str(app_id) in self.archived_ids()

    def _save_archived_ids(self, ids):
        self.registry["archived_apps"] = sorted({str(x) for x in ids if str(x).strip()})
        save_registry(self.registry)

    def archive_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        ids = self.archived_ids()
        if app_id in ids:
            return self.restore_selected()
        ids.add(app_id)
        self._save_archived_ids(ids)
        name = app_display_name(app_id, self.remote_apps.get(app_id, {}), self.candidate(app_id))
        self.info.config(text=f"{name} foi arquivado. Instalação e dados foram mantidos.")
        self.render()

    def restore_selected(self):
        app_id = self.selected_id()
        if not app_id:
            return messagebox.showinfo("KBL Hub", "Selecione um aplicativo.")
        ids = self.archived_ids()
        if app_id not in ids:
            return
        ids.discard(app_id)
        self._save_archived_ids(ids)
        name = app_display_name(app_id, self.remote_apps.get(app_id, {}), self.candidate(app_id))
        self.info.config(text=f"{name} voltou para a lista principal.")
        self.render()

    def toggle_archived(self):
        self.show_archived = not bool(self.show_archived)
        self.render()

'''
if anchor not in t:
    raise RuntimeError("_selected_action não encontrado")
t = t.replace(anchor, helpers + anchor, 1)

# Quando a área de arquivados está visível, a ação principal vira Restaurar.
old = '''        if not app_id:
            return "Selecionar aplicativo", None
        folder = app_dir(app_id)
'''
new = '''        if not app_id:
            return "Selecionar aplicativo", None
        if self.is_archived(app_id):
            return "Restaurar", self.restore_selected
        folder = app_dir(app_id)
'''
if old not in t:
    raise RuntimeError("_selected_action base não encontrado")
t = t.replace(old, new, 1)

# Menu Mais: arquivar/restaurar o selecionado e alternar a visualização dos arquivados.
old = '''        menu.add_command(label="Encerrar aplicativo", command=self.close_selected,
                         state=("normal" if running else "disabled"))
'''
new = '''        if app_id:
            if self.is_archived(app_id):
                menu.add_command(label="Restaurar aplicativo", command=self.restore_selected)
            else:
                menu.add_command(label="Arquivar aplicativo", command=self.archive_selected)
            menu.add_separator()

        menu.add_command(label="Encerrar aplicativo", command=self.close_selected,
                         state=("normal" if running else "disabled"))
'''
if old not in t:
    raise RuntimeError("menu Mais base não encontrado")
t = t.replace(old, new, 1)

old = '''        menu.add_separator()
        menu.add_command(label="Instalar todos os disponíveis...", command=self.install_all)
        menu.add_command(label="Atualizar versões", command=self.refresh_remote)
'''
new = '''        archived_count = len(self.archived_ids())
        if archived_count:
            menu.add_separator()
            menu.add_command(
                label=("Ocultar arquivados" if self.show_archived else f"Mostrar arquivados ({archived_count})"),
                command=self.toggle_archived,
            )

        menu.add_separator()
        menu.add_command(label="Instalar todos os disponíveis...", command=self.install_all)
        menu.add_command(label="Atualizar versões", command=self.refresh_remote)
'''
if old not in t:
    raise RuntimeError("rodapé do menu Mais não encontrado")
t = t.replace(old, new, 1)

# A grade principal ignora arquivados até o usuário pedir para mostrá-los.
old = '''        for app_id in self.all_ids():
            folder = app_dir(app_id)
'''
new = '''        for app_id in self.all_ids():
            archived = self.is_archived(app_id)
            if archived and not self.show_archived:
                continue
            folder = app_dir(app_id)
'''
# Há dois loops semelhantes (runtime em background e render). O primeiro é o runtime.
if old not in t:
    raise RuntimeError("loop de runtime não encontrado")
t = t.replace(old, '''        for app_id in self.all_ids():
            archived = self.is_archived(app_id)
            folder = app_dir(app_id)
''', 1)
# O segundo é o render.
if old not in t:
    raise RuntimeError("loop de render não encontrado")
t = t.replace(old, new, 1)

# Atualizações arquivadas não entram no contador principal. Quando visíveis, recebem rótulo claro.
old = '''            elif cand and vtuple(cand["version"]) > vtuple(local):
                status = (run_status + " • " if run_status else "") + "Atualização disponível"
                updates += 1
            elif run_status:
'''
new_runtime = '''            elif cand and vtuple(cand["version"]) > vtuple(local):
                status = (run_status + " • " if run_status else "") + "Atualização disponível"
                if not archived:
                    updates += 1
            elif run_status:
'''
if old not in t:
    raise RuntimeError("status de atualização do runtime não encontrado")
t = t.replace(old, new_runtime, 1)
if old not in t:
    raise RuntimeError("status de atualização do render não encontrado")
t = t.replace(old, new_runtime, 1)

old = '''            rows[app_id] = (name, local, avail, source, status)
'''
new = '''            if archived:
                status = "Arquivado • " + status
            rows[app_id] = (name, local, avail, source, status)
'''
if old not in t:
    raise RuntimeError("linha de cache do runtime não encontrada")
t = t.replace(old, new, 1)

old = '''            row_values = (name, local, avail, source, status)
            self.tree.insert("", "end", iid=app_id, values=row_values)
'''
new = '''            if archived:
                status = "Arquivado • " + status
            row_values = (name, local, avail, source, status)
            self.tree.insert("", "end", iid=app_id, values=row_values)
'''
if old not in t:
    raise RuntimeError("linha visual do render não encontrada")
t = t.replace(old, new, 1)

# Operações em lote respeitam o arquivamento.
old = '''        ids = [i for i in self.all_ids()
               if self.candidate(i) and not (app_dir(i).exists() and any(app_dir(i).iterdir()))]
'''
new = '''        ids = [i for i in self.all_ids()
               if not self.is_archived(i)
               and self.candidate(i) and not (app_dir(i).exists() and any(app_dir(i).iterdir()))]
'''
if old not in t:
    raise RuntimeError("install_all não encontrado")
t = t.replace(old, new, 1)

old = '''        for i in self.all_ids():
            c = self.candidate(i)
'''
new = '''        for i in self.all_ids():
            if self.is_archived(i):
                continue
            c = self.candidate(i)
'''
if old not in t:
    raise RuntimeError("update_all não encontrado")
t = t.replace(old, new, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.19")
