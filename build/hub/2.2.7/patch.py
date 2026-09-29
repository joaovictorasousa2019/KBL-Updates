from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

if 'HUB_VERSION = "2.2.6"' not in t:
    raise RuntimeError("KBL Hub 2.2.6 base não encontrada")
t = t.replace('HUB_VERSION = "2.2.6"', 'HUB_VERSION = "2.2.7"', 1)

# 1) Toda leitura HTTP do catálogo passa a ignorar cache de CDN/proxy.
old_get = '''def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": f"KBL-Hub/{HUB_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8-sig"))
'''
new_get = '''def _fresh_url(url):
    """Adiciona cache-buster sem perder parâmetros existentes."""
    try:
        parts = urllib.parse.urlsplit(str(url))
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if k != "_kbl_cache"]
        query.append(("_kbl_cache", str(time.time_ns())))
        return urllib.parse.urlunsplit((
            parts.scheme, parts.netloc, parts.path,
            urllib.parse.urlencode(query), parts.fragment
        ))
    except Exception:
        sep = "&" if "?" in str(url) else "?"
        return f"{url}{sep}_kbl_cache={time.time_ns()}"

def get_json(url, timeout=20, fresh=True):
    target = _fresh_url(url) if fresh else str(url)
    req = urllib.request.Request(target, headers={
        "User-Agent": f"KBL-Hub/{HUB_VERSION}",
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8-sig"))
'''
if old_get not in t:
    raise RuntimeError("get_json antigo não encontrado")
t = t.replace(old_get, new_get, 1)

# 2) Fonte autoritativa para confirmar publicação sem depender do raw.githubusercontent.
anchor = '''def gh_api_json(endpoint):
    raw = _gh_run(["api", endpoint], timeout=60)
    return json.loads(raw.decode("utf-8"))
'''
if anchor not in t:
    raise RuntimeError("gh_api_json não encontrado")
helpers = anchor + '''
def gh_read_public_manifest(app_id):
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
    raise RuntimeError(
        f"Publicação enviada, mas a confirmação remota ainda não ficou consistente: {last}"
    )
'''
t = t.replace(anchor, helpers, 1)

# published_version_from_repo passa a usar a mesma leitura autoritativa.
old_published = '''def published_version_from_repo(app_id):
    try:
        endpoint = f"repos/{UPDATES_REPO}/contents/apps/{app_id}/version.json"
        meta = gh_api_json(endpoint + "?ref=main")
        content = base64.b64decode(meta["content"]).decode("utf-8-sig")
        obj = json.loads(content)
        return str(obj.get("version") or "0.0.0")
    except Exception:
        return "0.0.0"
'''
new_published = '''def published_version_from_repo(app_id):
    try:
        return str(gh_read_public_manifest(app_id).get("version") or "0.0.0")
    except Exception:
        return "0.0.0"
'''
if old_published not in t:
    raise RuntimeError("published_version_from_repo antigo não encontrado")
t = t.replace(old_published, new_published, 1)

# 3) Cada publicação também versiona a URL do manifesto do app para ajudar Hubs antigos.
old_url = '    url = f"https://raw.githubusercontent.com/{UPDATES_REPO}/main/apps/{app_id}/version.json"\n'
new_url = '    url = f"https://raw.githubusercontent.com/{UPDATES_REPO}/main/apps/{app_id}/version.json?v={urllib.parse.quote(str(version))}"\n'
if old_url not in t:
    raise RuntimeError("URL do version.json não encontrada")
t = t.replace(old_url, new_url, 1)

# 4) Atualização da grade: força rede nova e impede resposta antiga de sobrescrever nova.
old_refresh = '''    def refresh_remote(self):
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
'''
new_refresh = '''    def refresh_remote(self):
        self._refresh_seq = int(getattr(self, "_refresh_seq", 0) or 0) + 1
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
            if seq is not None and seq != getattr(self, "_refresh_seq", seq):
                return
            self.remote_root = root
            self.remote_apps = apps
            globals()["_HUB_REMOTE_CACHE"] = apps
            self.after(0, self.render)
        except Exception:
            if seq is not None and seq != getattr(self, "_refresh_seq", seq):
                return
            self.after(0, lambda: self.render(offline=True))
'''
if old_refresh not in t:
    raise RuntimeError("Bloco refresh_remote não encontrado")
t = t.replace(old_refresh, new_refresh, 1)

t = t.replace(
    'menu.add_command(label="Verificar atualizações", command=self.refresh_remote)',
    'menu.add_command(label="Atualizar versões", command=self.refresh_remote)',
    1
)

