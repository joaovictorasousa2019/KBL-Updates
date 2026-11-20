# -*- coding: utf-8 -*-
"""Frutaverso Studio 90s - um ZIP de roteiro/imagens, um clique para o MP4."""
from __future__ import annotations
import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageOps

import frutaverso as base
import episode90 as ep

VERSION="0.6.0"
base.VERSION=VERSION
STATE=base.APP_HOME/"studio90_config.json"
PACKS=base.DATA/"pacotes"

class Studio90(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FRUTAVERSO STUDIO - TikTok 90s")
        self.geometry("1110x760")
        self.minsize(890,640)
        self.configure(bg="#111827")
        self.events=queue.Queue()
        self.busy=False
        self.current=None
        self.preview=None
        self.pending_update=None
        self.make_ui()
        self.after(140,self.drain)
        self.load_last()
        if base.RUNNING:threading.Thread(target=self.check_updates,daemon=True).start()

    def text(self,box,t,size=11,color="#e8eef9",bold=False):
        return tk.Label(box,text=t,bg=box["bg"],fg=color,font=("Segoe UI",size,"bold" if bold else "normal"))
    def btn(self,box,label,callback,accent=False):
        return tk.Button(box,text=label,command=callback,padx=18,pady=12,borderwidth=0,
                         font=("Segoe UI",11,"bold"),bg="#f5b537" if accent else "#2c3e5d",
                         fg="#101520" if accent else "white",activebackground="#fdd077",
                         relief="flat",cursor="hand2")
    def make_ui(self):
        bar=tk.Frame(self,bg="#111827");bar.pack(fill="x",padx=24,pady=(20,10))
        self.text(bar,"FRUTAVERSO",size=25,color="#ffbd43",bold=True).pack(side="left")
        self.text(bar,"STUDIO",size=25,bold=True).pack(side="left",padx=(5,18))
        self.text(bar,"v"+VERSION+"  |  sem CMD  |  RTX 4060",size=10,color="#93a7c4").pack(side="left")
        self.btn(bar,"Buscar atualizacoes",self.check_async).pack(side="right")
        main=tk.Frame(self,bg="#111827");main.pack(fill="both",expand=True,padx=24)
        left=tk.Frame(main,bg="#1a2436")
        left.pack(side="left",fill="both",expand=True,padx=(0,9))
        right=tk.Frame(main,bg="#1a2436",width=350)
        right.pack(side="left",fill="y",padx=(9,0))
        right.pack_propagate(False)
        self.text(left,"1. IMPORTE O EPISODIO",size=15,color="#ffbd43",bold=True).pack(anchor="w",padx=20,pady=(20,5))
        self.text(left,"O pacote ZIP contem roteiro.json e imagens. Nao precisa editar cenas ou prompts.",
                  color="#afc0d9",size=10).pack(anchor="w",padx=20,pady=(0,14))
        self.btn(left,"IMPORTAR ZIP DE ROTEIRO + IMAGENS",self.import_dialog).pack(anchor="w",padx=20)
        self.name=tk.StringVar(value="Nenhum episodio importado")
        tk.Label(left,textvariable=self.name,bg="#1a2436",fg="#f7f9fd",font=("Segoe UI",16,"bold"),
                 wraplength=590,justify="left").pack(fill="x",anchor="w",padx=20,pady=(22,12))
        self.listbox=tk.Listbox(left,bg="#223148",fg="#dce8fb",selectbackground="#526689",
                                bd=0,highlightthickness=0,font=("Segoe UI",11))
        self.listbox.pack(fill="both",expand=True,padx=20,pady=(0,16))
        self.listbox.bind("<<ListboxSelect>>",self.scene_select)
        self.text(left,"2. GERE O VIDEO COMPLETO",size=15,color="#ffbd43",bold=True).pack(anchor="w",padx=20,pady=(2,9))
        self.generate_button=self.btn(left,"GERAR VIDEO TIKTOK - 90 SEGUNDOS",self.generate,accent=True)
        self.generate_button.pack(fill="x",padx=20,pady=(0,18))
        self.text(right,"PREVIA DA CENA",size=15,color="#ffbd43",bold=True).pack(anchor="w",padx=18,pady=(20,10))
        self.thumbnail=tk.Label(right,bg="#111827",fg="#fff",text="Importe um episodio\ne selecione uma cena",
                                width=30,height=18)
        self.thumbnail.pack(padx=18,pady=(0,14),fill="x")
        self.scene_details=tk.StringVar(value="Formato: 1080 x 1920\nDuração: exatamente 90s\nVoz neural brasileira\nSincronia labial por imagens do pacote\nAnimacoes 3D Wan 2.2\nExportacao MP4 H.264")
        tk.Label(right,textvariable=self.scene_details,bg="#1a2436",fg="#c9d7ec",
                 font=("Segoe UI",10),justify="left",wraplength=310).pack(fill="x",padx=18,pady=(2,12))
        self.btn(right,"ABRIR PASTA DOS VIDEOS",self.open_output).pack(anchor="w",padx=18,pady=(12,8))
        line=tk.Frame(self,bg="#111827");line.pack(fill="x",padx=24,pady=(12,0))
        self.status=tk.StringVar(value="Pronto. Importe um pacote de 90 segundos.")
        tk.Label(line,textvariable=self.status,bg="#111827",fg="#ffcc69",
                 font=("Segoe UI",11),anchor="w",justify="left",
                 wraplength=1010).pack(fill="x")
        self.progress=ttk.Progressbar(self,mode="indeterminate")
        self.progress.pack(fill="x",padx=24,pady=8)
        self.logview=tk.Text(self,height=5,bg="#0a111d",fg="#c9d7ea",font=("Consolas",9),
                             bd=0,highlightthickness=0,state="disabled")
        self.logview.pack(fill="x",padx=24,pady=(0,16))

    def send(self,message):
        base.logline(str(message))
        self.events.put(("log",str(message)))

    def drain(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=="log":
                    self.status.set(payload)
                    self.logview.config(state="normal")
                    self.logview.insert("end",payload+"\n")
                    self.logview.see("end")
                    self.logview.config(state="disabled")
                elif kind=="ready":
                    self.current=payload
                    self.name.set(payload["titulo"])
                    self.listbox.delete(0,"end")
                    for i,s in enumerate(payload["cenas"],1):
                        self.listbox.insert("end",f"{i:02d}   {s.get('nome','Cena')}  ·  {s.get('personagem','Narrador')}  ·  {float(s['duracao']):g}s")
                    self.listbox.selection_set(0)
                    self.show_scene(0)
                    self.send(f"Projeto validado: {len(payload['cenas'])} cenas / 90 segundos. Um clique para gerar.")
                elif kind=="error":
                    self.busy=False
                    self.progress.stop()
                    self.generate_button.config(state="normal")
                    messagebox.showerror("Producao nao concluida",str(payload))
                elif kind=="finish":
                    self.busy=False
                    self.progress.stop()
                    self.generate_button.config(state="normal")
                    messagebox.showinfo("VIDEO COMPLETO","MP4 salvo:\n"+str(payload))
                    self.open_output()
                elif kind=="update":
                    self.pending_update=payload
                    if not self.busy:
                        self.apply_update()
        except queue.Empty:
            pass
        self.after(160,self.drain)

    def load_last(self):
        try:
            if STATE.is_file():
                data=json.loads(STATE.read_text(encoding="utf-8"))
                root=Path(data["root"])
                if root.is_dir():
                    project=ep._project_from_root(root)
                    self.events.put(("ready",project))
        except Exception as e:
            self.send("Ultimo projeto nao foi recuperado: "+str(e))

    def import_dialog(self):
        file=filedialog.askopenfilename(title="Selecione seu pacote de roteiro e imagens",
                                        filetypes=[("Pacote do Frutaverso","*.zip")])
        if not file:return
        self.send("Conferindo imagens e duracao do roteiro...")
        def work():
            try:
                project=ep.import_pack(Path(file),PACKS)
                STATE.parent.mkdir(parents=True,exist_ok=True)
                STATE.write_text(json.dumps({"root":str(project["_root"])},ensure_ascii=False),encoding="utf-8")
                self.events.put(("ready",project))
            except Exception as e:self.events.put(("error",str(e)))
        threading.Thread(target=work,daemon=True).start()

    def scene_select(self,_event=None):
        if not self.current:return
        sel=self.listbox.curselection()
        if sel:self.show_scene(sel[0])

    def show_scene(self,idx):
        scene=self.current["cenas"][idx]
        try:
            with Image.open(scene["_imagem"]) as im:
                im=ImageOps.contain(im.convert("RGB"),(300,400))
            self.preview=ImageTk.PhotoImage(im)
            self.thumbnail.config(image=self.preview,text="",height=400,width=300)
        except Exception as e:
            self.thumbnail.config(image="",text=str(e))
        self.scene_details.set(
            f"{scene.get('nome','Cena')}\n\nTipo: {scene['tipo']}\n"+
            f"Personagem: {scene.get('personagem','Narrador')}\n"+
            f"Duração: {scene['duracao']}s\n\n"+
            (scene.get("fala","")[:240] or "Cena visual sem fala")+
            "\n\nSaida: 1080×1920, 24 fps, MP4"
        )

    def generate(self):
        if self.busy:return
        if not self.current:
            messagebox.showwarning("Falta o pacote","Importe um ZIP contendo roteiro.json e imagens.")
            return
        self.busy=True
        self.generate_button.config(state="disabled")
        self.progress.start(10)
        project=self.current
        self.send("Iniciando producao automatica de 90 segundos...")
        def work():
            try:
                path=ep.render(project,self.send)
                self.events.put(("finish",path))
            except Exception as e:
                base.logline(traceback.format_exc())
                self.events.put(("error",str(e)))
        threading.Thread(target=work,daemon=True).start()

    def open_output(self):
        base.OUTPUT.mkdir(parents=True,exist_ok=True)
        if os.name=="nt":os.startfile(str(base.OUTPUT))
        else:messagebox.showinfo("Videos",str(base.OUTPUT))

    def check_async(self):
        if base.RUNNING:threading.Thread(target=self.check_updates,daemon=True).start()

    def check_updates(self):
        try:
            found=base.download_update(self.send)
            if found:self.events.put(("update",found))
        except Exception as e:self.send("Nao foi possivel checar atualizacao: "+str(e)[:150])

    def apply_update(self):
        if not self.pending_update or self.busy:return
        update,version=self.pending_update
        self.send("Atualizacao "+version+" instalada automaticamente ao reiniciar.")
        try:
            base.proc([str(update),"--apply-update",str(base.APP_DIR/"FrutaversoStudio.exe")])
            self.destroy()
        except Exception as e:self.send("Falha ao aplicar atualizacao: "+str(e))

def main():
    if len(sys.argv)>1 and sys.argv[1]=="--apply-update":
        base.applied_update(sys.argv[2])
        return
    base.bootstrap()
    for folder in (base.APP_HOME,base.APP_DIR,base.DATA,base.OUTPUT,base.CACHE,PACKS):
        folder.mkdir(parents=True,exist_ok=True)
    Studio90().mainloop()

if __name__=="__main__":
    try:main()
    except Exception as e:
        base.logline(traceback.format_exc())
        if os.name=="nt":
            base.ctypes.windll.user32.MessageBoxW(None,str(e),"Frutaverso Studio",0x10)
        else:raise
