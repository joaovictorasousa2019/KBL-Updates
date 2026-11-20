# -*- coding: utf-8 -*-
"""Frutaverso Studio: aplicativo Windows com atualizacao automatica e Wan 2.2 local."""
from __future__ import annotations
import ctypes
import datetime
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import wave
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

VERSION = "0.4.0"
REPO = "joaovictorasousa2019/KBL-Updates"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=60"
APP_HOME = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FrutaversoStudio"
APP_DIR = APP_HOME / "app"
DATA = APP_HOME / "dados"
ASSETS = DATA / "assets"
OUTPUT = DATA / "saida"
CACHE = DATA / "cache"
PROJECT_FILE = DATA / "episodio.json"
RUNNING = getattr(sys, "frozen", False)
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
if os.name == "nt":
    _si = subprocess.STARTUPINFO()
    _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _si.wShowWindow = 0
    HIDDEN["startupinfo"] = _si

PILOT = {
 "titulo": "A banana humilhou a laranja errada!",
 "cenas": [
  {"nome":"Chegada","personagem":"Narrador","fala":"Na academia mais braba do Frutaverso, chegou um novato!","imagem":"assets/01_laranja.jpg","duracao":6,"prompt":"Cinematic 3D muscular anthropomorphic orange in a dark gym slowly walks forward, clenches his fists, intimidating confident facial expression. Fixed camera. Keep exact appearance."},
  {"nome":"Provocacao","personagem":"Banana","fala":"Ahahaha! Olha o suquinho que chegou! Vai treinar aqui com esse tamaninho?","imagem":"assets/02_banana.jpg","duracao":7,"prompt":"Cinematic 3D muscular anthropomorphic banana wearing sunglasses laughs and points at the orange in a prison gym. Natural character motion, expressive face, fixed camera."},
  {"nome":"Resposta","personagem":"Laranja","fala":"Continua rindo, banana. Porque logo voce vai chorar!","imagem":"assets/03_confronto.jpg","duracao":7,"prompt":"Cinematic 3D anthropomorphic orange confidently challenges muscular banana in a prison gym, subtle natural facial movements and hand gestures, fixed camera, exact character identity."}
 ]
}

def logline(msg):
    APP_HOME.mkdir(parents=True,exist_ok=True)
    with (APP_HOME/"frutaverso.log").open("a",encoding="utf-8") as f:
        f.write(datetime.datetime.now().isoformat(timespec="seconds")+" "+str(msg)+"\n")

def proc(argv, **kwargs):
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **HIDDEN, **kwargs)