# 5) Mesma versão pode ser reparada; versão inferior continua bloqueada.
old_choose = r'''        current = self.remote_apps.get(app_id, {}).get("version", "—")
        if current not in ("", "—", None) and vtuple(version) <= vtuple(current):
            return messagebox.showerror(
                "Publicação bloqueada",
                f"A versão {version} não pode ser publicada porque a versão estável atual é {current}.\n\n"
                "O catálogo só aceita versões maiores que a publicada. "
                "Para voltar uma versão no computador, use a opção de reversão do aplicativo; "
                "isso não altera a versão estável publicada.",
                parent=parent,
            )
        msg = (f"Aplicativo: {name}\n"
               f"Versão do pacote: {version}\n"
               f"Versão publicada: {current}\n\n"
               f"Publicar no KBL-Apps privado e ativar no KBL-Updates?")
        if not messagebox.askyesno("Publicar atualização", msg, parent=parent):
            return
        threading.Thread(target=self._publish_worker,
                         args=(app_id, version, Path(file_path), label, parent), daemon=True).start()
'''
new_choose = r'''        current_obj = {}
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
                parent=parent,
            )

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
'''
if old_choose not in t:
    raise RuntimeError("Bloco de escolha de publicação 2.2.6 não encontrado")
t = t.replace(old_choose, new_choose, 1)

old_worker = '''    def _publish_worker(self, app_id, version, file_path, label, parent):
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
'''
new_worker = '''    def _publish_worker(self, app_id, version, file_path, label, parent, repair=False):
        try:
            action = "Reparando" if repair else "Publicando"
            self.after(0, lambda: label.config(text=f"{action} {app_id} v{version}..."))
            digest, package_path = self._publish_package(app_id, version, file_path)
            self.after(0, lambda: label.config(text=f"Confirmando {app_id} v{version} no catálogo remoto..."))
            confirmed = gh_confirm_publication(app_id, version, digest, package_path)

            self.remote_apps[app_id] = confirmed
            globals().setdefault("_HUB_REMOTE_CACHE", {})[app_id] = confirmed
            self.after(0, self.render)
            self.after(0, lambda: label.config(text=f"{app_id} v{version} confirmado no catálogo."))
            self.after(250, self.refresh_remote)

            msg = (f"{app_id} v{version} reparado e confirmado." if repair
                   else f"{app_id} v{version} publicado e confirmado.")
            self.after(0, lambda m=msg: messagebox.showinfo("KBL Hub", m, parent=parent))
        except Exception as exc:
            self.after(0, lambda e=exc: label.config(text=f"Falha: {e}"))
            self.after(0, lambda e=exc: messagebox.showerror("KBL Hub", str(e), parent=parent))
'''
if old_worker not in t:
    raise RuntimeError("_publish_worker 2.2.6 não encontrado")
t = t.replace(old_worker, new_worker, 1)

old_publish = '''    def _publish_package(self, app_id, version, file_path):
        if not github_connected():
            raise RuntimeError("GitHub não está conectado.")
        published = published_version_from_repo(app_id)
        if vtuple(version) <= vtuple(published):
            raise RuntimeError(
                f"Publicação bloqueada: v{version} não é maior que a versão estável v{published}. "
                "Reversão local continua permitida, mas o catálogo remoto nunca é rebaixado."
            )
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
'''
new_publish = '''    def _publish_package(self, app_id, version, file_path):
        if not github_connected():
            raise RuntimeError("GitHub não está conectado.")
        published = published_version_from_repo(app_id)
        if vtuple(version) < vtuple(published):
            raise RuntimeError(
                f"Publicação bloqueada: v{version} é menor que a versão estável v{published}. "
                "Reversão local continua permitida, mas o catálogo remoto nunca é rebaixado."
            )
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
        return digest, package_path
'''
if old_publish not in t:
    raise RuntimeError("_publish_package 2.2.6 não encontrado")
t = t.replace(old_publish, new_publish, 1)

# Garante atributo antes da primeira consulta, embora refresh_remote também seja defensivo.
old_init = '''        self.remote_root = {}
        self.remote_apps = {}
        self.local_descriptors = {}
'''
new_init = '''        self.remote_root = {}
        self.remote_apps = {}
        self.local_descriptors = {}
        self._refresh_seq = 0
'''
if old_init not in t:
    raise RuntimeError("Inicialização remota não encontrada")
t = t.replace(old_init, new_init, 1)

# Corrige escape quebrado herdado do patch 2.2.6 no comando PowerShell.
broken_pid = '            f"$p=Get-CimInstance Win32_Process -Filter "ProcessId = {int(pid)}" -ErrorAction SilentlyContinue; "'
fixed_pid = '            f\'$p=Get-CimInstance Win32_Process -Filter "ProcessId = {int(pid)}" -ErrorAction SilentlyContinue; \''
if broken_pid in t:
    t = t.replace(broken_pid, fixed_pid, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.7")
