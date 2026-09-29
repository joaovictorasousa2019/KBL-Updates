from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
p = ROOT / "hub-installer" / "kbl_hub.py"
t = p.read_text(encoding="utf-8")
if 'HUB_VERSION = "2.2.2"' in t:
    t = t.replace('HUB_VERSION = "2.2.2"', 'HUB_VERSION = "2.2.3"', 1)
elif 'HUB_VERSION = "2.2.0"' in t:
    t = t.replace('HUB_VERSION = "2.2.0"', 'HUB_VERSION = "2.2.3"', 1)
else:
    raise RuntimeError("HUB_VERSION esperado não encontrado")
p.write_text(t, encoding="utf-8")
print("KBL Hub version set to 2.2.3")
