"""Barrar release sem pipeline 90s completo e sem teste audiovisual minimo."""
from __future__ import annotations
import ast
import sys
import tempfile
import zipfile
import json
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
SRCDIR=ROOT/"source"
sys.path.insert(0,str(SRCDIR))
for filename in ("studio90.py","episode90.py","frutaverso.py"):
    file=SRCDIR/filename
    assert file.exists(),f"Fonte ausente {filename}"
    ast.parse(file.read_text(encoding="utf-8"),filename=str(file))
from episode90 import import_pack, smoke_test, ProjectError

with tempfile.TemporaryDirectory(prefix="frutaverso_gate_") as temp:
    base=Path(temp)
    assert smoke_test(base/"lipsync"),"Falha ao gerar MP4 de teste com boca sincronizada"
    source=base/"source";source.mkdir()
    (source/"imagens").mkdir()
    im=Image.new("RGB",(720,1280),(80,120,150))
    im.save(source/"imagens"/"cenario.png")
    im=Image.new("RGB",(720,1280),(80,120,150))
    im.save(source/"imagens"/"aberta.png")
    # Criar imagens de teste suficientemente completas e diferenciadas.
    from PIL import ImageDraw
    for name in ("cenario.png","aberta.png"):
        p=source/"imagens"/name
        frame=Image.open(p)
        d=ImageDraw.Draw(frame)
        for k in range(150):
            d.ellipse((k*5,300+k,320+k*2,550+k),outline=(k%250,150,220),width=2)
        if name=="aberta.png":
            d.ellipse((230,530,480,625),fill=(10,10,15))
        frame.save(p)
    payload={"titulo":"Teste 90 segundos","cenas":[]}
    for k in range(8):
        payload["cenas"].append({
            "nome":f"Teste {k+1}","tipo":"fala" if k%2==0 else "acao",
            "personagem":"Laranja" if k%2==0 else "Narrador",
            "duracao":11.25,
            "fala":"Boa noite, turma.",
            "imagem":"imagens/cenario.png",
            "boca_aberta":"imagens/aberta.png",
            "regiao_boca":[.28,.39,.38,.15]
        })
    (source/"roteiro.json").write_text(json.dumps(payload),encoding="utf-8")
    pack=base/"episodio.zip"
    with zipfile.ZipFile(pack,"w") as z:
        for file in source.rglob("*"):
            if file.is_file():z.write(file,file.relative_to(source))
    episode=import_pack(pack,base/"importados")
    assert len(episode["cenas"])==8
    assert abs(sum(s["duracao"] for s in episode["cenas"])-90)<.01
    assert all(s["_imagem"].is_file() for s in episode["cenas"])
    payload["cenas"][0]["duracao"]=11
    (source/"roteiro.json").write_text(json.dumps(payload),encoding="utf-8")
    wrong=base/"errado.zip"
    with zipfile.ZipFile(wrong,"w") as z:
        for file in source.rglob("*"):
            if file.is_file():z.write(file,file.relative_to(source))
    try:import_pack(wrong,base/"invalidos")
    except ProjectError:pass
    else:raise AssertionError("Validador aceitou roteiro menor que 90s")

print("FRUTAVERSO: teste de importacao ZIP, labios com WAV e 90s de roteiro PASSOU.")
