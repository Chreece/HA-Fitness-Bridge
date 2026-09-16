"""Build the deterministic, self-contained HA configuration-directory installer."""
from pathlib import Path
import base64
import hashlib
import json
import zlib

ROOT = Path(__file__).resolve().parents[1]
rows = {}
for path in sorted((ROOT / 'custom_components/fitness_bridge').rglob('*')):
    if path.is_file() and '__pycache__' not in path.parts and path.suffix in {'.py', '.js', '.json'}:
        rows[str(path.relative_to(ROOT / 'custom_components/fitness_bridge'))] = base64.b64encode(path.read_bytes()).decode()
raw = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
payload = base64.b64encode(zlib.compress(raw, 9)).decode()
installer = r'''#!/usr/bin/env bash
# Execute this file. It installs only fitness_bridge and keeps a code backup.
set -Eeuo pipefail
python3 - "$@" <<'FITNESS_BRIDGE_PY'
import base64, datetime, hashlib, json, os, shutil, sys, tempfile, uuid, zlib
from pathlib import Path
raw = zlib.decompress(base64.b64decode('PAYLOAD'))
if hashlib.sha256(raw).hexdigest() != 'DIGEST':
    raise SystemExit('Bridge payload checksum mismatch')
files = json.loads(raw)
config = Path(sys.argv[1] if len(sys.argv)>1 else '/config').resolve()
if not config.is_dir() or not (config / 'configuration.yaml').is_file():
    raise SystemExit('Pass the Home Assistant configuration directory containing configuration.yaml')
components = config / 'custom_components'
if components.is_symlink():
    raise SystemExit('Refusing a symlinked custom_components directory')
components.mkdir(exist_ok=True)
target = components / 'fitness_bridge'
if target.is_symlink() or (target.exists() and not target.is_dir()):
    raise SystemExit('Refusing an unexpected fitness_bridge path')
staging = Path(tempfile.mkdtemp(prefix='fitness-bridge-stage-', dir=components))
backup = None
try:
    for name, content in files.items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts:
            raise SystemExit('Invalid payload path')
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(content, validate=True))
        dest.chmod(0o644)
    if target.exists():
        backup_root = config / 'fitness_bridge_backups'
        if backup_root.is_symlink():
            raise SystemExit('Refusing a symlinked backup directory')
        backup_root.mkdir(exist_ok=True)
        backup = backup_root / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except BaseException:
        if backup is not None:
            os.replace(backup, target)
        raise
    print('Installed HA-Fitness Bridge 0.31.0a1 at', target)
    if backup: print('Previous bridge code backup:', backup)
    print('Restart Home Assistant. Add Fitness Server Bridge > Connect from Fitness (OAuth), then connect in Fitness Admin > Home Assistant bridge.')
finally:
    if staging.exists(): shutil.rmtree(staging)
FITNESS_BRIDGE_PY
'''.replace('PAYLOAD', payload).replace('DIGEST', hashlib.sha256(raw).hexdigest())
target = ROOT / 'tools/install_bridge_a31.sh'
target.write_text(installer)
target.chmod(0o755)
print(json.dumps({'files':len(rows),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
