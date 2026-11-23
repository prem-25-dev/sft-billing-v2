import unittest

from app.services.historical_reservation_parser import (
    parse_historical_reservation,
)


class HistoricalReservationParserTests(unittest.TestCase):
    def test_audited_numbers_derive_sequence_and_financial_year(self):
        expected_sequences = {
            "001/2026-27": 1,
            "006/2026-27": 6,
            "011/2026-27": 11,
            "015/2026-27": 15,
            "023/2026-27": 23,
            "029/2026-27": 29,
        }

        for number, expected_sequence in expected_sequences.items():
            with self.subTest(number=number):
                parsed = parse_historical_reservation(number)
                self.assertEqual(parsed.number, number)
                self.assertEqual(parsed.financial_year, "2026-27")
                self.assertEqual(parsed.sequence, expected_sequence)
                self.assertEqual(parsed.source_mismatches, ())

    def test_source_mismatches_are_reported_without_changing_derived_values(self):
        parsed = parse_historical_reservation(
            "011/2026-27",
            source_financial_year="2025-26",
            source_sequence=2,
        )

        self.assertEqual(parsed.financial_year, "2026-27")
        self.assertEqual(parsed.sequence, 11)
        self.assertEqual(
            [(mismatch.field, mismatch.source_value, mismatch.derived_value)
             for mismatch in parsed.source_mismatches],
            [
                ("financialYear", "2025-26", "2026-27"),
                ("sequence", 2, 11),
            ],
        )

    def test_audited_redundant_sequence_values_report_four_mismatches(self):
        source_sequences = {
            "001/2026-27": 1,
            "006/2026-27": 6,
            "011/2026-27": 2,
            "015/2026-27": 3,
            "023/2026-27": 4,
            "029/2026-27": 5,
        }

        mismatch_rows = {
            number: parsed.source_mismatches
            for number, source_sequence in source_sequences.items()
            if (parsed := parse_historical_reservation(
                number,
                source_financial_year="2026-27",
                source_sequence=source_sequence,
            )).source_mismatches
        }

        self.assertEqual(
            {
                number: mismatch[0].derived_value
                for number, mismatch in mismatch_rows.items()
            },
            {
                "011/2026-27": 11,
                "015/2026-27": 15,
                "023/2026-27": 23,
                "029/2026-27": 29,
            },
        )

    def test_non_integer_source_sequence_is_reported_as_a_mismatch(self):
        parsed = parse_historical_reservation(
            "006/2026-27",
            source_sequence="not-a-sequence",
        )

        self.assertEqual(parsed.sequence, 6)
        self.assertEqual(
            [(mismatch.field, mismatch.derived_value)
             for mismatch in parsed.source_mismatches],
            [("sequence", 6)],
        )

    def test_malformed_number_is_rejected(self):
        for number in (
            "",
            "0/2026-27",
            "000/2026-27",
            "001/2026-28",
            "1000/2026-27",
            "001-2026-27",
        ):
            with self.subTest(number=number):
                with self.assertRaises(ValueError):
                    parse_historical_reservation(number)


if __name__ == "__main__":
    unittest.main()
