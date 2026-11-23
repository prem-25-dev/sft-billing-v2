"""Optional one-time demo data seeding — never runs automatically.

Per spec item 24 ("do NOT hard-code the current demo clients/invoices as
the permanent database"), this exists only so a developer can populate a
fresh SFT_Billing.xlsx with a couple of realistic records for manual
testing, invoked explicitly via `python -m app.seed_demo_data`. The
FastAPI app itself never calls this.
"""
from __future__ import annotations

from app.services import business_service, client_service, invoice_service


def seed() -> None:
    business_service.update_business_profile({
        "name": "SFT Enterprises",
        "address": "12 Residency Road, Bengaluru, Karnataka 560025",
        "email": "billing@sftenterprises.example",
        "gstin": "29AAAAA0000A1Z5",
        "pan": "AAAAA0000A",
        "bank": {
            "accountHolder": "SFT Enterprises",
            "bankName": "State Bank of India",
            "branch": "Residency Road",
            "accountNumber": "000000000000",
            "ifsc": "SBIN0000000",
        },
        "declaration": "We declare that this invoice shows the actual price of the goods/services described and that all particulars are true and correct.",
        "authorizedSignatory": "Authorized Signatory",
        "defaultGst": {"cgstRate": 0.09, "sgstRate": 0.09},
    })

    client = client_service.create_client({
        "name": "Acme Corporation",
        "contactName": "Priya Sharma",
        "email": "billing@acme.example",
        "phone": "+91 98765 43210",
        "billingAddress": "221B Industrial Layout, Bengaluru, Karnataka 560068",
        "gstin": "29BBBBB1111B1Z5",
    })

    invoice_service.create_invoice({
        "clientId": client["id"],
        "issueDate": "2025-01-05",
        "dueDate": "2025-01-20",
        "gst": {"cgstRate": 0.09, "sgstRate": 0.09},
        "discount": 0,
        "roundOff": 0,
        "isDraft": False,
        "items": [
            {"description": "Consulting services", "hsnCode": "9983", "quantity": 10, "unitPrice": 2000},
            {"description": "Hosting — annual", "hsnCode": "9983", "quantity": 1, "unitPrice": 5700},
        ],
    })

    print("Seeded demo business profile, one client, and one invoice.")


if __name__ == "__main__":
    seed()