def fetch_json(url, timeout=15):
    req=urllib.request.Request(url,headers={"User-Agent":"FrutaversoStudio/"+VERSION,"Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return json.load(r)

def parse_ver(s):
    try:return tuple(int(x) for x in s.strip().lstrip("v").split(".")[:3])
    except Exception:return (0,0,0)

def latest_release():
    items=fetch_json(RELEASES_API)
    matches=[]
    for rel in items:
        tag=rel.get("tag_name","")
        if not tag.startswith("frutaverso-v") or rel.get("draft") or rel.get("prerelease"):continue
        version=tag.partition("frutaverso-v")[2]
        assets=rel.get("assets",[])
        exe=next((a for a in assets if a.get("name")=="FrutaversoStudio.exe"),None)
        sha=next((a for a in assets if a.get("name")=="FrutaversoStudio.exe.sha256"),None)
        if exe and sha:matches.append((parse_ver(version),version,exe["browser_download_url"],sha["browser_download_url"]))
    return max(matches,key=lambda row:row[0]) if matches else None

def download_update(callback):
    rel=latest_release()
    if not rel or rel[0]<=parse_ver(VERSION):return None
    _,version,url,checksum_url=rel
    expected_prefix=f"https://github.com/{REPO}/releases/download/frutaverso-v"
    if not url.startswith(expected_prefix) or not url.endswith("/FrutaversoStudio.exe"):
        raise RuntimeError("URL de atualizacao nao reconhecida.")
    expected=urllib.request.urlopen(urllib.request.Request(checksum_url,headers={"User-Agent":"FrutaversoStudio"}),timeout=25).read(300).decode().strip().split()[0].lower()
    if len(expected)!=64 or any(c not in "0123456789abcdef" for c in expected):
        raise RuntimeError("Checksum da nova versao invalido.")
    folder=APP_HOME/"updates"/version;folder.mkdir(parents=True,exist_ok=True)
    filename=folder/"FrutaversoStudio.exe"
    if filename.is_file() and hashlib.sha256(filename.read_bytes()).hexdigest()==expected:
        return filename,version
    tmp=filename.with_suffix(".part")
    h=hashlib.sha256()
    req=urllib.request.Request(url,headers={"User-Agent":"FrutaversoStudio"})
    with urllib.request.urlopen(req,timeout=90) as resp, tmp.open("wb") as f:
        while True:
            chunk=resp.read(1024*1024)
            if not chunk:break
            h.update(chunk);f.write(chunk)
    if h.hexdigest()!=expected:
        tmp.unlink(missing_ok=True);raise RuntimeError("SHA-256 nao corresponde; atualizacao cancelada.")
    os.replace(tmp,filename);callback("Atualizacao "+version+" baixada e verificada.")
    return filename,version

def applied_update(target):
    """Executado pelo EXE novo enquanto o EXE antigo fecha, sem janela CMD."""
    source=Path(sys.executable).resolve()
    target=Path(target).resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    for _ in range(150):
        try:
            shutil.copy2(source,target)
            proc([str(target),"--updated"])
            return
        except (PermissionError,OSError):
            time.sleep(.5)
    logline("ERRO: nao foi possivel substituir a versao instalada.")

def shortcut():
    """Atalho Windows criado silenciosamente na instalacao inicial."""
    if os.name!="nt":return
    target=APP_DIR/"FrutaversoStudio.exe"
    desktop=Path.home()/"Desktop"
    if not desktop.exists():
        desktop=Path(os.environ.get("USERPROFILE",str(Path.home())))/"Desktop"
    if not desktop.exists():return
    lnk=desktop/"Frutaverso Studio.lnk"
    if lnk.exists():return
    esc=lambda s:str(s).replace("'","''")
    code=("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('"+esc(lnk)+"');"+
          "$s.TargetPath='"+esc(target)+"';"+
          "$s.WorkingDirectory='"+esc(APP_DIR)+"';"+
          "$s.Description='Frutaverso Studio';$s.Save()")
    subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",code],
                   timeout=20,**HIDDEN)

def bootstrap():
    if not RUNNING or os.name!="nt":return
    target=APP_DIR/"FrutaversoStudio.exe"
    me=Path(sys.executable).resolve()
    if me==target.resolve():return
    if len(sys.argv)>1 and sys.argv[1]=="--apply-update":
        applied_update(sys.argv[2]);sys.exit(0)
    APP_DIR.mkdir(parents=True,exist_ok=True)
    try:
        if not target.is_file():
            shutil.copy2(me,target)
        elif parse_ver(VERSION)>parse_ver((APP_DIR/"installed-version.txt").read_text().strip() if (APP_DIR/"installed-version.txt").exists() else "0.0.0"):
            proc([str(me),"--apply-update",str(target)])
            sys.exit(0)
        (APP_DIR/"installed-version.txt").write_text(VERSION,encoding="utf-8")
        shortcut()
        proc([str(target),"--installed"])
        sys.exit(0)
    except PermissionError as exc:
        logline("Falha na instalacao: "+str(exc))
        raise

def import_old_images():
    if all((ASSETS/f"{i:02d}_{name}.jpg").exists() for i,name in [(1,"laranja"),(2,"banana"),(3,"confronto")]):return
    home=Path.home()
    bases=[home/"Downloads",home/"Desktop",home/"Documents",home/"OneDrive"/"Desktop"]
    names=("Frutaverso_Studio_Automatico_v0_3","Frutaverso_Studio_Automatico_v0_2","Frutaverso_Studio_Gratis")
    for base in bases:
        if not base.exists():continue
        candidates=[base/name for name in names]
        candidates += [sub/name for sub in list(base.iterdir())[:50] if sub.is_dir() for name in names]
        for folder in candidates:
            old=folder/"assets"
            if not old.is_dir():continue
            for name in ("01_laranja.jpg","02_banana.jpg","03_confronto.jpg"):
                src=old/name;dest=ASSETS/name
                if src.exists() and not dest.exists():shutil.copy2(src,dest)
            if (ASSETS/"01_laranja.jpg").exists():return

def generate_placeholder(path,kind):
    """Reserva de demonstracao caso o pacote antigo nao seja localizado."""
    colors={"laranja":(235,103,22),"banana":(245,204,25),"confronto":(155,77,30)}
    c=colors[kind];im=Image.new("RGB",(720,1280),(19,30,44));d=ImageDraw.Draw(im)
    for i in range(45):
        d.rectangle((0,i*29,720,i*29+15),fill=(22+i//6,35+i//7,52+i//8))
    d.ellipse((155,280,565,695),fill=c,outline=(250,205,120),width=8)
    d.ellipse((242,400,290,445),fill="white");d.ellipse((420,400,470,445),fill="white")
    d.ellipse((264,414,284,441),fill="black");d.ellipse((437,414,458,441),fill="black")
    d.arc((275,460,460,575),0,180,fill=(64,39,27),width=12)
    d.ellipse((125,690,600,1150),fill=(65,70,75))
    im.save(path,quality=92)

def setup_data():
    for folder in (APP_HOME,APP_DIR,DATA,ASSETS,OUTPUT,CACHE):folder.mkdir(parents=True,exist_ok=True)
    import_old_images()
    for file,kind in (("01_laranja.jpg","laranja"),("02_banana.jpg","banana"),("03_confronto.jpg","confronto")):
        if not (ASSETS/file).exists():generate_placeholder(ASSETS/file,kind)
    if not PROJECT_FILE.exists():PROJECT_FILE.write_text(json.dumps(PILOT,ensure_ascii=False,indent=2),encoding="utf-8")

def wf_template(image,prompt,frames=33):
    return {
     "37":{"class_type":"UNETLoader","inputs":{"unet_name":"wan2.2_ti2v_5B_fp16.safetensors","weight_dtype":"default"}},
     "38":{"class_type":"CLIPLoader","inputs":{"clip_name":"umt5_xxl_fp8_e4m3fn_scaled.safetensors","type":"wan","device":"default"}},
     "39":{"class_type":"VAELoader","inputs":{"vae_name":"wan2.2_vae.safetensors"}},
     "48":{"class_type":"ModelSamplingSD3","inputs":{"model":["37",0],"shift":8}},
     "6":{"class_type":"CLIPTextEncode","inputs":{"clip":["38",0],"text":prompt}},
     "7":{"class_type":"CLIPTextEncode","inputs":{"clip":["38",0],"text":"blurry, static, distorted face, extra fingers, extra limbs, subtitles, watermark, camera motion, deformed character"}},
     "56":{"class_type":"LoadImage","inputs":{"image":image}},
     "55":{"class_type":"Wan22ImageToVideoLatent","inputs":{"vae":["39",0],"start_image":["56",0],"width":384,"height":640,"length":frames,"batch_size":1}},
     "3":{"class_type":"KSampler","inputs":{"model":["48",0],"positive":["6",0],"negative":["7",0],"latent_image":["55",0],
            "seed":int(time.time_ns())%(2**48),"steps":20,"cfg":5,"sampler_name":"uni_pc","scheduler":"simple","denoise":1}},
     "8":{"class_type":"VAEDecode","inputs":{"samples":["3",0],"vae":["39",0]}},
     "57":{"class_type":"CreateVideo","inputs":{"images":["8",0],"fps":16,"codec":"none","color_space":"sRGB","bit_depth":"auto"}},
     "58":{"class_type":"SaveVideo","inputs":{"video":["57",0],"filename_prefix":"frutaverso/gerado","format":"auto","format.codec":"auto"}}
    }

def request(base,endpoint,data=None,ctype="application/json",timeout=30):
    raw=json.dumps(data).encode("utf-8") if isinstance(data,dict) else data
    hdr={"Content-Type":ctype} if raw is not None else {}
    with urllib.request.urlopen(urllib.request.Request(base+endpoint,data=raw,headers=hdr),timeout=timeout) as r:return r.read()

def server():
    ports=[8000,8188,8189,8190,8187,8191]
    for port in ports:
        url=f"http://127.0.0.1:{port}"
        try:
            data=json.loads(request(url,"/system_stats",timeout=1))
            if "devices" in data or "system" in data:return url
        except Exception:pass
    return None

def start_comfy():
    if os.name!="nt":return False
    local=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))
    programs=Path(os.environ.get("PROGRAMFILES","C:/Program Files"))
    opts=[local/"Programs"/"ComfyUI"/"ComfyUI.exe",local/"ComfyUI"/"ComfyUI.exe",programs/"ComfyUI"/"ComfyUI.exe"]
    for opt in opts:
        if opt.is_file():
            proc([str(opt)],cwd=str(opt.parent));return True
    return False

def get_server(status):
    base=server()
    if base:return base
    status("Iniciando motor ComfyUI local...")
    if not start_comfy():raise RuntimeError("ComfyUI Desktop nao encontrado. Mantenha a instalacao atual do ComfyUI.")
    for _ in range(75):
        base=server()
        if base:return base
        time.sleep(2)
    raise RuntimeError("ComfyUI abriu mas a API local nao respondeu. Verifique a instalacao do Wan 2.2.")

def upload_image(base,img):
    boundary="----Fruta"+uuid.uuid4().hex
    mimetype="image/jpeg" if img.suffix.lower() in (".jpg",".jpeg") else "image/png"
    pre=f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{img.name}"\r\nContent-Type: {mimetype}\r\n\r\n'.encode()
    raw=pre+img.read_bytes()+f"\r\n--{boundary}--\r\n".encode()
    return json.loads(request(base,"/upload/image",raw,f"multipart/form-data; boundary={boundary}",timeout=120))["name"]

def animate(base,scene,idx,status):
    img=resolve_image(scene)
    key=hashlib.sha256(img.read_bytes()+scene.get("prompt","").encode()+b"33-384-640").hexdigest()[:24]
    cached=CACHE/(key+".mp4")
    if cached.is_file() and cached.stat().st_size>1000:return cached
    status(f"Cena {idx}: enviando imagem ao Wan 2.2...")
    uploaded=upload_image(base,img)
    wf=wf_template(uploaded,scene.get("prompt","3D fruit character animation"))
    try:
        r=json.loads(request(base,"/prompt",{"prompt":wf,"client_id":uuid.uuid4().hex},timeout=60))
    except urllib.error.HTTPError as e:
        raise RuntimeError("O ComfyUI rejeitou a cena: "+e.read().decode("utf-8","replace")[-900:])
    if not r.get("prompt_id"):raise RuntimeError("Resposta inesperada do ComfyUI: "+str(r)[:400])
    job=r["prompt_id"];started=time.monotonic();last=-1
    while time.monotonic()-started<5400:
        h=json.loads(request(base,"/history/"+job,timeout=25))
        if job in h:
            item=h[job]
            if item.get("status",{}).get("status_str")=="error":
                raise RuntimeError("Falha no Wan: "+str(item.get("status",{}).get("messages",[]))[-1200:])
            for output in item.get("outputs",{}).values():
                for typ in ("videos","images","gifs"):
                    for f in output.get(typ,[]):
                        name=f.get("filename","")
                        if name.lower().endswith((".mp4",".webm",".mov")):
                            qs=urllib.parse.urlencode({"filename":name,"subfolder":f.get("subfolder",""),"type":f.get("type","output")})
                            cached.write_bytes(request(base,"/view?"+qs,timeout=300))
                            return cached
            raise RuntimeError("ComfyUI concluiu, mas nao retornou video. Confira o SaveVideo.")
        elapsed=int(time.monotonic()-started)
        if elapsed//30!=last:
            last=elapsed//30
            status(f"Cena {idx}: Wan gerando... {elapsed}s")
        time.sleep(4)
    raise TimeoutError("Tempo de geracao excedido.")

def resolve_image(scene):
    value=Path(scene.get("imagem",""))
    if value.is_absolute():path=value
    else:path=DATA/value
    if not path.is_file():raise FileNotFoundError("Imagem nao encontrada: "+str(path))
    return path

def voice(text,out,status):
    """SAPI do Windows, sem servicos pagos ou janelas de terminal."""
    if not text.strip():return None
    inp=out.with_suffix(".txt")
    script=out.with_suffix(".ps1")
    inp.write_text(text,encoding="utf-8")
    esc=lambda x:str(x).replace("'","''")
    ps=(r"Add-Type -AssemblyName System.Speech;" +
        r"$v=New-Object System.Speech.Synthesis.SpeechSynthesizer;" +
        r"$pt=$v.GetInstalledVoices()|Where-Object {$_.VoiceInfo.Culture.Name -eq 'pt-BR'}|Select-Object -First 1;" +
        r"if($pt){$v.SelectVoice($pt.VoiceInfo.Name)};" +
        "$v.SetOutputToWaveFile('"+esc(out)+"');" +
        "$v.Speak([System.IO.File]::ReadAllText('"+esc(inp)+"',[System.Text.Encoding]::UTF8));" +
        "$v.Dispose()")
    script.write_text(ps,encoding="utf-8-sig")
    p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(script)],
                     capture_output=True,text=True,timeout=120,**HIDDEN)
    if p.returncode or not out.exists():raise RuntimeError("Falha ao gerar voz local: "+p.stderr[-400:])
    status("Voz local criada.")
    return out

