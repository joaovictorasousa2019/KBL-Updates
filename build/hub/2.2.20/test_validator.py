"""Test Hub module discovery, install, preservation, hash failure and rollback.

    With KBL_VALIDATOR_PACKAGE this tests the actual release ZIP; the Windows
    installer pipeline uses a descriptor fixture for the same Hub contract.
"""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('kblhub_validator_test', ROOT / 'hub-installer' / 'kbl_hub.py')
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)
assert hub.HUB_VERSION == '2.2.20'
assert 'def archived_ids(self):' in Path(hub.__file__).read_text(encoding='utf-8')
assert hub.DEFAULT_APPS['validador-balancete'] == 'KBL Validador de Balancete'
assert hub.ENTRYPOINT_HINTS['validador-balancete'][0] == 'app.pyw'

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    package = root / 'KBL_Validador_Balancete_v1_0_2_Hub.zip'
    actual = os.environ.get('KBL_VALIDATOR_PACKAGE')
    if actual:
        shutil.copyfile(actual, package)
    else:
        # Minimal install fixture; the app release is validated separately.
        descriptor = {'app_id': 'validador-balancete', 'name': 'KBL Validador de Balancete',
                      'version': '1.0.2', 'entry': 'app.pyw', 'window_title': 'KBL Validador de Balancete'}
        with zipfile.ZipFile(package, 'w') as z:
            z.writestr('KBL_Validador/hub_app.json', json.dumps(descriptor))
            z.writestr('KBL_Validador/version.json', json.dumps(descriptor))
            z.writestr('KBL_Validador/app.pyw', '# package contract fixture\n')
            z.writestr('KBL_Validador/requirements.txt', 'PyMuPDF==1.26.6\nPillow==12.3.0\n')
    assert hub.detect_app_id_from_zip(package) == 'validador-balancete'
    assert hub.detect_version_from_zip(package) == '1.0.2'
    random_name = root / 'qualquer-nome.zip'
    shutil.copyfile(package, random_name)
    assert hub.detect_app_id_from_zip(random_name) == 'validador-balancete'
    fallback = root / 'KBL_Validador_Balancete_v1_0_2.zip'
    with zipfile.ZipFile(fallback, 'w') as z:
        z.writestr('app.pyw', '# fixture\n')
    assert hub.detect_app_id_from_zip(fallback) == 'validador-balancete'

    hub.LOCAL_ROOT = root / 'Local' / 'KBL'
    hub.APPS_ROOT = hub.LOCAL_ROOT / 'Apps'
    hub.DATA_ROOT = root / 'Roaming' / 'KBLAccounting'
    hub.HUB_DATA = hub.DATA_ROOT / 'Hub'
    hub.REGISTRY_FILE = hub.HUB_DATA / 'registry.json'
    hub.install_requirements = lambda folder: hub.requirements_digest(folder)
    hub.ensure_dirs()
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    candidate = {'source': 'Base local', 'file': package, 'sha256': digest, 'version': '1.0.2'}
    fake = SimpleNamespace(candidate=lambda app_id: candidate, registry={'schema_version': 2, 'apps': {}})
    app_id = 'validador-balancete'
    hub.Hub._perform_install(fake, app_id)
    installed = hub.app_dir(app_id)
    assert hub.find_entrypoint(installed, app_id).name == 'app.pyw'
    assert hub.local_version(app_id, fake.registry) == '1.0.2'
    assert set(hub.requirement_distributions(installed)) == {'PyMuPDF', 'Pillow'}

    # Both regular persistent data and optional portable data must survive.
    persistent = hub.DATA_ROOT / 'ValidadorBalancete' / 'revisoes.sqlite3'
    persistent.parent.mkdir(parents=True, exist_ok=True)
    persistent.write_bytes(b'persisted-user-data')
    portable = installed / 'dados' / 'rascunho.txt'
    portable.parent.mkdir()
    portable.write_text('conferencia portatil', encoding='utf-8')
    hub.Hub._perform_install(fake, app_id)
    assert portable.read_text(encoding='utf-8') == 'conferencia portatil'
    assert persistent.read_bytes() == b'persisted-user-data'

    # A stale backup exists; hash failure must not restore it over newer data.
    marker = installed / 'mais-recente.txt'
    marker.write_text('nao substituir por backup antigo', encoding='utf-8')
    candidate['sha256'] = '0' * 64
    try:
        hub.Hub._perform_install(fake, app_id)
        raise AssertionError('Bad SHA accepted')
    except RuntimeError as exc:
        assert 'SHA-256' in str(exc)
    assert marker.exists() and portable.exists() and persistent.exists()

    # A failure after replacement must restore the most recent installation.
    candidate['sha256'] = digest
    def fail_dependencies(folder):
        raise RuntimeError('simulated dependency failure')
    hub.install_requirements = fail_dependencies
    try:
        hub.Hub._perform_install(fake, app_id)
        raise AssertionError('Failed install accepted')
    except RuntimeError as exc:
        assert 'simulated dependency failure' in str(exc)
    assert marker.exists() and portable.exists()
    assert persistent.read_bytes() == b'persisted-user-data'

print('VALIDATOR_HUB_CONTRACT_OK: discovery, metadata, install, update, data, SHA rejection and rollback')
