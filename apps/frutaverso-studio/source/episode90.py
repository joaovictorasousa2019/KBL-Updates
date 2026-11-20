# -*- coding: utf-8 -*-
"""Frutaverso 90s: renderizacao completa a partir de roteiro.json + imagens.
Voz: Kokoro ONNX local. Acao: Wan2.2 do ComfyUI local.
Dialogo: visemas ilustrados no pacote, animados pelo envelope de audio;
nao afirma equivalencia com lip-sync neural fonema-a-fonema.
"""
from __future__ import annotations
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import wave
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from imageio_ffmpeg import write_frames, read_frames

import frutaverso as base

FPS=24
WIDTH=720
HEIGHT=1280
TARGET=90.0
MAX_SCENES=30

class ProjectError(RuntimeError):
    pass

def _safe_extract(archive:Path, target:Path):
    total=0
    with zipfile.ZipFile(archive) as z:
        files=[i for i in z.infolist() if not i.is_dir()]
        if len(files)>150:raise ProjectError("Pacote com arquivos demais (limite 150).")
        for m in files:
            path=Path(m.filename.replace("\\","/"))
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ProjectError("Caminho inseguro no ZIP.")
            if m.file_size>70*1024*1024:raise ProjectError("Imagem maior que 70 MB.")
            total+=m.file_size
            if total>450*1024*1024:raise ProjectError("Pacote excede 450 MB.")
        for m in files:
            rel=Path(m.filename.replace("\\","/"))
            dest=(target/rel).resolve()
            if target.resolve() not in dest.parents:raise ProjectError("Caminho de ZIP invalido.")
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(m) as inp, dest.open("wb") as out:
                shutil.copyfileobj(inp,out)
    roots=list(target.rglob("roteiro.json"))
    if len(roots)!=1:raise ProjectError("ZIP deve conter um unico roteiro.json.")
    return roots[0].parent

def _project_from_root(root:Path):
    script=root/"roteiro.json"
    if not script.is_file():raise ProjectError("Falta roteiro.json.")
    try:data=json.loads(script.read_text(encoding="utf-8-sig"))
    except (OSError,ValueError) as e:raise ProjectError("Roteiro JSON invalido: "+str(e))
    scenes=data.get("cenas")
    if not isinstance(scenes,list) or not 8<=len(scenes)<=MAX_SCENES:
        raise ProjectError("O episodio de 90s precisa de 8 a 30 cenas.")
    durations=[]
    for i,s in enumerate(scenes,1):
        if not isinstance(s,dict):raise ProjectError("Cena "+str(i)+" invalida.")
        image=s.get("imagem","")
        if not isinstance(image,str) or not image:
            raise ProjectError("Cena "+str(i)+" sem imagem.")
        def resolve(value):
            path=(root/value).resolve()
            if root.resolve() not in path.parents:raise ProjectError("Imagem fora do pacote.")
            if not path.is_file() or path.suffix.lower() not in (".jpg",".jpeg",".png",".webp"):
                raise ProjectError("Imagem inexistente: "+value)
            if path.stat().st_size<13000:raise ProjectError("Imagem insuficiente: "+value)
            try:
                with Image.open(path) as im:
                    if min(im.size)<420:raise ProjectError("Imagem muito pequena: "+value)
                    if not 0.4<im.width/im.height<1.5:raise ProjectError("Imagem com proporcao inadequada: "+value)
            except (OSError,ValueError) as e:raise ProjectError("Imagem corrompida: "+value) from e
            return path
        s["_imagem"]=resolve(image)
        scene_type=str(s.get("tipo","narracao")).lower()
        if scene_type not in ("fala","acao","narracao"):
            raise ProjectError("Tipo invalido na cena "+str(i)+".")
        s["tipo"]=scene_type
        speaker=str(s.get("personagem","Narrador")).strip()
        talk=(scene_type=="fala" and speaker.lower()!="narrador")
        if talk:
            mouth=s.get("boca_aberta")
            if not mouth:raise ProjectError("Cena "+str(i)+" precisa de boca_aberta para sincronizar a fala.")
            s["_boca"]=resolve(mouth)
            bbox=s.get("regiao_boca")
            if not isinstance(bbox,list) or len(bbox)!=4:
                raise ProjectError("Cena "+str(i)+" precisa de regiao_boca no roteiro.")
            x,y,w,h=map(float,bbox)
            if not all(0<=v<=1 for v in (x,y,w,h)) or w<.04 or h<.025 or x+w>1 or y+h>1:
                raise ProjectError("Regiao de boca invalida na cena "+str(i)+".")
            s["_bbox"]=(x,y,w,h)
        d=float(s.get("duracao",0))
        if not 2<=d<=20:raise ProjectError("Duracao invalida na cena "+str(i)+".")
        durations.append(d)
        s["fala"]=str(s.get("fala","")).strip()
        if not s["fala"] and scene_type=="fala":
            raise ProjectError("Cena "+str(i)+" possui personagem mas nao tem fala.")
    if abs(sum(durations)-TARGET)>.12:
        raise ProjectError(f"Duracoes somam {sum(durations):.2f}s; o roteiro precisa somar 90 segundos.")
    data["duracao_total"]=TARGET
    data["titulo"]=str(data.get("titulo","Episodio Frutaverso"))[:110]
    data["_root"]=root
    return data

