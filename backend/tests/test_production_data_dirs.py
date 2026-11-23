import tempfile
import unittest
from pathlib import Path

from app.excel.workbook import BASE_DIR, _resolve_application_data_dir


class ProductionDataDirectoryTests(unittest.TestCase):
    def test_development_data_remains_backend_relative(self):
        self.assertEqual(_resolve_application_data_dir(is_frozen=False), BASE_DIR)

    def test_frozen_data_uses_local_appdata(self):
        with tempfile.TemporaryDirectory() as local_appdata:
            self.assertEqual(
                _resolve_application_data_dir(
                    is_frozen=True,
                    local_appdata=local_appdata,
                ),
                Path(local_appdata) / "SFT Billing",
            )

    def test_frozen_data_requires_local_appdata(self):
        with self.assertRaisesRegex(RuntimeError, "LOCALAPPDATA is required"):
            _resolve_application_data_dir(is_frozen=True, local_appdata="")
