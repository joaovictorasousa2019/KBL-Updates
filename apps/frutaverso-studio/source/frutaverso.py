# -*- coding: utf-8 -*-
"""Frutaverso Studio: aplicativo Windows com atualizacao automatica e Wan 2.2 local."""
from __future__ import annotations
import ctypes
import concurrent.futures
import re
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
import psutil
import socket

VERSION = "0.4.2"
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
    opts=dict(HIDDEN)
    opts.update({"stdin":subprocess.DEVNULL,"stdout":subprocess.DEVNULL,"stderr":subprocess.DEVNULL})
    opts.update(kwargs)
    return subprocess.Popen(argv, **opts)

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
     "57":{"class_type":"CreateVideo","inputs":{"images":["8",0],"fps":16}},
     "58":{"class_type":"SaveVideo","inputs":{"video":["57",0],"filename_prefix":"frutaverso/gerado","format":"auto","format.codec":"auto"}}
    }

def request(base,endpoint,data=None,ctype="application/json",timeout=30):
    raw=json.dumps(data).encode("utf-8") if isinstance(data,dict) else data
    hdr={"Content-Type":ctype} if raw is not None else {}
    with urllib.request.urlopen(urllib.request.Request(base+endpoint,data=raw,headers=hdr),timeout=timeout) as r:return r.read()

COMFY_SETTINGS = APP_HOME / "comfy_desktop.json"

def configured_desktop():
    try:
        data=json.loads(COMFY_SETTINGS.read_text(encoding="utf-8"))
        path=Path(data.get("executable",""))
        if path.is_file() and path.suffix.lower()==".exe":return path
    except (OSError,ValueError,TypeError):pass
    return None

def save_desktop_executable(path):
    path=Path(path)
    if not path.is_file() or path.suffix.lower()!=".exe":
        raise ValueError("Selecione o executavel .exe instalado do Comfy Desktop.")
    # Protege contra a selecao acidental de outro aplicativo.
    if "comfy" not in path.name.lower() and "comfy" not in str(path.parent).lower():
        raise ValueError("Esse arquivo nao parece ser o Comfy Desktop.")
    COMFY_SETTINGS.write_text(json.dumps({"executable":str(path)},ensure_ascii=False,indent=2),encoding="utf-8")

def running_comfy():
    """Identifica processos do Desktop e argumentos --port do backend sem abrir CMD."""
    desktop=[]; ports=set()
    for procinfo in psutil.process_iter(["name","exe","cmdline"]):
        try:
            name=(procinfo.info.get("name") or "").lower()
            exe=procinfo.info.get("exe") or ""
            parts=procinfo.info.get("cmdline") or []
            joined=" ".join(str(p) for p in parts)
            lower=joined.lower()
            if "comfy" in name and "desktop" in name and exe:
                desktop.append(Path(exe))
            if name=="comfyui.exe" and exe:desktop.append(Path(exe))
            if "main.py" in lower and ("comfy" in lower or "comfyui" in lower):
                match=re.search(r"(?:^|\s)--port(?:=|\s+)(\d{2,5})\b",joined,re.I)
                if match:ports.add(int(match.group(1)))
                else:ports.add(8188)
        except (psutil.AccessDenied,psutil.NoSuchProcess,OSError):continue
    return desktop,ports

