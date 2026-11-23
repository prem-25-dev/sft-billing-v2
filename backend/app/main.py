"""SFT Billing backend entrypoint.

The frontend uses SQLite-backed API domains and the legacy workbook for
domains that have not yet been migrated.

See README.md for how to launch this application.
"""
from __future__ import annotations

import os
import argparse
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database.session import engine, initialize_database, initialize_notifications_database, validate_production_database
from app.excel.workbook import ensure_workbook_exists
from app.routes import (
    activities,
    auth,
    business_profile,
    clients,
    dashboard,
    health,
    invoice_items,
    invoices,
    notifications,
    payments,
    products,
    transfer,
)

app = FastAPI(
    title="SFT Billing API",
    description=(
        "Local FastAPI backend for SFT Billing. Migrated domains use SQLite; "
        "domains not yet migrated continue to use the legacy workbook."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Invoice-Export-Warnings"],
)


@app.on_event("startup")
def on_startup() -> None:
    validate_production_database()
    # The packaged service always migrates on start; in development opt in with SFT_BILLING_AUTO_INIT=1.
    if getattr(sys, "frozen", False) or os.environ.get("SFT_BILLING_AUTO_INIT") == "1":
        initialize_database(engine)
        initialize_notifications_database(engine)
    ensure_workbook_exists()


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(business_profile.router)
app.include_router(clients.router)
app.include_router(invoices.router)
app.include_router(invoice_items.router)
app.include_router(payments.router)
app.include_router(activities.router)
app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(notifications.router)
app.include_router(transfer.setup_router)
app.include_router(transfer.transfer_router)


def parse_args():
    parser = argparse.ArgumentParser(description="SFT Billing Backend")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    return parser.parse_args()


if __name__ == "__main__":
    import uvicorn
    args = parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