def import_pack(zip_path:Path,destination:Path):
    zip_path=Path(zip_path)
    if not zipfile.is_zipfile(zip_path):raise ProjectError("Selecione um pacote ZIP valido.")
    destination.mkdir(parents=True,exist_ok=True)
    marker=hashlib.sha256(zip_path.read_bytes()).hexdigest()[:20]
    folder=destination/marker
    if (folder/"roteiro.json").is_file():
        return _project_from_root(folder)
    staging=destination/("staging_"+marker)
    if staging.exists():shutil.rmtree(staging)
    staging.mkdir()
    try:
        root=_safe_extract(zip_path,staging)
        _project_from_root(root)
        if folder.exists():shutil.rmtree(folder)
        shutil.move(str(root),str(folder))
    finally:
        if staging.exists():shutil.rmtree(staging)
    return _project_from_root(folder)

def _font(size,bold=True):
    paths=[
       "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
       "C:/Windows/Fonts/segoeuib.ttf",
       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    for path in paths:
        if Path(path).is_file():return ImageFont.truetype(path,size)
    return ImageFont.load_default()

def _envelope(path:Path, frames:int):
    samples,sr=sf.read(str(path),dtype="float32",always_2d=True)
    mono=np.mean(samples,axis=1)
    rms=[]
    step=max(1,int(sr/50))
    for k in range(0,len(mono),step):
        buf=mono[k:k+step]
        rms.append(float(np.sqrt(np.mean(buf**2))) if buf.size else 0.0)
    if not rms:return np.zeros(frames,dtype=np.float32)
    rms=np.array(rms,dtype=np.float32)
    high=max(float(np.percentile(rms,85)),.0003)
    t=np.arange(frames)/FPS
    raw=np.interp(t,np.arange(len(rms))*step/sr,np.clip(rms/high,0,1.1),right=0,left=0)
    raw=np.clip((raw-.12)*1.50,0,1)
    # Smooth transitions and hold low-level consonants briefly
    out=np.zeros(frames,dtype=np.float32)
    for k in range(frames):
        prev=out[k-1] if k else 0.0
        alpha=.72 if raw[k]>prev else .32
        out[k]=prev+alpha*(raw[k]-prev)
    return out

def _canvas(path):
    with Image.open(path) as im:
        im=im.convert("RGB")
        return ImageOps.fit(im,(WIDTH,HEIGHT),method=Image.Resampling.LANCZOS,centering=(.5,.45))

def _mask(bbox):
    x,y,w,h=bbox
    area=(int(x*WIDTH),int(y*HEIGHT),int((x+w)*WIDTH),int((y+h)*HEIGHT))
    mask=Image.new("L",(WIDTH,HEIGHT),0)
    d=ImageDraw.Draw(mask)
    dx=int(w*WIDTH*.02);dy=int(h*HEIGHT*.12)
    d.rounded_rectangle((area[0]-dx,area[1]-dy,area[2]+dx,area[3]+dy),
                        radius=max(5,int(h*HEIGHT*.30)),fill=255)
    return mask.filter(ImageFilter.GaussianBlur(max(6,int(h*HEIGHT*.25))))

def _camera(img,k,total,scene_index):
    """Camera cinematografica suave sem deformar a boca."""
    phase=k/max(1,total-1)
    zoom=1.028+.030*(.5-.5*math.cos(math.pi*phase))
    cw=int(WIDTH/zoom);ch=int(HEIGHT/zoom)
    x=int((WIDTH-cw)*(.5 + .08*math.sin(phase*math.pi + scene_index)))
    y=int((HEIGHT-ch)*(.45 + .06*math.cos(phase*math.pi)))
    return img.crop((x,y,x+cw,y+ch)).resize((WIDTH,HEIGHT),Image.Resampling.BICUBIC)

def _render_talk(scene,wav:Path,out:Path,duration:float,index:int,status):
    """Boca usa 2 imagens fornecidas no pacote; visemas aproximados guiados pelo WAV.
    Nao usa deformacao de rosto nem desenha boca artificial.
    """
    closed=_canvas(scene["_imagem"])
    opened=_canvas(scene["_boca"])
    mask=_mask(scene["_bbox"])
    total=max(1,round(duration*FPS))
    env=_envelope(wav,total)
    writer=write_frames(str(out),(WIDTH,HEIGHT),fps=FPS,
        codec="libx264",pix_fmt_in="rgb24",
        output_params=["-preset","veryfast","-crf","21","-pix_fmt","yuv420p"])
    writer.send(None)
    try:
        for k,v in enumerate(env):
            # Soft blend of the speaking mouth within the masked region only.
            local=Image.blend(closed,opened,min(1.0,max(0.0,float(v))))
            frame=Image.composite(local,closed,mask)
            frame=_camera(frame,k,total,index)
            writer.send(frame.tobytes())
        writer.close()
    except Exception:
        try:writer.close()
        except Exception:pass
        out.unlink(missing_ok=True)
        raise
    status(f"Cena {index}: movimento da boca aplicado ao audio ({total} quadros).")
    if out.stat().st_size<5000:raise ProjectError("Lip-sync resultou em arquivo vazio.")
    return out

def _wav_length(path):
    with wave.open(str(path),"rb") as w:
        return w.getnframes()/w.getframerate()

def _subtitle_asset(text,speaker,dest):
    """Legendas sem caixa escura gigante, no terco inferior."""
    canvas=Image.new("RGBA",(WIDTH,HEIGHT))
    draw=ImageDraw.Draw(canvas)
    words=text.split()
    font=_font(42)
    chunks=[];cur=""
    for word in words:
        candidate=(cur+" "+word).strip()
        if cur and draw.textbbox((0,0),candidate,font=font,stroke_width=3)[2]>WIDTH-120:
            chunks.append(cur);cur=word
        else:cur=candidate
    if cur:chunks.append(cur)
    chunks=chunks[:3]
    sy=930+(3-len(chunks))*25
    for i,line in enumerate(chunks):
        draw.text((WIDTH/2,sy+i*58),line,font=font,anchor="ma",fill="white",stroke_width=4,stroke_fill=(8,13,23))
    if speaker.lower()!="narrador":
        lab=_font(25)
        draw.text((WIDTH/2,sy-48),speaker.upper(),font=lab,anchor="ma",fill=(255,197,61),stroke_width=3,stroke_fill=(8,13,23))
    canvas.save(dest)

def _ff(args,timeout=14400):
    prog=base.imageio_ffmpeg.get_ffmpeg_exe()
    proc=subprocess.run([prog,"-nostdin","-hide_banner","-loglevel","error","-y"]+args,
                        capture_output=True,text=True,timeout=timeout,**base.HIDDEN)
    if proc.returncode:
        raise ProjectError("Falha FFmpeg: "+(proc.stderr or proc.stdout)[-1300:])

def _action_clip(project,scene,index,status):
    """Wan sempre obrigatorio para cenas de acao/narracao, nao usa imagem estatica disfarçada."""
    status(f"Cena {index}: enviando imagem 3D ao Wan...")
    shot=dict(scene)
    shot["imagem"]=str(scene["_imagem"])
    shot["prompt"]=scene.get("prompt_movimento") or (
        "Cinematic high-end 3D animated movie shot, expressive anthropomorphic fruit "
        "character, natural body movement, dramatic lighting, controlled camera move, "
        "preserve exact appearance, detailed texture, vertical composition."
    )
    engine=base.get_server(status)
    return Path(base.animate(engine,shot,index,status))

def _conform(scene,visual:Path,audio:Path|None,out:Path,duration:float,index:int,work:Path):
    caption=work/f"caption_{index:02}.png"
    _subtitle_asset(scene.get("fala",""),scene.get("personagem","Narrador"),caption)
    audio_input=["-i",str(audio)] if audio else ["-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=44100"]
    # Loop action footage smoothly (last-frame hold suppresses hard flash).
    args=["-stream_loop","-1","-i",str(visual),"-loop","1","-i",str(caption)]+audio_input
    args+=["-filter_complex",
        "[0:v]fps=24,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1[base];"
        "[base][1:v]overlay=0:0:shortest=1[v]",
        "-map","[v]","-map","2:a",
        "-t",f"{duration:.3f}","-r","24","-c:v","libx264","-preset","veryfast",
        "-crf","20","-pix_fmt","yuv420p","-c:a","aac","-b:a","160k",
        "-af","apad","-movflags","+faststart",str(out)]
    _ff(args)
    if not out.is_file() or out.stat().st_size<5000:
        raise ProjectError("A cena "+str(index)+" nao produziu video valido.")

def _duration(path):
    ffmpeg=base.imageio_ffmpeg.get_ffmpeg_exe()
    probe=Path(ffmpeg).parent/("ffprobe.exe" if os.name=="nt" else "ffprobe")
    if not probe.is_file():
        # imageio-ffmpeg nao inclui ffprobe no Windows; procurar outro executavel antes do log.
        probe=shutil.which("ffprobe")
    if probe:
        proc=subprocess.run([str(probe),"-v","error","-show_entries","format=duration",
                             "-of","default=noprint_wrappers=1:nokey=1",str(path)],
                            capture_output=True,text=True,timeout=20,**base.HIDDEN)
        if proc.returncode==0:
            try:return float(proc.stdout.strip())
            except ValueError:pass
    return None

def render(project,status):
    root=Path(project["_root"])
    job=root/"render"
    job.mkdir(exist_ok=True)
    segments=[]
    scenes=project["cenas"]
    for idx,scene in enumerate(scenes,1):
        duration=float(scene["duracao"])
        status(f"Cena {idx}/{len(scenes)}: voz e animacao...")
        content=scene.get("fala","")
        wav=None
        if content:
            wav=job/f"fala_{idx:02}.wav"
            if not wav.is_file() or wav.stat().st_size<1200:
                base.voice(content,wav,status,scene)
            sound_len=_wav_length(wav)
            if sound_len>duration-0.15:
                raise ProjectError(f"Cena {idx}: fala tem {sound_len:.1f}s, mas a cena tem {duration:.1f}s. O roteiro precisa de uma fala mais curta.")
        visual=job/f"mov_{idx:02}.mp4"
        if not visual.is_file() or visual.stat().st_size<5000:
            if scene["tipo"]=="fala" and scene["personagem"].strip().lower()!="narrador":
                _render_talk(scene,wav,visual,duration,idx,status)
            else:
                generated=_action_clip(project,scene,idx,status)
                shutil.copy2(generated,visual)
        segment=job/f"montado_{idx:02}.mp4"
        if not segment.is_file() or segment.stat().st_size<5000:
            _conform(scene,visual,wav,segment,duration,idx,job)
        segments.append(segment)
    manifest=job/"concat.txt"
    manifest.write_text("\n".join("file '"+p.as_posix().replace("'","")+"'" for p in segments),encoding="utf-8")
    temp=job/"export_90s.mp4"
    _ff(["-f","concat","-safe","0","-i",str(manifest),"-t","90",
         "-c:v","libx264","-preset","medium","-crf","19",
         "-r","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",
         "-vf","scale=1080:1920:flags=lanczos","-movflags","+faststart",str(temp)])
    if not temp.is_file() or temp.stat().st_size<100000:
        raise ProjectError("A exportacao final nao gerou um video valido.")
    d=_duration(temp)
    if d is not None and not 89.65<=d<=90.15:
        raise ProjectError(f"Exportacao rejeitada: o video tem {d:.2f}s em vez de 90s.")
    result=base.OUTPUT/("FRUTAVERSO_TIKTOK_90S_"+base.datetime.datetime.now().strftime("%Y%m%d_%H%M%S")+".mp4")
    shutil.copy2(temp,result)
    status("MP4 finalizado: 1080x1920, 24fps, 90 segundos.")
    return result

def smoke_test(tmp):
    """Testa importaçao e render de boca sem baixar IA (para CI Windows)."""
    temp=Path(tmp)
    temp.mkdir(parents=True,exist_ok=True)
    a=Image.new("RGB",(720,1280),(52,84,114))
    b=a.copy()
    draw=ImageDraw.Draw(a);draw.ellipse((255,535,450,610),fill=(75,16,17))
    draw=ImageDraw.Draw(b);draw.ellipse((250,522,460,650),fill=(82,9,12))
    a.save(temp/"closed.png");b.save(temp/"open.png")
    sr=22050
    import numpy as np
    t=np.arange(sr*2,dtype=np.float32)/sr
    samples=(.18*np.sin(t*2*np.pi*220)*np.clip(np.sin(t*12)**4,0,1)).astype("float32")
    sf.write(temp/"voice.wav",samples,sr)
    scene={"_imagem":temp/"closed.png","_boca":temp/"open.png","_bbox":(.28,.39,.38,.16)}
    output=temp/"synced.mp4"
    _render_talk(scene,temp/"voice.wav",output,2.0,1,lambda _:None)
    return output.is_file() and output.stat().st_size>8000
