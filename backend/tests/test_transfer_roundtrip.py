"""Export from one PC's database and restore on a fresh one (separate processes)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _run(code: str, db: Path, *args: str) -> str:
    env = dict(os.environ)
    url = f"sqlite:///{db.as_posix()}"
    env["SFT_BILLING_DATABASE_URL"] = url
    env["SFT_BILLING_MIGRATION_DATABASE_URL"] = url
    env["SFT_BILLING_AUTO_INIT"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip().splitlines()[-1]


SOURCE = """
import sys
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    r = c.post('/api/auth/first-run-setup', json={'username': 'a', 'mobile': '9876543210', 'password': 'Password123'})
    h = {'Authorization': 'Bearer ' + r.json()['token']}
    c.post('/api/clients', headers=h, json={'name': 'Acme', 'billingAddress': 'Chennai', 'gstin': '33ABCDE1234F1Z5', 'phone': '9876543210', 'contactName': 'Ravi', 'email': 'a@b.com'})
    resp = c.post('/api/transfer/export', headers=h, json={'master': True, 'business': True, 'transactions': False})
    assert resp.status_code == 200, resp.text
    open(sys.argv[1], 'wb').write(resp.content)
    print('exported', len(resp.content))
"""

TARGET = """
import sys
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    assert c.get('/api/setup/status').json()['needs_account'] is True
    bad = c.post('/api/setup/restore', files={'file': ('x.sftpack', b'garbage')})
    assert bad.status_code == 400, bad.text
    ok = c.post('/api/setup/restore', files={'file': ('x.sftpack', open(sys.argv[1], 'rb').read())})
    assert ok.status_code == 200, ok.text
    st = c.get('/api/setup/status').json()
    assert st['clients'] == 1 and st['needs_account'] is True, st
    r = c.post('/api/auth/first-run-setup', json={'username': 'newuser', 'mobile': '9123456780', 'password': 'Password123'})
    assert r.status_code == 200, r.text
    again = c.post('/api/setup/restore', files={'file': ('x.sftpack', open(sys.argv[1], 'rb').read())})
    assert again.status_code == 409
    print('restored ok')
"""


def test_export_then_restore_on_new_pc(tmp_path):
    pack = tmp_path / "data.sftpack"
    assert _run(SOURCE, tmp_path / "pc1.db", str(pack)).startswith("exported")
    assert _run(TARGET, tmp_path / "pc2.db", str(pack)) == "restored ok"
