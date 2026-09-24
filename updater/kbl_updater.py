# KBL Updater v1.0.0
# Atualizador genérico dos aplicativos KBL.
# Usa apenas a biblioteca padrão do Python.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

UPDATER_VERSION = "1.0.0"


def _version_tuple(value: str):
    parts = []
    for p in str(value).strip().lstrip("vV").split("."):
        n = ""
        for ch in p:
            if ch.isdigit():
                n += ch
            else:
                break
        parts.append(int(n or 0))
    return tuple((parts + [0, 0, 0])[:3])


def is_newer(remote: str, local: str) -> bool:
    return _version_tuple(remote) > _version_tuple(local)


def fetch_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "KBL-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def download(url: str, target: Path, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "KBL-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r, target.open("wb") as f:
        shutil.copyfileobj(r, f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().lower()


def safe_extract(zf: zipfile.ZipFile, destination: Path):
    root = destination.resolve()
    for info in zf.infolist():
        out = (destination / info.filename).resolve()
        if root != out and root not in out.parents:
            raise RuntimeError(f"Arquivo inseguro no ZIP: {info.filename}")
    zf.extractall(destination)


def wait_pid(pid: int | None, timeout: int = 45):
    if not pid:
        return
    end = time.time() + timeout
    while time.time() < end:
        try:
            os.kill(pid, 0)
            time.sleep(0.4)
        except OSError:
            return
    raise RuntimeError("O aplicativo não encerrou a tempo para atualizar.")


def copy_tree_contents(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def backup_app(app_dir: Path, backup_dir: Path):
    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    for item in app_dir.iterdir():
        # Dados do usuário ficam fora da pasta do aplicativo.
        if item.name.lower() in {"data", "dados", "userdata"}:
            continue
        target = backup_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def restore_backup(app_dir: Path, backup_dir: Path):
    if not backup_dir.exists():
        return
    for item in list(app_dir.iterdir()):
        if item.name.lower() in {"data", "dados", "userdata"}:
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        except FileNotFoundError:
            pass
    copy_tree_contents(backup_dir, app_dir)


def restart(path: Path | None):
    if not path or not path.exists():
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([str(path)], cwd=str(path.parent), creationflags=flags)


def apply_update(manifest_url: str, app_dir: Path, local_version: str,
                 pid: int | None = None, restart_path: Path | None = None):
    manifest = fetch_json(manifest_url)
    if not manifest.get("published"):
        return {"status": "unpublished", "manifest": manifest}

    remote_version = str(manifest.get("version", "0.0.0"))
    if not is_newer(remote_version, local_version):
        return {"status": "up_to_date", "version": local_version}

    url = str(manifest.get("download_url") or "").strip()
    expected = str(manifest.get("sha256") or "").strip().lower()
    if not url or len(expected) != 64:
        raise RuntimeError("Manifesto incompleto: download_url/sha256.")

    work = Path(tempfile.mkdtemp(prefix="kbl_update_"))
    package = work / (manifest.get("file_name") or "update.zip")
    extracted = work / "extracted"
    backup = app_dir.parent / f".{app_dir.name}_rollback"

    try:
        download(url, package)
        actual = sha256_file(package)
        if actual != expected:
            raise RuntimeError("SHA-256 inválido. Atualização cancelada.")

        extracted.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package, "r") as zf:
            safe_extract(zf, extracted)

        wait_pid(pid)
        backup_app(app_dir, backup)

        try:
            copy_tree_contents(extracted, app_dir)
        except Exception:
            restore_backup(app_dir, backup)
            raise

        restart(restart_path)
        return {"status": "updated", "version": remote_version}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest-url", required=True)
    p.add_argument("--app-dir", required=True)
    p.add_argument("--local-version", required=True)
    p.add_argument("--pid", type=int)
    p.add_argument("--restart")
    p.add_argument("--check-only", action="store_true")
    args = p.parse_args()

    if args.check_only:
        m = fetch_json(args.manifest_url)
        print(json.dumps({
            "published": bool(m.get("published")),
            "local_version": args.local_version,
            "remote_version": m.get("version"),
            "update_available": bool(m.get("published")) and is_newer(str(m.get("version","0.0.0")), args.local_version),
            "notes": m.get("notes", [])
        }, ensure_ascii=False))
        return

    result = apply_update(
        args.manifest_url,
        Path(args.app_dir).resolve(),
        args.local_version,
        args.pid,
        Path(args.restart).resolve() if args.restart else None
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
