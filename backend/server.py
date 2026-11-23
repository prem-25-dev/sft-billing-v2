"""Entry point of the bundled billing service (PyInstaller: sft-billing-server.exe).

Started by the Flutter app with --port and --parent-pid. The service exits by
itself when the app that started it is gone, so it never lingers in the background.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time
from pathlib import Path


def _parent_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args()

    # Windowed build: no console, so give stdio a real target before logging starts.
    if sys.stdout is None or sys.stderr is None:
        local = Path(os.environ.get("LOCALAPPDATA", ".")) / "SFT Billing"
        local.mkdir(parents=True, exist_ok=True)
        log = open(local / "service.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    import uvicorn
    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_config=None, log_level="warning"))

    if args.parent_pid:
        def watch() -> None:
            while _parent_alive(args.parent_pid):
                time.sleep(2)
            server.should_exit = True

        threading.Thread(target=watch, daemon=True).start()

    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
