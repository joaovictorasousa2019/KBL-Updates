"""Bloqueia releases Frutaverso sem os requisitos de qualidade solicitados."""
from pathlib import Path
import sys
import ast

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"source"/"frutaverso.py"
ASSETS=ROOT/"source"/"assets"
fail=[]
source=SOURCE.read_text(encoding="utf-8")
ast.parse(source, filename=str(SOURCE))

for filename in ("01_laranja.webp","02_banana.webp","03_confronto.webp"):
    p=ASSETS/filename
    if not p.exists() or p.stat().st_size < 8_000:
        fail.append(f"Recurso 3D ausente/insuficiente: {p}")
if "def generate_placeholder" in source:
    fail.append("A criacao de bonecos substitutos ainda existe no codigo.")
if "build_synced_video" not in source and "render_lipsync" not in source:
    fail.append("Falta integrar lip-sync de audio ao video de cada personagem.")
if "neural_engine" not in source:
    fail.append("Falta o motor neural de voz brasileira.")
if "voice(" not in source or "animate(" not in source:
    fail.append("Pipeline de voz + animacao incompleto.")
if fail:
    print("FRUTAVERSO: BUILD BLOQUEADO POR QUALIDADE")
    for f in fail:print("ERRO: "+f)
    sys.exit(1)
print("Frutaverso release quality gate: regras basicas presentes.")
