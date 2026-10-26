"""Register the KBL trial balance validator, keeping all 2.2.19 Hub fixes."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[3]
path = ROOT / 'hub-installer' / 'kbl_hub.py'
text = path.read_text(encoding='utf-8')
if 'HUB_VERSION = "2.2.19"' not in text or 'def archived_ids(self):' not in text:
    raise RuntimeError('A base precisa ser o Hub 2.2.19, com arquivamento e correções de runtime.')
text = text.replace('HUB_VERSION = "2.2.19"', 'HUB_VERSION = "2.2.20"', 1)
additions = {
    'DEFAULT_APPS': '    "validador-balancete": "KBL Validador de Balancete",\n',
    'ENTRYPOINT_HINTS': '    "validador-balancete": ["app.pyw", "app.py", "KBL_Validador_Balancete.exe"],\n',
    'FILENAME_APP_HINTS': '    "validador_balancete": "validador-balancete",\n    "validador-balancete": "validador-balancete",\n    "validador balancete": "validador-balancete",\n',
}
for name, addition in additions.items():
    anchor = name + ' = {\n'
    if text.count(anchor) != 1:
        raise RuntimeError('Dicionário não encontrado: ' + name)
    text = text.replace(anchor, anchor + addition, 1)
# A download/hash failure occurs before replacement. Never restore a stale
# backup or delete an existing app when no installation files were changed.
start = text.index('    def _perform_install(self, app_id):')
end = text.index('    def open_selected(self):', start)
block = text[start:end]
anchor = '        ext = work / "ext"\n        try:\n'
assert block.count(anchor) == 1
block = block.replace(anchor, '        ext = work / "ext"\n        installation_changed = False\n        backup_ready = False\n        try:\n', 1)
anchor = '                shutil.copytree(folder, backup)\n\n            if folder.exists():\n'
assert block.count(anchor) == 1
block = block.replace(anchor, '                shutil.copytree(folder, backup)\n                backup_ready = True\n\n            installation_changed = True\n            if folder.exists():\n', 1)
old = '''        except Exception:
            if backup.exists():
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
                shutil.copytree(backup, folder)
            elif folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            raise
'''
new = '''        except Exception:
            if installation_changed:
                if backup_ready and backup.exists():
                    if folder.exists():
                        shutil.rmtree(folder, ignore_errors=True)
                    shutil.copytree(backup, folder)
                elif folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
            raise
'''
assert block.count(old) == 1
block = block.replace(old, new, 1)
text = text[:start] + block + text[end:]
ast.parse(text)
path.write_text(text, encoding='utf-8')
print('KBL Hub patched to 2.2.20: Validador de Balancete')
