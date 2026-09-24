# KBL Update Center v1.0.0
# Módulo para integrar ao KBL Fechamento Contábil / Hub.
# Biblioteca padrão apenas: tkinter + urllib + json.

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

MANIFEST_URL = "https://raw.githubusercontent.com/joaovictorasousa2019/KBL-Updates/main/manifest.json"
BASE_DATA = Path(os.getenv("APPDATA", Path.home())) / "KBLAccounting" / "Updates"
REGISTRY_FILE = BASE_DATA / "registry.json"


def _v(v):
    out=[]
    for part in str(v or "0").lstrip("vV").split("."):
        s=""
        for ch in part:
            if ch.isdigit(): s+=ch
            else: break
        out.append(int(s or 0))
    return tuple((out+[0,0,0])[:3])


def _get_json(url, timeout=15):
    req=urllib.request.Request(url,headers={"User-Agent":"KBL-Fechamento-Contabil/Updater"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def _load_registry():
    BASE_DATA.mkdir(parents=True,exist_ok=True)
    if not REGISTRY_FILE.exists():
        return {"schema_version":1,"apps":{}}
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version":1,"apps":{}}


def _save_registry(data):
    BASE_DATA.mkdir(parents=True,exist_ok=True)
    tmp=REGISTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(REGISTRY_FILE)


class KBLUpdateCenter(tk.Toplevel):
    def __init__(self, master, updater_path=None, on_close=None):
        super().__init__(master)
        self.title("Atualizações • KBL")
        self.geometry("900x520")
        self.minsize(760,420)
        self.transient(master)
        self.registry=_load_registry()
        self.updater_path=Path(updater_path) if updater_path else Path(__file__).with_name("kbl_updater.py")
        self.remote={}
        self.rows={}
        self.on_close=on_close
        self.protocol("WM_DELETE_WINDOW",self._close)
        self._build()
        self.after(150,self.check_updates)

    def _build(self):
        top=ttk.Frame(self,padding=18)
        top.pack(fill="both",expand=True)

        head=ttk.Frame(top)
        head.pack(fill="x")
        ttk.Label(head,text="Atualizações dos aplicativos KBL",font=("Segoe UI",16,"bold")).pack(side="left")
        self.status=ttk.Label(head,text="Verificando…")
        self.status.pack(side="right")

        ttk.Label(
            top,
            text="O Hub compara as versões instaladas com o manifesto oficial e preserva os dados locais.",
        ).pack(anchor="w",pady=(6,14))

        cols=("app","instalada","disponivel","status")
        self.tree=ttk.Treeview(top,columns=cols,show="headings",height=12)
        self.tree.heading("app",text="Aplicativo")
        self.tree.heading("instalada",text="Instalada")
        self.tree.heading("disponivel",text="Disponível")
        self.tree.heading("status",text="Status")
        self.tree.column("app",width=330)
        self.tree.column("instalada",width=100,anchor="center")
        self.tree.column("disponivel",width=100,anchor="center")
        self.tree.column("status",width=180)
        self.tree.pack(fill="both",expand=True)

        bar=ttk.Frame(top)
        bar.pack(fill="x",pady=(14,0))
        ttk.Button(bar,text="Configurar pasta",command=self.configure_selected).pack(side="left")
        ttk.Button(bar,text="Verificar novamente",command=self.check_updates).pack(side="left",padx=8)
        ttk.Button(bar,text="Atualizar selecionado",command=self.update_selected).pack(side="right")
        ttk.Button(bar,text="Atualizar todos",command=self.update_all).pack(side="right",padx=8)

    def _close(self):
        if self.on_close:
            try: self.on_close()
            except Exception: pass
        self.destroy()

    def _selected_app_id(self):
        sel=self.tree.selection()
        return sel[0] if sel else None

    def configure_selected(self):
        app_id=self._selected_app_id()
        if not app_id:
            messagebox.showinfo("KBL","Selecione um aplicativo.")
            return
        folder=filedialog.askdirectory(title="Selecione a pasta instalada do aplicativo")
        if not folder: return
        app=self.registry.setdefault("apps",{}).setdefault(app_id,{})
        app["install_dir"]=folder
        app.setdefault("version","0.0.0")
        _save_registry(self.registry)
        self.check_updates()

    def check_updates(self):
        self.status.config(text="Verificando…")
        threading.Thread(target=self._check_worker,daemon=True).start()

    def _check_worker(self):
        try:
            root=_get_json(MANIFEST_URL)
            remote={}
            for item in root.get("apps",[]):
                try:
                    remote[item["app_id"]]=_get_json(item["manifest_url"])
                except Exception as exc:
                    remote[item["app_id"]]={"name":item.get("name",item["app_id"]),"error":str(exc),"published":False}
            self.remote=remote
            self.after(0,self._render)
        except Exception as exc:
            self.after(0,lambda: self._error(str(exc)))

    def _error(self,msg):
        self.status.config(text="Falha na verificação")
        messagebox.showerror("Atualizações KBL",msg)

    def _local_version(self,app_id):
        app=self.registry.get("apps",{}).get(app_id,{})
        install=Path(app.get("install_dir","")) if app.get("install_dir") else None
        if install:
            vf=install/"version.json"
            if vf.exists():
                try:
                    return str(json.loads(vf.read_text(encoding="utf-8-sig")).get("version","0.0.0"))
                except Exception:
                    pass
        return str(app.get("version","0.0.0"))

    def _render(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        updates=0
        for app_id,m in self.remote.items():
            local=self._local_version(app_id)
            remote=str(m.get("version","0.0.0"))
            configured=bool(self.registry.get("apps",{}).get(app_id,{}).get("install_dir"))
            if m.get("error"):
                st="Erro ao consultar"
            elif not configured:
                st="Pasta não configurada"
            elif not m.get("published"):
                st="Sem publicação"
            elif _v(remote)>_v(local):
                st="Atualização disponível"
                updates+=1
            else:
                st="Atualizado"
            self.tree.insert("", "end", iid=app_id, values=(m.get("name",app_id),local,remote,st))
        self.status.config(text=(f"{updates} atualização(ões)" if updates else "Tudo atualizado"))

    def _launch_update(self,app_id):
        m=self.remote.get(app_id,{})
        if not m.get("published"):
            return False
        local=self._local_version(app_id)
        if _v(str(m.get("version","0.0.0")))<=_v(local):
            return False
        reg=self.registry.get("apps",{}).get(app_id,{})
        app_dir=reg.get("install_dir")
        if not app_dir:
            return False

        manifest_url=next((x["manifest_url"] for x in _get_json(MANIFEST_URL).get("apps",[]) if x.get("app_id")==app_id),None)
        if not manifest_url:
            return False

        pyw=Path(sys.executable)
        if pyw.name.lower()=="python.exe":
            candidate=pyw.with_name("pythonw.exe")
            if candidate.exists(): pyw=candidate

        cmd=[
            str(pyw),str(self.updater_path),
            "--manifest-url",manifest_url,
            "--app-dir",app_dir,
            "--local-version",local
        ]
        entry=reg.get("entrypoint")
        if entry:
            cmd += ["--restart",str(Path(app_dir)/entry)]
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        subprocess.Popen(cmd,cwd=str(self.updater_path.parent),creationflags=flags)
        return True

    def update_selected(self):
        app_id=self._selected_app_id()
        if not app_id:
            messagebox.showinfo("KBL","Selecione um aplicativo.")
            return
        if self._launch_update(app_id):
            messagebox.showinfo("KBL","Atualização iniciada. O aplicativo será reaberto ao concluir.")
        else:
            messagebox.showinfo("KBL","Nenhuma atualização aplicável para este aplicativo.")

    def update_all(self):
        count=0
        for app_id in list(self.remote):
            if self._launch_update(app_id):
                count+=1
        if count:
            messagebox.showinfo("KBL",f"{count} atualização(ões) iniciada(s).")
        else:
            messagebox.showinfo("KBL","Não há atualizações aplicáveis.")


def open_update_center(master, updater_path=None):
    return KBLUpdateCenter(master,updater_path=updater_path)
