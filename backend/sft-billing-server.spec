# -*- mode: python ; coding: utf-8 -*-
# Bundles the FastAPI service into dist/sft-billing-server/ (one folder, windowed).

a = Analysis(
    ['server.py'],
    pathex=['.'],
    binaries=[],
    datas=[('app', 'app'), ('migrations', 'migrations'), ('alembic.ini', '.')],
    hiddenimports=[
        'uvicorn', 'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
        'fastapi', 'openpyxl', 'pydantic', 'pydantic_core', 'email_validator', 'starlette',
        'typing_extensions', 'annotated_types', 'anyio', 'idna', 'click', 'h11', 'multipart',
        'passlib.handlers.bcrypt', 'passlib.handlers.pbkdf2', 'reportlab', 'PIL', 'jose', 'bcrypt',
        'app.services.xlsx_pdf_renderer', 'app.services.invoice_pdf_service', 'app.services.transfer_service',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['IPython', 'pytest', 'jupyter', 'notebook', 'tkinter', 'numpy', 'pandas', 'scipy', 'matplotlib',
              'pythoncom', 'pywintypes', 'win32com'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='sft-billing-server',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='sft-billing-server')