def candidate_desktops():
    local=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))
    programs=Path(os.environ.get("PROGRAMFILES","C:/Program Files"))
    p86=Path(os.environ.get("PROGRAMFILES(X86)","C:/Program Files (x86)"))
    roots=[
       local/"Programs"/"Comfy Desktop", local/"Programs"/"ComfyUI",
       local/"Programs"/"comfyui-desktop-2", local/"Programs"/"comfyui-electron",
       local/"Comfy Desktop", local/"ComfyUI", local/"Comfy-Desktop",
       programs/"Comfy Desktop", programs/"ComfyUI", p86/"Comfy Desktop",
       local/"Programs", programs
    ]
    filenames=("Comfy Desktop.exe","ComfyUI.exe","Comfy-Desktop.exe","comfyui-desktop-2.exe")
    found=[];seen=set()
    def put(p):
        try:
            if p.is_file() and str(p).lower() not in seen:
                seen.add(str(p).lower());found.append(p)
        except OSError:pass
    custom=configured_desktop()
    if custom:put(custom)
    running,_=running_comfy()
    for exe in running:put(exe)
    for root in roots:
        for exe in filenames:put(root/exe)
        # Desktop pode ser instalado em subdiretorio com nome diferente.
        if root.name=="Programs" and root.is_dir():
            try:
                for child in root.iterdir():
                    if child.is_dir() and "comfy" in child.name.lower():
                        for exe in filenames:put(child/exe)
            except OSError:pass
    if os.name=="nt":
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
                for keyname in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                    try:rootkey=winreg.OpenKey(hive,keyname)
                    except OSError:continue
                    with rootkey:
                        count=winreg.QueryInfoKey(rootkey)[0]
                        for i in range(count):
                            try:
                                with winreg.OpenKey(rootkey,winreg.EnumKey(rootkey,i)) as sub:
                                    name=str(winreg.QueryValueEx(sub,"DisplayName")[0])
                                    if "comfy" not in name.lower():continue
                                    try:
                                        location=Path(winreg.QueryValueEx(sub,"InstallLocation")[0])
                                        for exe in filenames:put(location/exe)
                                    except OSError:pass
                                    try:
                                        icon=str(winreg.QueryValueEx(sub,"DisplayIcon")[0]).split('",')[0].strip('"')
                                        put(Path(icon))
                                    except OSError:pass
                            except OSError:continue
        except (OSError,ImportError) as exc:logline("Registro ComfyUI: "+str(exc))
    return found

def comfy_ports():
    _,process_ports=running_comfy()
    ports=set([8000,8188,8189,8190,8187,8191,8200])
    ports.update(range(8000,8251))
    ports.update(p for p in process_ports if 1<=p<=65535)
    settings=APP_HOME/"comfy_desktop.json"
    if settings.is_file():
        try:
            saved=int(json.loads(settings.read_text(encoding="utf-8")).get("port",0))
            if 1<=saved<=65535:ports.add(saved)
        except (ValueError,TypeError,OSError):pass
    return sorted(ports,key=lambda p:(p not in (8000,8188,8189,8190),p))

def _probe_comfy(port):
    base=f"http://127.0.0.1:{port}"
    try:
        obj=json.loads(request(base,"/system_stats",timeout=.45))
        if isinstance(obj,dict) and "devices" in obj and "system" in obj:
            return base
    except Exception:pass
    return None

def server():
    """Detecta API em processo Python Comfy ou servidor ja iniciado pelo Frutaverso."""
    quick=[MANAGED_PORT,8000,8188,8189,8190]
    quick += sorted(active_comfy_ports())
    seen=set()
    for port in quick:
        if not port or port in seen:
            continue
        seen.add(port)
        base=_probe_comfy(port)
        if base:return base
    # Em caso de Desktop com porta dinamica, procure em segundo plano.
    ports=[p for p in comfy_ports() if p not in seen]
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        for base in pool.map(_probe_comfy,ports):
            if base:return base
    return None

MANAGED_BACKEND = None
MANAGED_PORT = None

