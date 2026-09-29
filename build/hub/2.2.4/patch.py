from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

# Version
for old in ('HUB_VERSION = "2.2.3"', 'HUB_VERSION = "2.2.2"', 'HUB_VERSION = "2.2.0"'):
    if old in t:
        t = t.replace(old, 'HUB_VERSION = "2.2.4"', 1)
        break
else:
    raise RuntimeError("HUB_VERSION esperado não encontrado")

# time para limpeza resiliente no Windows
if "import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.request, urllib.parse, zipfile, datetime" in t:
    t = t.replace(
        "import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.request, urllib.parse, zipfile, datetime",
        "import base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, urllib.request, urllib.parse, zipfile, datetime, time",
        1
    )

# Limpeza de temporários que não pode derrubar uma publicação já concluída.
anchor = """def safe_extract(zf, dest):
    root = Path(dest).resolve()
    for info in zf.infolist():
        out = (root / info.filename).resolve()
        if root != out and root not in out.parents:
            raise RuntimeError(f"Arquivo inseguro no ZIP: {info.filename}")
    zf.extractall(root)

"""
if anchor not in t:
    raise RuntimeError("Âncora safe_extract não encontrada")
insert = anchor + """def safe_unlink(path, attempts=15, delay=0.12):
    path = Path(path)
    last = None
    for _ in range(max(1, attempts)):
        try:
            path.unlink(missing_ok=True)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            last = exc
            time.sleep(delay)
    # Arquivo temporário travado não pode transformar uma publicação concluída em falha.
    # O Windows/antivírus libera o handle depois; o arquivo fica no TEMP para limpeza normal.
    return False

"""
t = t.replace(anchor, insert, 1)

# Fecha corretamente stdin quando _gh_run usar arquivo como entrada.
old_gh = """def _gh_run(args, *, input_path=None, binary_stdout_path=None, timeout=300):
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
"""
new_gh = """def _gh_run(args, *, input_path=None, binary_stdout_path=None, timeout=300):
    gh = gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI não está instalado.")
    if not github_connected():
        raise RuntimeError("GitHub não está conectado. Abra Administração > Conectar GitHub.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [str(gh), *args]
    stderr = subprocess.PIPE
    inp = open(input_path, "rb") if input_path else None
    try:
        if binary_stdout_path:
            with open(binary_stdout_path, "wb") as out:
                r = subprocess.run(cmd, stdin=inp, stdout=out, stderr=stderr,
                                   creationflags=flags, timeout=timeout)
        else:
            r = subprocess.run(cmd, stdin=inp, stdout=subprocess.PIPE, stderr=stderr,
                               creationflags=flags, timeout=timeout)
    finally:
        if inp is not None:
            inp.close()
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(err or f"GitHub CLI retornou código {r.returncode}.")
    return r.stdout if not binary_stdout_path else b""
"""
if old_gh not in t:
    raise RuntimeError("_gh_run esperado não encontrado")
t = t.replace(old_gh, new_gh, 1)

# Substitui limpeza frágil de temporários.
t = t.replace("        tmp.unlink(missing_ok=True)\n", "        safe_unlink(tmp)\n")

# Consulta autoritativa da versão estável publicada.
anchor2 = """def gh_update_public_manifest(app_id, version, file_name, file_sha, package_path, package_meta=None):
"""
if anchor2 not in t:
    raise RuntimeError("gh_update_public_manifest não encontrado")
helper = """def published_version_from_repo(app_id):
    try:
        endpoint = f"repos/{UPDATES_REPO}/contents/apps/{app_id}/version.json"
        meta = gh_api_json(endpoint + "?ref=main")
        content = base64.b64decode(meta["content"]).decode("utf-8-sig")
        obj = json.loads(content)
        return str(obj.get("version") or "0.0.0")
    except Exception:
        return "0.0.0"

"""
t = t.replace(anchor2, helper + anchor2, 1)

# Bloqueio visual antes da confirmação.
old_choose = """        current = self.remote_apps.get(app_id, {}).get("version", "—")
        msg = (f"Aplicativo: {name}\n"
               f"Versão do pacote: {version}\n"
               f"Versão publicada: {current}\n\n"
               f"Publicar no KBL-Apps privado e ativar no KBL-Updates?")
"""
new_choose = """        current = self.remote_apps.get(app_id, {}).get("version", "—")
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
"""
if old_choose not in t:
    raise RuntimeError("Trecho _admin_choose_publish não encontrado")
t = t.replace(old_choose, new_choose, 1)

# Bloqueio autoritativo no worker, inclusive contra tela desatualizada/concorrência.
old_publish = """    def _publish_package(self, app_id, version, file_path):
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
"""
new_publish = """    def _publish_package(self, app_id, version, file_path):
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
"""
if old_publish not in t:
    raise RuntimeError("Trecho _publish_package não encontrado")
t = t.replace(old_publish, new_publish, 1)

# Pré-valida o pacote antes de substituir uma instalação existente.
old_install = """            ext.mkdir()
            with zipfile.ZipFile(pkg) as zf:
                safe_extract(zf, ext)

            if folder.exists() and any(folder.iterdir()):
"""
new_install = """            ext.mkdir()
            with zipfile.ZipFile(pkg) as zf:
                safe_extract(zf, ext)

            extracted_items = list(ext.iterdir())
            extracted_src = extracted_items[0] if len(extracted_items) == 1 and extracted_items[0].is_dir() else ext
            if not find_entrypoint(extracted_src, app_id):
                raise RuntimeError(
                    "O pacote foi baixado, mas não contém um inicializador válido para este aplicativo. "
                    "A instalação anterior foi mantida."
                )

            if folder.exists() and any(folder.iterdir()):
"""
if old_install not in t:
    raise RuntimeError("Trecho de pré-validação não encontrado")
t = t.replace(old_install, new_install, 1)

t = t.replace(
"""            items = list(ext.iterdir())
            src = items[0] if len(items) == 1 and items[0].is_dir() else ext
            shutil.copytree(src, folder, dirs_exist_ok=True)
""",
"""            src = extracted_src
            shutil.copytree(src, folder, dirs_exist_ok=True)
""",
1
)

old_except = """        except Exception:
            if backup.exists():
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
                shutil.copytree(backup, folder)
            raise
"""
new_except = """        except Exception:
            if backup.exists():
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
                shutil.copytree(backup, folder)
            elif folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            raise
"""
if old_except not in t:
    raise RuntimeError("Trecho de rollback não encontrado")
t = t.replace(old_except, new_except, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.4")
