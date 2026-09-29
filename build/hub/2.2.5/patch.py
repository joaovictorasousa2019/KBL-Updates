from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")

if 'HUB_VERSION = "2.2.4"' in t:
    t = t.replace('HUB_VERSION = "2.2.4"', 'HUB_VERSION = "2.2.5"', 1)
elif 'HUB_VERSION = "2.2.2"' in t:
    t = t.replace('HUB_VERSION = "2.2.2"', 'HUB_VERSION = "2.2.5"', 1)
else:
    raise RuntimeError("Versão-base do Hub não encontrada")

old = '''def gh_private_download(repository, path, target):
    encoded = urllib.parse.quote(path, safe="/")
    _gh_run(["api", f"repos/{repository}/contents/{encoded}",
             "-H", "Accept: application/vnd.github.raw+json"],
            binary_stdout_path=str(target), timeout=300)
'''
new = '''def gh_private_download(repository, path, target):
    """Baixa binários privados sem usar o modo raw do gh.

    O endpoint raw pode falhar no Windows/gh com "transform: short source buffer"
    em respostas comprimidas. Aqui buscamos JSON/base64 e, se necessário,
    caímos para o endpoint de Git blob, que também retorna base64.
    """
    encoded = urllib.parse.quote(path, safe="/")
    endpoint = f"repos/{repository}/contents/{encoded}?ref=main"
    last_error = None

    for attempt in range(1, 4):
        try:
            meta = gh_api_json(endpoint)
            content = meta.get("content")
            encoding = str(meta.get("encoding") or "").lower()

            if content and encoding == "base64":
                data = base64.b64decode(content, validate=False)
            else:
                sha = meta.get("sha")
                if not sha:
                    raise RuntimeError("GitHub não retornou conteúdo nem SHA do pacote.")
                blob = gh_api_json(f"repos/{repository}/git/blobs/{sha}")
                if str(blob.get("encoding") or "").lower() != "base64" or not blob.get("content"):
                    raise RuntimeError("GitHub não retornou o blob do pacote em base64.")
                data = base64.b64decode(blob["content"], validate=False)

            if not data:
                raise RuntimeError("O pacote baixado veio vazio.")

            Path(target).write_bytes(data)
            return
        except Exception as exc:
            last_error = exc
            try:
                Path(target).unlink(missing_ok=True)
            except Exception:
                pass
            if attempt < 3:
                time.sleep(0.6 * attempt)

    raise RuntimeError(f"Falha ao baixar pacote privado após 3 tentativas: {last_error}")
'''
if old not in t:
    raise RuntimeError("gh_private_download antigo não encontrado")
t = t.replace(old, new, 1)

p.write_text(t, encoding="utf-8")
print("KBL Hub patched to 2.2.5")