def local_comfy_installs():
    """Instalacoes registradas pelo Comfy Desktop (nao confundir com seu executavel)."""
    found = []
    seen = set()
    roaming = Path(os.environ.get("APPDATA", str(Path.home()/"AppData"/"Roaming")))
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()/"AppData"/"Local")))
    config = roaming/"Comfy Desktop"
    entries = []
    config_path = config/"installations.json"
    if config_path.is_file():
        try:
            records = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if isinstance(records, list):
                for record in records:
                    if not isinstance(record, dict):
                        continue
                    if str(record.get("sourceId","")).lower() in ("cloud","remote","desktop"):
                        continue
                    location = record.get("installPath")
                    if location:
                        entries.append((Path(location), record.get("name","ComfyUI")))
        except (OSError,ValueError,TypeError) as exc:
            logline("Nao foi possivel interpretar installations.json: "+str(exc))
    settings = config/"settings.json"
    if settings.is_file():
        try:
            settings_obj = json.loads(settings.read_text(encoding="utf-8-sig"))
            install_dir=settings_obj.get("installDir")
            if install_dir and Path(install_dir).is_dir():
                for child in list(Path(install_dir).iterdir())[:80]:
                    if child.is_dir():
                        entries.append((child, child.name))
        except (OSError,ValueError,TypeError):
            pass
    locations = [
        local/"Comfy-Desktop"/"ComfyUI-Installs",
        Path.home()/"ComfyUI-Installs",
        local/"Programs"/"ComfyUI",
    ]
    for location in locations:
        if location.is_dir():
            try:
                entries.extend((p,p.name) for p in list(location.iterdir())[:80] if p.is_dir())
            except OSError:
                pass
    for root,name in entries:
        # A instalacao pode se chamar ComfyUI e conter outra pasta ComfyUI.
        # Subir um nivel apenas quando este root for a pasta do codigo main.py.
        if (root/"main.py").is_file():
            root=root.parent
        main = root/"ComfyUI"/"main.py"
        if not main.is_file():
            continue
        py_candidates = (
            root/"ComfyUI"/".venv"/"Scripts"/"python.exe",
            root/"standalone-env"/"Scripts"/"python.exe",
            root/"standalone-env"/"python.exe",
            root/"envs"/"default"/"Scripts"/"python.exe",
            root/"ComfyUI"/"venv"/"Scripts"/"python.exe"
        )
        exe = next((p for p in py_candidates if p.is_file()),None)
        if not exe:
            continue
        key=str(root).lower()
        if key not in seen:
            seen.add(key)
            found.append((root,exe,str(name)))
    return found

def active_comfy_ports():
    ports=set()
    try:
        listeners=psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied,OSError):
        return ports
    for item in listeners:
        try:
            if item.status != psutil.CONN_LISTEN or not item.pid:
                continue
            p=psutil.Process(item.pid)
            cmd=" ".join(p.cmdline()).lower()
            if "main.py" in cmd and ("comfy" in cmd or "comfyui" in cmd):
                port=item.laddr.port
                if port and 1<=port<=65535:
                    ports.add(port)
        except (psutil.AccessDenied,psutil.NoSuchProcess,OSError,ValueError):
            continue
    return ports

def start_backend(status):
    """Inicia a instalacao Python ja existente. Nao abre a janela do Comfy Desktop."""
    global MANAGED_BACKEND,MANAGED_PORT
    installs=local_comfy_installs()
    if not installs:
        raise RuntimeError(
            "Nao encontrei a instalacao de IA do Comfy Desktop. "
            "Acesse 'Diagnosticar motor' e envie o arquivo DIAGNOSTICO_FRUTAVERSO.txt. "
            "Nao reinstale os modelos."
        )
    root,python_exe,name=installs[0]
    comfy_dir=root/"ComfyUI"
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1",0))
        port=sock.getsockname()[1]
    log_path=APP_HOME/"motor_comfy.log"
    roaming=Path(os.environ.get("APPDATA", str(Path.home()/"AppData"/"Roaming")))
    config_path=roaming/"Comfy Desktop"/"shared_model_paths.yaml"
    args=[str(python_exe),"-s",str(comfy_dir/"main.py"),
          "--listen","127.0.0.1","--port",str(port),"--lowvram"]
    if config_path.is_file():
        args += ["--extra-model-paths-config",str(config_path)]
    else:
        shared = Path(os.environ.get("LOCALAPPDATA",str(Path.home()))) / "Comfy-Desktop"/"ComfyUI-Shared"
        if (shared/"models").is_dir():
            config_file=APP_HOME/"frutaverso_models.yaml"
            base=str(shared).replace("\\","/")
            config_file.write_text(
                "frutaverso_shared:\n  base_path: '"+base.replace("'","''")+"'\n"+
                "  diffusion_models: models/diffusion_models\n"+
                "  text_encoders: models/text_encoders\n"+
                "  vae: models/vae\n"+
                "  checkpoints: models/checkpoints\n"+
                "  loras: models/loras\n",encoding="utf-8")
            args += ["--extra-model-paths-config",str(config_file)]
    status("Motor Wan localizado em "+str(root)+". Iniciando em segundo plano, sem CMD...")
    logline("Iniciando motor local na porta "+str(port)+" usando "+str(python_exe))
    with log_path.open("ab") as fp:
        fp.write(("\n=== Frutaverso "+VERSION+" em "+datetime.datetime.now().isoformat()+" ===\n").encode())
        fp.flush()
        MANAGED_BACKEND=proc(args,cwd=str(root),stdout=fp,stderr=subprocess.STDOUT)
    MANAGED_PORT=port
    return port