def length_wav(p):
    if not p:return 0
    with wave.open(str(p),"rb") as w:return w.getnframes()/w.getframerate()

def font(size):
    for path in ("C:/Windows/Fonts/arialbd.ttf","C:/Windows/Fonts/segoeuib.ttf"):
        if Path(path).exists():return ImageFont.truetype(path,size)
    return ImageFont.load_default()

def overlay(text,speaker,path):
    w,h=720,1280
    im=Image.new("RGBA",(w,h));d=ImageDraw.Draw(im)
    f=font(42);fs=font(25)
    words=text.split();lines=[];line=""
    for word in words:
        candidate=(line+" "+word).strip()
        if line and d.textbbox((0,0),candidate,font=f)[2]>w-90:
            lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    lines=lines[:4] if lines else [""]
    y=940-len(lines)*54
    d.rounded_rectangle((28,y-55,w-28,1040),radius=22,fill=(5,10,19,205),outline=(247,192,44),width=3)
    d.text((w//2,y-38),speaker.upper(),font=fs,anchor="mt",fill=(249,195,58))
    for i,line in enumerate(lines):
        d.text((w//2,y+12+i*54),line,font=f,anchor="mt",fill="white",stroke_width=2,stroke_fill="black")
    im.save(path)

def ffmpeg_run(args):
    p=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-hide_banner","-y","-loglevel","error"]+args,
                     capture_output=True,text=True,timeout=7200,**HIDDEN)
    if p.returncode:raise RuntimeError("FFmpeg: "+p.stderr[-1400:])

def compose(project,clips,status):
    """Monta videos completos com legenda e audio por cena."""
    stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    final=OUTPUT/("Frutaverso_Episodio_"+stamp+".mp4")
    with tempfile.TemporaryDirectory(prefix="frutaverso_") as temp:
        tmp=Path(temp);pieces=[]
        for idx,scene in enumerate(project["cenas"],1):
            raw=clips[idx-1];text=scene.get("fala","")
            wav=voice(text,tmp/f"voz{idx}.wav",status) if text else None
            duration=max(float(scene.get("duracao",6)), length_wav(wav)+.5)
            poster=tmp/f"legenda{idx}.png"
            overlay(text,scene.get("personagem","Narrador"),poster)
            outfile=tmp/f"cena{idx:03d}.mp4";pieces.append(outfile)
            ffmpeg_run(["-stream_loop","-1","-i",str(raw),
                        "-loop","1","-i",str(poster)] +
                        (["-i",str(wav)] if wav else ["-f","lavfi","-i","anullsrc=r=44100:cl=stereo"]) +
                        ["-filter_complex","[0:v]fps=24,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280[base];[base][1:v]overlay=0:0:shortest=1[v]",
                         "-map","[v]","-map","2:a","-t",str(duration),"-r","24",
                         "-c:v","libx264","-preset","veryfast","-crf","23","-pix_fmt","yuv420p",
                         "-c:a","aac","-b:a","128k","-movflags","+faststart",str(outfile)])
            status(f"Cena {idx}/{len(clips)} montada.")
        txt=tmp/"lista.txt"
        txt.write_text("\n".join("file '"+str(p).replace("\\","/")+"'" for p in pieces),encoding="utf-8")
        ffmpeg_run(["-f","concat","-safe","0","-i",str(txt),"-c","copy","-movflags","+faststart",str(final)])
    return final

class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FRUTAVERSO STUDIO  |  Atualizacao automatica")
        self.geometry("1020x740");self.minsize(850,650);self.configure(bg="#111927")
        self.jobs=queue.Queue();self.busy=False;self.pending_update=None
        self.project=json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
        self.index=0
        self.make_ui();self.select_scene(0)
        self.after(200,self.poll)
        if RUNNING:threading.Thread(target=self.check_update,daemon=True).start()

    def label(self,parent,text,color="#edf2f8",size=10,bold=False):
        return tk.Label(parent,text=text,bg=parent["bg"],fg=color,
                        font=("Segoe UI",size,"bold" if bold else "normal"))
    def button(self,parent,text,fn):
        return tk.Button(parent,text=text,command=fn,bg="#25354e",fg="#ffffff",padx=10,pady=8,bd=0,activebackground="#334862")
    def make_ui(self):
        title=tk.Frame(self,bg="#111927");title.pack(fill="x",padx=18,pady=13)
        self.label(title,"FRUTAVERSO STUDIO",color="#f4c04d",size=22,bold=True).pack(side="left")
        self.label(title,"v"+VERSION+"   •  sem CMD",color="#b7c5d8").pack(side="left",padx=12)
        self.button(title,"Verificar atualizacao",self.check_update_async).pack(side="right")
        top=tk.Frame(self,bg="#111927");top.pack(fill="x",padx=18)
        self.label(top,"Titulo:").pack(side="left")
        self.title_value=tk.StringVar(value=self.project.get("titulo",""))
        tk.Entry(top,textvariable=self.title_value,bg="#25354e",fg="white",insertbackground="white",bd=0,font=("Segoe UI",11)).pack(side="left",fill="x",expand=True,padx=12,ipady=8)
        self.button(top,"Salvar",self.save).pack(side="left",padx=4)
        split=tk.PanedWindow(self,orient="horizontal",bg="#111927",sashwidth=8,bd=0)
        split.pack(fill="both",expand=True,padx=18,pady=13)
        left=tk.Frame(split,bg="#192338");right=tk.Frame(split,bg="#192338")
        split.add(left,width=330,minsize=250);split.add(right,minsize=450)
        self.label(left,"CENAS",color="#f4c04d",size=12,bold=True).pack(anchor="w",padx=14,pady=12)
        self.listbox=tk.Listbox(left,bg="#213047",fg="white",selectbackground="#405778",bd=0,font=("Segoe UI",11))
        self.listbox.pack(fill="both",expand=True,padx=12,pady=5)
        self.listbox.bind("<<ListboxSelect>>",self.change_scene)
        for scene in self.project["cenas"]:self.listbox.insert("end",scene["nome"])
        tools=tk.Frame(left,bg="#192338");tools.pack(fill="x",padx=12,pady=12)
        self.button(tools,"+ Cena",self.add_scene).pack(side="left")
        self.button(tools,"Excluir",self.remove_scene).pack(side="left",padx=5)
        self.label(right,"EDITAR CENA",color="#f4c04d",size=12,bold=True).pack(anchor="w",padx=14,pady=12)
        form=tk.Frame(right,bg="#192338");form.pack(fill="both",expand=True,padx=14)
        self.name=tk.StringVar();self.speaker=tk.StringVar();self.duration=tk.StringVar();self.picture=tk.StringVar()
        def field(label,var):
            self.label(form,label,color="#b9c6dc").pack(anchor="w",pady=(8,3))
            tk.Entry(form,textvariable=var,bg="#25354e",fg="white",insertbackground="white",bd=0).pack(fill="x",ipady=6)
        field("Nome",self.name);field("Personagem",self.speaker);field("Duracao em segundos",self.duration)
        self.label(form,"Fala (voz automatica)",color="#b9c6dc").pack(anchor="w",pady=(9,2))
        self.speech=tk.Text(form,height=3,bg="#25354e",fg="white",insertbackground="white",bd=0,wrap="word");self.speech.pack(fill="x")
        self.label(form,"Movimento (prompt Wan 2.2)",color="#b9c6dc").pack(anchor="w",pady=(9,2))
        self.motion=tk.Text(form,height=5,bg="#25354e",fg="white",insertbackground="white",bd=0,wrap="word");self.motion.pack(fill="both",expand=True)
        self.label(form,"Imagem da cena:",color="#b9c6dc").pack(anchor="w",pady=(9,2))
        imagebar=tk.Frame(form,bg="#192338");imagebar.pack(fill="x")
        self.image_label=self.label(imagebar,"");self.image_label.pack(side="left",fill="x",expand=True)
        self.button(imagebar,"Escolher imagem",self.choose_image).pack(side="right")
        bottom=tk.Frame(self,bg="#111927");bottom.pack(fill="x",padx=18,pady=(0,10))
        self.button(bottom,"GERAR EPISODIO COMPLETO COM IA",self.generate).pack(side="left")
        self.button(bottom,"Abrir videos",lambda:os.startfile(str(OUTPUT)) if os.name=="nt" else None).pack(side="left",padx=8)
        self.status=tk.StringVar(value="Pronto para produzir. Os modelos Wan permanecem no ComfyUI instalado.")
        self.label(bottom,"",color="#c4d5e4").pack(side="left")
        tk.Label(self,textvariable=self.status,fg="#f4c04d",bg="#111927",wraplength=310,justify="left").pack(anchor="w",padx=18)
        self.progress=ttk.Progressbar(self,mode="indeterminate");self.progress.pack(fill="x",padx=18,pady=8)
        self.logs=tk.Text(self,height=6,bg="#0a121d",fg="#d7e4f4",font=("Consolas",9),state="disabled")
        self.logs.pack(fill="x",padx=18,pady=(2,12))

    def inform(self,msg):
        logline(msg);self.jobs.put(("log",str(msg)))
    def poll(self):
        try:
            while True:
                kind,data=self.jobs.get_nowait()
                if kind=="log":
                    self.status.set(data[:135])
                    self.logs.config(state="normal");self.logs.insert("end",data+"\n");self.logs.see("end");self.logs.config(state="disabled")
                elif kind=="done":
                    self.busy=False;self.progress.stop();messagebox.showinfo("Pronto","Episodio gerado:\n"+str(data));os.startfile(str(OUTPUT))
                elif kind=="fail":
                    self.busy=False;self.progress.stop();messagebox.showerror("Erro",str(data))
                elif kind=="update":
                    self.pending_update=data
                    if not self.busy:self.install_update()
        except queue.Empty:pass
        self.after(150,self.poll)
    def select_scene(self,i):
        self.index=i
        s=self.project["cenas"][i]
        self.listbox.selection_clear(0,"end");self.listbox.selection_set(i);self.listbox.activate(i)
        self.name.set(s.get("nome",""));self.speaker.set(s.get("personagem","Narrador"))
        self.duration.set(str(s.get("duracao",6)))
        self.picture.set(s.get("imagem",""))
        self.speech.delete("1.0","end");self.speech.insert("1.0",s.get("fala",""))
        self.motion.delete("1.0","end");self.motion.insert("1.0",s.get("prompt",""))
        self.image_label.config(text=Path(self.picture.get()).name)
    def remember_scene(self):
        s=self.project["cenas"][self.index]
        s.update(nome=self.name.get(),personagem=self.speaker.get(),
                 fala=self.speech.get("1.0","end-1c").strip(),prompt=self.motion.get("1.0","end-1c").strip(),
                 imagem=self.picture.get())
        try:s["duracao"]=max(1,float(self.duration.get().replace(",",".")))
        except ValueError:s["duracao"]=6
        self.project["titulo"]=self.title_value.get()
    def change_scene(self,_event=None):
        selection=self.listbox.curselection()
        if not selection:return
        j=selection[0]
        if j==self.index:return
        self.remember_scene();self.select_scene(j)
    def add_scene(self):
        self.remember_scene()
        self.project["cenas"].append({"nome":f"Cena {len(self.project['cenas'])+1}","personagem":"Narrador","fala":"",
                 "imagem":"assets/01_laranja.jpg","prompt":"Cinematic 3D fruit character animation, fixed camera, natural body movements.","duracao":6})
        self.listbox.insert("end",self.project["cenas"][-1]["nome"])
        self.select_scene(len(self.project["cenas"])-1)
    def remove_scene(self):
        if len(self.project["cenas"])<=1:return
        j=self.index;self.project["cenas"].pop(j);self.listbox.delete(j)
        self.select_scene(min(j,len(self.project["cenas"])-1))
    def choose_image(self):
        p=filedialog.askopenfilename(filetypes=[("Imagens","*.jpg *.jpeg *.png *.webp")])
        if p:
            self.picture.set(p);self.image_label.config(text=Path(p).name)
            self.remember_scene()
    def save(self):
        self.remember_scene()
        PROJECT_FILE.write_text(json.dumps(self.project,ensure_ascii=False,indent=2),encoding="utf-8")
        self.inform("Projeto salvo.")
    def generate(self):
        if self.busy:return
        self.save();self.busy=True;self.progress.start(9)
        project=json.loads(json.dumps(self.project))
        def worker():
            try:
                base=get_server(self.inform)
                clips=[]
                for i,scene in enumerate(project["cenas"],1):
                    clips.append(animate(base,scene,i,self.inform))
                self.inform("Animacoes concluidas. Montando vozes, legendas e MP4...")
                result=compose(project,clips,self.inform)
                self.jobs.put(("done",result))
            except Exception as exc:
                import traceback
                logline(traceback.format_exc())
                self.jobs.put(("fail",str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def check_update_async(self):
        threading.Thread(target=self.check_update,daemon=True).start()
    def check_update(self):
        if not RUNNING:return
        try:
            found=download_update(self.inform)
            if found:self.jobs.put(("update",found))
        except Exception as exc:self.inform("Atualizacao nao verificada: "+str(exc)[:160])
    def install_update(self):
        if self.busy:return
        file,version=self.pending_update
        self.inform("Atualizando para "+version+"; reabrindo automaticamente...")
        self.save()
        try:
            proc([str(file),"--apply-update",str(APP_DIR/"FrutaversoStudio.exe")])
            self.destroy()
        except Exception as exc:self.inform("Falha ao iniciar atualizacao: "+str(exc))

def main():
    if len(sys.argv)>1 and sys.argv[1]=="--apply-update":
        applied_update(sys.argv[2]);return
    bootstrap()
    setup_data()
    Studio().mainloop()

if __name__=="__main__":
    try:main()
    except Exception as exc:
        logline("FALHA: "+repr(exc))
        if os.name=="nt":
            ctypes.windll.user32.MessageBoxW(None,str(exc),"Frutaverso Studio",0x10)
        else:raise
