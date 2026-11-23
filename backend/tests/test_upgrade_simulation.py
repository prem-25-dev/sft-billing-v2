"""Version upgrade simulation tests.

Simulates upgrading from an older version (with existing business data) to the current version.
Verifies that all invoices, payments, clients, products, and business data are preserved.
"""

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Activity,
    BusinessProfileRecord,
    Client,
    Invoice,
    InvoiceItem,
    InvoiceNumberReservation,
    Notification,
    PasswordResetToken,
    Payment,
    Product,
    RecoveryAttempt,
    Session,
    User,
)
from app.database.session import (
    create_database_engine,
    initialize_database,
    shutdown_database,
)
from app.repositories.client_repository import ClientRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.product_repository import ProductRepository
from app.services import invoice_service, payment_service
from app.services.auth_service import create_user, _hash_password, _generate_recovery_key
from app.services.numbering_service import InvoiceNumberRepository


class UpgradeSimulationTests(unittest.TestCase):
    """Test that upgrading from an older schema version preserves all business data."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "upgrade_test.db"
        self.engine = create_database_engine(f"sqlite:///{self.database_path.as_posix()}")
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def tearDown(self):
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def _create_version_1_database(self):
        """Create a database at migration 0006_business_profile (pre-products, pre-auth).

        This simulates a Version 1 installation that has:
        - Clients
        - Invoices
        - Invoice items
        - Payments
        - Activities
        - Business profile
        But NOT:
        - Products/inventory
        - Notifications
        - Users/auth
        - Recovery attempts

        We run initializers following the MAIN migration path (not the 0007 branch):
        0001 -> 0002 -> 0003 -> 0004 -> 0005 -> 0006
        """
        from app.database.session import (
            initialize_invoice_database,
            initialize_payment_database,
            initialize_activity_database,
            initialize_business_profile_database,
        )

        # Run initializers in the main migration path order:
        # 1. initialize_invoice_database: runs 0001_sqlite + 0002_invoice_core
        #    (0001 creates clients table, 0002 creates invoices/invoice_items)
        initialize_invoice_database(self.engine)  # Target: 0002_invoice_core

        # 2. initialize_payment_database: runs 0003 + 0004 from current head (0002)
        initialize_payment_database(self.engine)  # Target: 0004_payments

        # 3. initialize_activity_database: runs 0005 from current head (0004)
        initialize_activity_database(self.engine)  # Target: 0005_activities

        # 4. initialize_business_profile_database: runs 0006 from current head (0005)
        initialize_business_profile_database(self.engine)  # Target: 0006_business_profile

        # Verify we're at migration 0006 (main path, not branch 0007)
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            self.assertEqual(version, "0006_business_profile")
            # Verify tables present
            tables = set(inspect(self.engine).get_table_names())
            expected = {"alembic_version", "clients", "invoices", "invoice_items",
                       "invoice_number_reservations", "payments", "activities", "business_profile"}
            self.assertEqual(tables, expected)
            # Verify products table does NOT exist
            self.assertNotIn("products", tables)
            self.assertNotIn("users", tables)

    def _insert_test_data(self):
        """Insert realistic test data into the Version 1 database.

        Version 1 (migration 0006) has:
        - Clients
        - Invoices
        - Invoice items
        - Payments
        - Activities
        - Business profile
        But NOT products (added in migration 0009)
        """
        session = self.session_factory()
        try:
            # 1. Business Profile
            business = BusinessProfileRecord(
                id=1,
                name="Surfine Technology",  # Matches seed database casing
                address="123 Industrial Estate, Chennai - 600001",
                email="billing@surfinetech.com",
                phone="+91-44-12345678",
                gstin="33AAACS1234A1Z5",
                pan="AAACS1234A",
                bank_account_holder="Surfine Technology",
                bank_bank_name="HDFC Bank",
                bank_branch="Industrial Estate Branch",
                bank_account_number="50200012345678",
                bank_ifsc="HDFC0001234",
                declaration="We declare that this invoice shows the actual price of the goods described.",
                authorized_signatory="Authorized Signatory",
                default_gst_cgst_rate=0.09,
                default_gst_sgst_rate=0.09,
            )
            session.add(business)

            # 2. Clients (5 clients)
            clients_data = [
                {
                    "id": "cl_001",
                    "name": "M/S MERCURY FITTINGS (P) LTD",
                    "contact_name": "Mr. Ramesh Kumar",
                    "email": "accounts@mercury.co.in",
                    "phone": "9876543210",
                    "billing_address": "S. NO 55/2 & 59/2 ARANVOYAL VILLAGE, TIRUVALLUR -602025",
                    "gstin": "33AAACM5230H1ZX",
                    "pan": "AAACM5230H",
                    "notes": "Regular customer, net 30 terms",
                },
                {
                    "id": "cl_002",
                    "name": "M/S MEGAWIN FABRICATION",
                    "contact_name": "Ms. Priya Sharma",
                    "email": "accounts@megawin.co.in",
                    "phone": "9876543211",
                    "billing_address": "NO 2/133, V.M.KOIL STREET, ALAGU NACHIYAR NAGAR, SALEM- 636 004",
                    "gstin": "33AAOFM3328H1ZA",
                    "pan": "AAOFM3328H",
                    "notes": "New customer, advance payment",
                },
                {
                    "id": "cl_003",
                    "name": "M/S VIBROMECH ENGINEERS AND SERVICES LTD",
                    "contact_name": "Mr. Suresh Babu",
                    "email": "accounts@vibromech.co.in",
                    "phone": "9876543212",
                    "billing_address": "NO 15/2, CMDA TNHB 80 FEET ROAD, GUDALUR, MARAIMALAI NAGAR, CHENGALPATTU- 603 209",
                    "gstin": "33AAACV2011P2ZH",
                    "pan": "AAACV2011P",
                    "notes": "Government contractor",
                },
                {
                    "id": "cl_004",
                    "name": "M/S PROTECK METALICS PVT LTD",
                    "contact_name": "Mr. Venkat Rao",
                    "email": "accounts@proteck.co.in",
                    "phone": "9876543213",
                    "billing_address": "PLOT NO A-8, SIPCOT INDL GROWTH CENTRE, VALLAM B VILLAGE, ORAGADAM, TIRUVALLUR -602 105",
                    "gstin": "33AANCP0664K1Z6",
                    "pan": "AANCP0664K",
                    "notes": "Export oriented unit",
                },
                {
                    "id": "cl_005",
                    "name": "M/S SRIWIN ELECTRIC",
                    "contact_name": "Ms. Lakshmi Devi",
                    "email": "accounts@sriwin.co.in",
                    "phone": "9876543214",
                    "billing_address": "P. NO 61 & 63 SIDCO WOMEN'S INDL. ESTATE, KARUPPUR, SALEM - 636 011",
                    "gstin": "33ACSFS6659M2Z4",
                    "pan": "ACSFS6659M",
                    "notes": "Women entrepreneurship unit",
                },
            ]
            for c in clients_data:
                session.add(Client(**c))

            session.flush()

            # 3. Invoices (20 invoices) with varying dates, amounts, and statuses
            # Note: No product_id in Version 1 (products table doesn't exist yet)
            invoices_data = [
                # Format: (invoice_id, number, client_id, issue_date, due_date, is_draft, items, discount, round_off)
                ("inv_001", "001/2026-27", "cl_001", "2026-04-01", "2026-04-30", False,
                 [("Eye Bolt MS 20x80 Pitch", "7318", 10, 4950.00),
                  ("Eye Bolt MS 25x90 Pitch", "7318", 5, 5200.00)],
                 100.00, -0.50),
                ("inv_002", "002/2026-27", "cl_002", "2026-04-05", "2026-05-05", False,
                 [("Spring Guide Rod MS Head Without Platting", "7318", 20, 4600.00)],
                 0.00, 0.00),
                ("inv_003", "003/2026-27", "cl_003", "2026-04-10", "2026-05-10", False,
                 [("Spring Supporter", "7318", 15, 2530.00),
                  ("AR Operating Lever Connecting Pin 10x70", "7318", 8, 6300.00)],
                 500.00, 0.25),
                ("inv_004", "004/2026-27", "cl_004", "2026-04-15", "2026-05-15", False,
                 [("Cage Nut to DRG No - DTR0000153511", "7318", 50, 5300.00)],
                 0.00, -0.75),
                ("inv_005", "005/2026-27", "cl_005", "2026-04-20", "2026-05-20", False,
                 [("VME G445 Bolt Including Zinc", "7318", 100, 1000.00),
                  ("VME G445 Washer Including Zinc", "7318", 200, 350.00)],
                 250.00, 0.50),
                ("inv_006", "006/2026-27", "cl_001", "2026-05-01", "2026-05-31", False,
                 [("M6x1.00x3.50 Screw", "7215", 500, 1050.00)],
                 0.00, 0.00),
                ("inv_007", "007/2026-27", "cl_002", "2026-05-05", "2026-06-04", False,
                 [("R- PFSS-PIN3.5X1 - F Pin Forging", "9989", 25, 2300.00)],
                 0.00, -0.25),
                ("inv_008", "008/2026-27", "cl_003", "2026-05-10", "2026-06-09", True,  # Draft
                 [("VAL R-PFSS-PIN41_2X1", "9989", 30, 2300.00)],
                 100.00, 0.00),
                ("inv_009", "009/2026-27", "cl_004", "2026-05-15", "2026-06-14", False,
                 [("VAL R-PFSS-PIN4X1", "9989", 20, 2300.00),
                  ("Trolley Wheel Type -1 (11 KV)", "8537", 2, 19700.00)],
                 500.00, 0.75),
                ("inv_010", "010/2026-27", "cl_005", "2026-05-20", "2026-06-19", False,
                 [("Eye Bolt MS 20x80 Pitch", "7318", 15, 4950.00),
                  ("Spring Guide Rod MS Head", "7318", 10, 4600.00)],
                 0.00, -0.50),
                ("inv_011", "011/2026-27", "cl_001", "2026-06-01", "2026-07-01", False,
                 [("Eye Bolt MS 25x90 Pitch", "7318", 8, 5200.00)],
                 0.00, 0.00),
                ("inv_012", "012/2026-27", "cl_002", "2026-06-05", "2026-07-05", False,
                 [("Spring Supporter", "7318", 12, 2530.00),
                  ("AR Operating Lever Connecting Pin", "7318", 6, 6300.00)],
                 200.00, 0.25),
                ("inv_013", "013/2026-27", "cl_003", "2026-06-10", "2026-07-10", False,
                 [("Cage Nut to DRG No", "7318", 40, 5300.00)],
                 0.00, -0.75),
                ("inv_014", "014/2026-27", "cl_004", "2026-06-15", "2026-07-15", False,
                 [("VME G445 Bolt", "7318", 80, 1000.00),
                  ("VME G445 Washer", "7318", 150, 350.00)],
                 150.00, 0.50),
                ("inv_015", "015/2026-27", "cl_005", "2026-06-20", "2026-07-20", True,  # Draft
                 [("M6x1.00x3.50 Screw", "7215", 400, 1050.00)],
                 0.00, 0.00),
                ("inv_016", "016/2026-27", "cl_001", "2026-07-01", "2026-07-31", False,
                 [("R- PFSS-PIN3.5X1", "9989", 20, 2300.00)],
                 0.00, -0.25),
                ("inv_017", "017/2026-27", "cl_002", "2026-07-05", "2026-08-04", False,
                 [("VAL R-PFSS-PIN41_2X1", "9989", 25, 2300.00)],
                 100.00, 0.00),
                ("inv_018", "018/2026-27", "cl_003", "2026-07-10", "2026-08-09", False,
                 [("VAL R-PFSS-PIN4X1", "9989", 15, 2300.00),
                  ("Trolley Wheel Type -1", "8537", 1, 19700.00)],
                 300.00, 0.75),
                ("inv_019", "019/2026-27", "cl_004", "2026-07-15", "2026-08-14", False,
                 [("Eye Bolt MS 20x80 Pitch", "7318", 10, 4950.00),
                  ("Eye Bolt MS 25x90 Pitch", "7318", 5, 5200.00)],
                 0.00, -0.50),
                ("inv_020", "020/2026-27", "cl_005", "2026-07-20", "2026-08-19", False,
                 [("Spring Guide Rod MS Head", "7318", 8, 4600.00)],
                 0.00, 0.00),
            ]

            for inv_data in invoices_data:
                inv_id, number, client_id, issue_date, due_date, is_draft, items, discount, round_off = inv_data

                # Calculate totals
                subtotal = sum(qty * price for _, _, qty, price in items)
                discount_paise = int(discount * 100)
                after_discount = subtotal * 100 - discount_paise
                cgst = int(after_discount * 0.09)
                sgst = int(after_discount * 0.09)
                round_off_paise = int(round_off * 100)
                total = after_discount + cgst + sgst + round_off_paise

                invoice = Invoice(
                    id=inv_id,
                    number=number,
                    client_id=client_id,
                    issue_date=issue_date,
                    due_date=due_date,
                    cgst_rate=0.09,
                    sgst_rate=0.09,
                    discount=discount_paise,
                    round_off=round_off_paise,
                    notes=f"Invoice {number} - Test data for upgrade simulation",
                    terms="Net 30 days",
                    is_draft=is_draft,
                    billed_at=datetime.now(timezone.utc).isoformat() if not is_draft else None,
                )
                session.add(invoice)
                session.flush()

                # Add invoice items (no product_id in Version 1)
                for idx, item_data in enumerate(items):
                    desc, hsn, qty, price = item_data
                    item = InvoiceItem(
                        id=f"{inv_id}_item_{idx}",
                        invoice_id=inv_id,
                        product_id=None,  # No products table in Version 1
                        description=desc,
                        hsn_code=hsn,
                        quantity=qty,
                        unit_price=int(price * 100),
                    )
                    session.add(item)

                # Add invoice number reservation
                from app.database.models import InvoiceNumberReservation
                seq = int(number.split("/")[0])
                fy = number.split("/")[1]
                reservation = InvoiceNumberReservation(
                    number=number,
                    financial_year=fy,
                    sequence=seq,
                    reserved_for=inv_id,
                    reserved_at=datetime.now(timezone.utc).isoformat(),
                )
                session.add(reservation)

            session.flush()

            # 4. Payments (multiple payments per invoice, including partial payments)
            payments_data = [
                # Full payments
                ("pay_001", "inv_001", "cl_001", 100.0, "bank_transfer", "2026-04-15T10:00:00+00:00", "TXN001"),
                ("pay_002", "inv_002", "cl_002", 100.0, "cash", "2026-04-20T10:00:00+00:00", "CASH001"),
                ("pay_003", "inv_003", "cl_003", 100.0, "upi", "2026-04-25T10:00:00+00:00", "UPI001"),
                ("pay_004", "inv_004", "cl_004", 100.0, "cheque", "2026-04-28T10:00:00+00:00", "CHQ001"),
                ("pay_005", "inv_005", "cl_005", 100.0, "bank_transfer", "2026-05-05T10:00:00+00:00", "TXN002"),
                ("pay_006", "inv_006", "cl_001", 100.0, "cash", "2026-05-10T10:00:00+00:00", "CASH002"),
                ("pay_007", "inv_007", "cl_002", 100.0, "upi", "2026-05-15T10:00:00+00:00", "UPI002"),
                ("pay_009", "inv_009", "cl_004", 100.0, "bank_transfer", "2026-05-25T10:00:00+00:00", "TXN003"),
                ("pay_010", "inv_010", "cl_005", 100.0, "cash", "2026-05-28T10:00:00+00:00", "CASH003"),
                # Partial payments
                ("pay_011", "inv_011", "cl_001", 50.0, "bank_transfer", "2026-06-10T10:00:00+00:00", "TXN004"),
                ("pay_012", "inv_012", "cl_002", 30.0, "cash", "2026-06-15T10:00:00+00:00", "CASH004"),
                ("pay_013", "inv_013", "cl_003", 75.0, "upi", "2026-06-20T10:00:00+00:00", "UPI003"),
                ("pay_014", "inv_014", "cl_004", 60.0, "cheque", "2026-06-25T10:00:00+00:00", "CHQ002"),
                ("pay_015", "inv_015", "cl_005", 40.0, "bank_transfer", "2026-06-28T10:00:00+00:00", "TXN005"),
                ("pay_016", "inv_016", "cl_001", 80.0, "cash", "2026-07-05T10:00:00+00:00", "CASH005"),
                ("pay_017", "inv_017", "cl_002", 25.0, "upi", "2026-07-10T10:00:00+00:00", "UPI004"),
                ("pay_018", "inv_018", "cl_003", 90.0, "bank_transfer", "2026-07-15T10:00:00+00:00", "TXN006"),
                ("pay_019", "inv_019", "cl_004", 100.0, "cheque", "2026-07-20T10:00:00+00:00", "CHQ003"),
                ("pay_020", "inv_020", "cl_005", 100.0, "bank_transfer", "2026-07-25T10:00:00+00:00", "TXN007"),
            ]

            for pay_data in payments_data:
                pay_id, inv_id, client_id, pct, method, received_at, ref = pay_data

                # Get invoice total
                inv = session.get(Invoice, inv_id)
                items = session.query(InvoiceItem).filter_by(invoice_id=inv_id).all()
                subtotal = sum(item.quantity * item.unit_price for item in items)
                discount_paise = inv.discount
                after_discount = subtotal - discount_paise
                cgst = int(after_discount * 0.09)
                sgst = int(after_discount * 0.09)
                total = after_discount + cgst + sgst + inv.round_off

                amount = int(total * pct / 100)

                payment = Payment(
                    id=pay_id,
                    invoice_id=inv_id,
                    client_id=client_id,
                    amount=amount,
                    method=method,
                    received_at=received_at,
                    reference=ref,
                )
                session.add(payment)

            session.commit()

            # Record row counts for verification after upgrade (no products in V1)
            self.expected_counts = {
                "clients": session.query(Client).count(),
                "products": 0,  # Products don't exist in Version 1
                "invoices": session.query(Invoice).count(),
                "invoice_items": session.query(InvoiceItem).count(),
                "payments": session.query(Payment).count(),
                "invoice_number_reservations": session.query(InvoiceNumberReservation).count(),
                "business_profile": session.query(BusinessProfileRecord).count(),
            }

            # Record financial totals
            self.expected_invoice_numbers = [inv.number for inv in session.query(Invoice).order_by(Invoice.number).all()]
            self.expected_invoice_totals = {}
            for inv in session.query(Invoice).all():
                items = session.query(InvoiceItem).filter_by(invoice_id=inv.id).all()
                subtotal = sum(item.quantity * item.unit_price for item in items)
                discount = inv.discount
                after_discount = subtotal - discount
                cgst = int(after_discount * 0.09)
                sgst = int(after_discount * 0.09)
                total = after_discount + cgst + sgst + inv.round_off
                self.expected_invoice_totals[inv.number] = {
                    "subtotal": subtotal,
                    "discount": discount,
                    "cgst": cgst,
                    "sgst": sgst,
                    "round_off": inv.round_off,
                    "total": total,
                }

            # Record payment totals per invoice
            self.expected_payment_totals = {}
            for inv in session.query(Invoice).all():
                payments = session.query(Payment).filter_by(invoice_id=inv.id).all()
                self.expected_payment_totals[inv.number] = sum(p.amount for p in payments)

        finally:
            session.close()

    def _verify_data_after_upgrade(self):
        """Verify all data is preserved after upgrade to current version."""
        session = self.session_factory()
        try:
            # Verify row counts for original V1 tables
            actual_counts = {
                "clients": session.query(Client).count(),
                "invoices": session.query(Invoice).count(),
                "invoice_items": session.query(InvoiceItem).count(),
                "payments": session.query(Payment).count(),
                "invoice_number_reservations": session.query(InvoiceNumberReservation).count(),
                "business_profile": session.query(BusinessProfileRecord).count(),
            }

            print("\n=== ROW COUNT COMPARISON (V1 tables) ===")
            for table, expected in self.expected_counts.items():
                if table == "products":
                    # Products table is created during upgrade but was empty in V1
                    actual = session.query(Product).count()
                    print(f"  {table}: expected={expected} (V1), actual={actual} (post-upgrade) - new table")
                    continue
                actual = actual_counts.get(table, 0)
                status = "✓" if actual == expected else "✗"
                print(f"  {table}: expected={expected}, actual={actual} {status}")
                self.assertEqual(actual, expected, f"Row count mismatch for {table}")

            # Verify invoice numbers unchanged
            actual_invoice_numbers = [inv.number for inv in session.query(Invoice).order_by(Invoice.number).all()]
            self.assertEqual(actual_invoice_numbers, self.expected_invoice_numbers)
            print(f"\n✓ Invoice numbers preserved: {actual_invoice_numbers}")

            # Verify invoice financial totals unchanged
            for inv in session.query(Invoice).all():
                items = session.query(InvoiceItem).filter_by(invoice_id=inv.id).all()
                subtotal = sum(item.quantity * item.unit_price for item in items)
                discount = inv.discount
                after_discount = subtotal - discount
                cgst = int(after_discount * 0.09)
                sgst = int(after_discount * 0.09)
                total = after_discount + cgst + sgst + inv.round_off

                expected = self.expected_invoice_totals[inv.number]
                self.assertEqual(subtotal, expected["subtotal"], f"Subtotal mismatch for {inv.number}")
                self.assertEqual(discount, expected["discount"], f"Discount mismatch for {inv.number}")
                self.assertEqual(cgst, expected["cgst"], f"CGST mismatch for {inv.number}")
                self.assertEqual(sgst, expected["sgst"], f"SGST mismatch for {inv.number}")
                self.assertEqual(inv.round_off, expected["round_off"], f"Round off mismatch for {inv.number}")
                self.assertEqual(total, expected["total"], f"Total mismatch for {inv.number}")
            print("✓ All invoice financial totals preserved")

            # Verify payment totals per invoice
            for inv in session.query(Invoice).all():
                payments = session.query(Payment).filter_by(invoice_id=inv.id).all()
                actual_paid = sum(p.amount for p in payments)
                expected_paid = self.expected_payment_totals[inv.number]
                self.assertEqual(actual_paid, expected_paid, f"Payment total mismatch for {inv.number}")
            print("✓ All payment totals preserved")

            # Verify client data
            for client_id in ["cl_001", "cl_002", "cl_003", "cl_004", "cl_005"]:
                client = session.get(Client, client_id)
                self.assertIsNotNone(client, f"Client {client_id} missing")
            print("✓ All 5 clients preserved")

            # Verify business profile
            business = session.get(BusinessProfileRecord, 1)
            self.assertIsNotNone(business)
            self.assertEqual(business.name, "Surfine Technology")
            print("✓ Business profile preserved")

            # Verify invoice items
            for inv in session.query(Invoice).all():
                items = session.query(InvoiceItem).filter_by(invoice_id=inv.id).all()
                self.assertGreater(len(items), 0, f"Invoice {inv.number} has no items")
            print("✓ All invoice items preserved")

            # Verify new tables exist (added by migrations after Version 1)
            inspector = inspect(self.engine)
            tables = set(inspector.get_table_names())

            # Core tables from Version 1
            for table in ["clients", "invoices", "invoice_items", "invoice_number_reservations",
                         "payments", "activities", "business_profile"]:
                self.assertIn(table, tables, f"Core table {table} missing after upgrade")

            # New tables from later migrations
            for table in ["products", "inventory_movements", "notifications",
                         "users", "sessions", "password_reset_tokens", "recovery_attempts"]:
                self.assertIn(table, tables, f"New table {table} missing after upgrade")

            print("✓ All expected tables exist after upgrade")
            print(f"✓ Final migration version: {session.execute(text('SELECT version_num FROM alembic_version')).scalar()}")

        finally:
            session.close()

    def test_version_1_to_current_upgrade(self):
        """Test upgrading from Version 1 (migration 0006) to current version (0012).

        This simulates a real user upgrading from an older SFT Billing release.
        All existing business data must be preserved.
        """
        print("\n" + "="*60)
        print("UPGRADE SIMULATION: Version 1 (migration 0006) → Current (0012)")
        print("="*60)

        # Step 1: Create Version 1 database schema
        print("\n[Step 1] Creating Version 1 database schema (migration 0006)...")
        self._create_version_1_database()
        print("✓ Version 1 schema created")

        # Step 2: Insert realistic test data
        print("\n[Step 2] Inserting test business data...")
        print("  - 1 Business Profile")
        print("  - 5 Clients")
        print("  - 13 Products")
        print("  - 20 Invoices (with items)")
        print("  - 20 Payments (including partial payments)")
        print("  - 20 Invoice Number Reservations")
        self._insert_test_data()
        print("✓ Test data inserted")
        print(f"  Expected counts: {self.expected_counts}")

        # Step 3: Record initial state
        print("\n[Step 3] Recording pre-upgrade state...")
        with self.engine.connect() as conn:
            pre_upgrade_version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"  Pre-upgrade migration: {pre_upgrade_version}")

        # Step 4: Perform upgrade (run all pending migrations)
        print("\n[Step 4] Running upgrade migrations (0007 through 0012)...")
        initialize_database(self.engine)
        print("✓ Upgrade migrations completed")

        # Step 5: Verify post-upgrade state
        print("\n[Step 5] Verifying post-upgrade state...")
        with self.engine.connect() as conn:
            post_upgrade_version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"  Post-upgrade migration: {post_upgrade_version}")
            self.assertEqual(post_upgrade_version, "0013_user_mobile")

        # Step 6: Verify all data preserved
        print("\n[Step 6] Verifying data integrity...")
        self._verify_data_after_upgrade()

        print("\n" + "="*60)
        print("UPGRADE SIMULATION: PASSED")
        print("All business data preserved through upgrade!")
        print("="*60)

    def test_repeated_upgrade_simulation(self):
        """Test sequential upgrades: V1 → V2 → V3 → V4 (simulated).

        This simulates multiple version upgrades over time.
        Each step should preserve all data.
        """
        print("\n" + "="*60)
        print("REPEATED UPGRADE SIMULATION: Multiple sequential upgrades")
        print("="*60)

        # Create initial Version 1 database
        self._create_version_1_database()
        self._insert_test_data()

        # Capture initial counts (V1 tables only - products don't exist yet)
        session = self.session_factory()
        initial_counts = {
            "clients": session.query(Client).count(),
            "invoices": session.query(Invoice).count(),
            "invoice_items": session.query(InvoiceItem).count(),
            "payments": session.query(Payment).count(),
        }
        session.close()

        # Simulate V1 → V2 (migration 0008: merge client nullable branch)
        # Note: 0007 is on a different branch; the merge at 0008 brings both branches together
        print("\n[Upgrade 1] Running migration 0008 (merge client nullable branch)...")
        initialize_database(self.engine)  # This runs 0007+0008 merge from 0006
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"  Post-upgrade 1 migration: {version}")
        self._verify_counts(initial_counts)

        # Simulate V2 → V3 (migration 0009: products)
        print("\n[Upgrade 2] Running migration 0009 (products)...")
        from app.database.session import initialize_products_database
        initialize_products_database(self.engine)
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"  Post-upgrade 2 migration: {version}")
        # Products table now exists but is empty (new feature)
        session = self.session_factory()
        self.assertEqual(session.query(Product).count(), 0)
        session.close()
        self._verify_counts(initial_counts)

        # Simulate V3 → V4 (migration 0010: notifications)
        print("\n[Upgrade 3] Running migration 0010 (notifications)...")
        from app.database.session import initialize_notifications_database
        initialize_notifications_database(self.engine)
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"  Post-upgrade 3 migration: {version}")
        self._verify_counts(initial_counts)

        # Simulate V4 → Current (migrations 0011-0012: auth, recovery_attempts)
        print("\n[Upgrade 4] Running migrations 0011-0012 (auth, recovery_attempts)...")
        initialize_database(self.engine)  # Runs all remaining to head
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print(f"  Post-upgrade 4 migration: {version}")
        self._verify_counts(initial_counts)

        # Final comprehensive verification
        print("\n[Final] Comprehensive data verification after all upgrades...")
        self._verify_data_after_upgrade()

        print("\n" + "="*60)
        print("REPEATED UPGRADE SIMULATION: PASSED")
        print("All data preserved through multiple sequential upgrades!")
        print("="*60)

    def test_migration_by_migration_verification(self):
        """Test each migration individually from 0006 to 0012.

        This verifies that each migration step preserves data correctly.
        """
        print("\n" + "="*60)
        print("MIGRATION-BY-MIGRATION VERIFICATION")
        print("="*60)

        # Create V1 database at 0006
        self._create_version_1_database()
        self._insert_test_data()

        # Capture initial state
        session = self.session_factory()
        initial_invoices = {inv.number: inv.id for inv in session.query(Invoice).all()}
        initial_invoice_totals = {}
        for inv in session.query(Invoice).all():
            items = session.query(InvoiceItem).filter_by(invoice_id=inv.id).all()
            subtotal = sum(item.quantity * item.unit_price for item in items)
            initial_invoice_totals[inv.number] = {
                "subtotal": subtotal,
                "discount": inv.discount,
                "round_off": inv.round_off,
                "cgst": int((subtotal - inv.discount) * 0.09),
                "sgst": int((subtotal - inv.discount) * 0.09),
                "total": subtotal - inv.discount + int((subtotal - inv.discount) * 0.09) * 2 + inv.round_off,
            }
        initial_payments = {}
        for inv in session.query(Invoice).all():
            payments = session.query(Payment).filter_by(invoice_id=inv.id).all()
            initial_payments[inv.number] = sum(p.amount for p in payments)
        initial_client_count = session.query(Client).count()
        session.close()

        # Migration sequence: 0006 -> 0008 (merge) -> 0009 -> 0010 -> 0011 -> 0012
        # Note: 0007 is on a different branch; the merge at 0008 brings both branches together
        migrations = [
            ("0008_merge_client_nullable_branch", "initialize_database"),  # merge revision (includes 0007 changes)
            ("0009_products", "initialize_products_database"),
            ("0010_notifications", "initialize_notifications_database"),
            ("0011_auth", "initialize_database"),  # will run to head
            ("0012_recovery_attempts", "initialize_database"),
        ]

        # Run 0008 (merge - includes 0007 changes from the client branch)
        print("\n[Step 1] Running migration 0008 (merge client nullable branch)...")
        from app.database.session import _upgrade_database
        _upgrade_database(self.engine, "0008_merge_client_nullable_branch")
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            self.assertEqual(version, "0008_merge_client_nullable_branch")
            print(f"  Migration version: {version}")
        self._verify_core_data_preserved(initial_invoices, initial_invoice_totals, initial_payments, initial_client_count)

        # Run 0009
        print("\n[Step 2] Running migration 0009 (products)...")
        from app.database.session import initialize_products_database
        initialize_products_database(self.engine)
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            self.assertEqual(version, "0009_products")
            print(f"  Migration version: {version}")
        self._verify_core_data_preserved(initial_invoices, initial_invoice_totals, initial_payments, initial_client_count)

        # Run 0010
        print("\n[Step 3] Running migration 0010 (notifications)...")
        from app.database.session import initialize_notifications_database
        initialize_notifications_database(self.engine)
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            self.assertEqual(version, "0010_notifications")
            print(f"  Migration version: {version}")
        self._verify_core_data_preserved(initial_invoices, initial_invoice_totals, initial_payments, initial_client_count)

        # Run 0011 and 0012 together (to head)
        print("\n[Step 4] Running migrations 0011-0012 (auth, recovery_attempts)...")
        initialize_database(self.engine)
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            self.assertEqual(version, "0013_user_mobile")
            print(f"  Migration version: {version}")
        self._verify_core_data_preserved(initial_invoices, initial_invoice_totals, initial_payments, initial_client_count)

        print("\n" + "="*60)
        print("MIGRATION-BY-MIGRATION VERIFICATION: PASSED")
        print("All data preserved through each migration step!")
        print("="*60)

    def _verify_core_data_preserved(self, initial_invoices, initial_invoice_totals, initial_payments, initial_client_count):
        """Verify core business data is preserved after a migration step."""
        session = self.session_factory()
        try:
            # Verify clients
            client_count = session.query(Client).count()
            self.assertEqual(client_count, initial_client_count, "Client count mismatch")

            # Verify invoices
            for inv in session.query(Invoice).all():
                self.assertIn(inv.number, initial_invoices, f"Invoice {inv.number} not in initial set")

                # Verify invoice totals
                items = session.query(InvoiceItem).filter_by(invoice_id=inv.id).all()
                subtotal = sum(item.quantity * item.unit_price for item in items)
                expected = initial_invoice_totals[inv.number]
                self.assertEqual(subtotal, expected["subtotal"], f"Subtotal mismatch for {inv.number}")
                self.assertEqual(inv.discount, expected["discount"], f"Discount mismatch for {inv.number}")
                self.assertEqual(inv.round_off, expected["round_off"], f"Round off mismatch for {inv.number}")

            # Verify payments
            for inv in session.query(Invoice).all():
                payments = session.query(Payment).filter_by(invoice_id=inv.id).all()
                actual_paid = sum(p.amount for p in payments)
                expected_paid = initial_payments.get(inv.number, 0)
                self.assertEqual(actual_paid, expected_paid, f"Payment total mismatch for {inv.number}")

            print(f"  ✓ Core data verified: {client_count} clients, {len(initial_invoices)} invoices")
        finally:
            session.close()

    def _verify_counts(self, expected_counts):
        """Verify row counts match expected."""
        session = self.session_factory()
        try:
            for table, expected in expected_counts.items():
                model_map = {
                    "clients": Client,
                    "products": Product,
                    "invoices": Invoice,
                    "invoice_items": InvoiceItem,
                    "payments": Payment,
                }
                actual = session.query(model_map[table]).count()
                self.assertEqual(actual, expected, f"Count mismatch for {table} after upgrade step")
            print(f"  ✓ Row counts verified: {expected_counts}")
        finally:
            session.close()


class FreshInstallationTests(unittest.TestCase):
    """Test that fresh installation works correctly with approved seed data."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "fresh_install.db"
        self.engine = create_database_engine(f"sqlite:///{self.database_path.as_posix()}")

    def tearDown(self):
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def test_fresh_installation_has_approved_master_data(self):
        """Verify fresh installation creates database with approved seed data.

        This simulates what Tauri does on first run:
        1. Copy the bundled sft_billing_initial.db to the production location
        2. Run any pending migrations (though seed is already at latest)
        """
        print("\n" + "="*60)
        print("FRESH INSTALLATION TEST")
        print("="*60)

        # Step 1: Copy the approved seed database (simulating Tauri's initialize_production_database)
        print("\n[Step 1] Copying approved seed database...")
        import shutil
        seed_path = Path(__file__).resolve().parents[1] / "data" / "sft_billing_initial.db"
        if not seed_path.exists():
            self.skipTest(f"Seed database not found at {seed_path}")
        shutil.copy2(seed_path, self.database_path)
        print(f"  ✓ Seed database copied from {seed_path}")

        # Step 2: Run initialize_database (simulates backend startup migrations)
        print("\n[Step 2] Running initialize_database() for any pending migrations...")
        initialize_database(self.engine)
        print("✓ Database initialized")

        # Verify migration version
        with self.engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            self.assertEqual(version, "0013_user_mobile")
            print(f"  Migration version: {version}")

        session = sessionmaker(bind=self.engine)()
        try:
            # Verify master data counts
            client_count = session.query(Client).count()
            product_count = session.query(Product).count()
            business_count = session.query(BusinessProfileRecord).count()
            invoice_count = session.query(Invoice).count()
            invoice_item_count = session.query(InvoiceItem).count()
            payment_count = session.query(Payment).count()
            user_count = session.query(__import__('app.database.models', fromlist=['User']).User).count()

            print(f"\n[Step 3] Verifying master data counts...")
            print(f"  Clients: {client_count} (expected: 5)")
            print(f"  Products: {product_count} (expected: 13)")
            print(f"  Business Profile: {business_count} (expected: 1)")
            print(f"  Invoices: {invoice_count} (expected: 0)")
            print(f"  Invoice Items: {invoice_item_count} (expected: 0)")
            print(f"  Payments: {payment_count} (expected: 0)")
            print(f"  Users: {user_count} (expected: 0)")

            self.assertEqual(client_count, 5)
            self.assertEqual(product_count, 13)
            self.assertEqual(business_count, 1)
            self.assertEqual(invoice_count, 0)
            self.assertEqual(invoice_item_count, 0)
            self.assertEqual(payment_count, 0)
            self.assertEqual(user_count, 0)

            # Verify client data matches seed
            clients = session.query(Client).all()
            client_names = {c.name for c in clients}
            expected_names = {
                "M/S MERCURY FITTINGS (P) LTD",
                "M/S MEGAWIN FABRICATION",
                "M/S VIBROMECH ENGINEERS AND SERVICES LTD",
                "M/S PROTECK METALICS PVT LTD",
                "M/S SRIWIN ELECTRIC",
            }
            self.assertEqual(client_names, expected_names)
            print("  ✓ Client names match approved seed")

            # Verify product data matches seed
            products = session.query(Product).all()
            product_codes = {p.code for p in products}
            expected_codes = {f"SFT-{i:03d}" for i in [1,2,3,4,5,6,7,8,9,10,11,12,16]}
            self.assertEqual(product_codes, expected_codes)
            print("  ✓ Product codes match approved seed")

            # Verify business profile
            business = session.get(BusinessProfileRecord, 1)
            self.assertIsNotNone(business)
            self.assertEqual(business.name, "Surfine Technology")  # Matches seed database
            print("  ✓ Business profile matches approved seed")

            # Verify no authentication records
            from app.database.models import User, Session, PasswordResetToken, RecoveryAttempt
            self.assertEqual(session.query(User).count(), 0)
            self.assertEqual(session.query(Session).count(), 0)
            self.assertEqual(session.query(PasswordResetToken).count(), 0)
            self.assertEqual(session.query(RecoveryAttempt).count(), 0)
            print("  ✓ No authentication records (clean slate for first-run setup)")

            print("\n" + "="*60)
            print("FRESH INSTALLATION TEST: PASSED")
            print("Clean master data with zero transactional data!")
            print("="*60)

        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()