def tail_backend_log():
    path=APP_HOME/"motor_comfy.log"
    try:
        data=path.read_bytes()[-9000:]
        return data.decode("utf-8","replace")[-1100:]
    except OSError:return "Sem log de inicializacao."

def get_server(status):
    global MANAGED_BACKEND,MANAGED_PORT
    base=server()
    if base:
        status("Motor ComfyUI conectado em "+base)
        return base
    status("Lendo a instalacao do ComfyUI registrada no Windows...")
    try:
        port=start_backend(status)
    except Exception as exc:
        logline("Falha na descoberta do backend: "+repr(exc))
        raise
    candidate=f"http://127.0.0.1:{port}"
    for elapsed in range(0,121,2):
        if MANAGED_BACKEND is not None and MANAGED_BACKEND.poll() is not None:
            raise RuntimeError(
                "O motor Wan iniciou mas encerrou com erro. Consulte motor_comfy.log. "
                "Detalhe: "+tail_backend_log()
            )
        if _probe_comfy(port):
            status("Motor Wan conectado. Preparando as cenas...")
            return candidate
        if elapsed%10==0:
            status("Inicializando IA na sua RTX 4060, sem CMD... "+str(elapsed)+"s")
        time.sleep(2)
    raise RuntimeError(
        "A instalacao de IA foi localizada, mas nao iniciou em 120 segundos. "
        "Consulte o arquivo motor_comfy.log no diagnostico. Detalhe: "+tail_backend_log()
    )

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
        self.button(bottom,"Localizar Comfy Desktop",self.choose_comfy).pack(side="left",padx=8)
        self.button(bottom,"Diagnosticar motor",self.diagnose_async).pack(side="left",padx=5)
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
    def choose_comfy(self):
        folder=filedialog.askopenfilename(title="Selecione Comfy Desktop.exe",filetypes=[("Aplicativos Windows","*.exe")])
        if not folder:return
        try:
            save_desktop_executable(folder)
            self.inform("Comfy Desktop configurado: "+folder)
            messagebox.showinfo("Motor configurado","O caminho foi salvo. Clique em Gerar episodio completo com IA.")
        except Exception as exc:messagebox.showerror("Caminho invalido",str(exc))

    def diagnose_async(self):
        def work():
            try:
                paths=candidate_desktops()
                installs=local_comfy_installs()
                self.inform("Instalacoes IA encontradas: "+("; ".join(str(root) for root,_,_ in installs[:3]) if installs else "nenhuma"))
                self.inform("Comfy Desktop instalado: "+("; ".join(map(str,paths[:4])) if paths else "nao localizado"))
                base=server()
                if base:self.inform("API local encontrada: "+base)
                else:self.inform("API local nao encontrada nas portas 8000 a 8250. Confira a instancia ativa no Comfy Desktop.")
                diag=APP_HOME/"DIAGNOSTICO_FRUTAVERSO.txt"
                diag.write_text(
                    "Frutaverso v"+VERSION+"\nComfy Desktop: "+(", ".join(map(str,paths)) if paths else "nao localizado")+
                    "\nInstalacoes IA: "+("; ".join(str(r) for r,_,_ in installs) if installs else "nenhuma")+
                    "\nMotor: "+str(base)+"\nLog Frutaverso: "+str(APP_HOME/"frutaverso.log")+
                    "\nLog motor Python: "+str(APP_HOME/"motor_comfy.log")+
                    "\nTrecho ultimo log: "+tail_backend_log(),
                    encoding="utf-8")
                self.inform("Diagnostico gravado em "+str(diag))
            except Exception as exc:self.inform("Falha no diagnostico: "+str(exc))
        threading.Thread(target=work,daemon=True).start()

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
