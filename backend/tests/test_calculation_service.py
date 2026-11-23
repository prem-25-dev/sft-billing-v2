import unittest

from app.services.calculation_service import amount_in_words, compute_invoice_totals


class AmountInWordsTests(unittest.TestCase):
    def test_calculated_total_rounding_does_not_leave_one_hundred_paise(self):
        totals = compute_invoice_totals(
            [{"quantity": 1, "unitPrice": 6210}],
            cgst_rate=0.09,
            sgst_rate=0.09,
            discount=0,
            round_off=0.2,
        )

        self.assertEqual(totals["total"], 7328.0)
        self.assertEqual(
            totals["amountInWords"],
            "Seven Thousand Three Hundred Twenty Eight Rupees Only",
        )

    def test_exact_amounts_and_paise(self):
        self.assertEqual(
            amount_in_words(7328.0),
            "Seven Thousand Three Hundred Twenty Eight Rupees Only",
        )
        self.assertEqual(
            amount_in_words(7328.5),
            "Seven Thousand Three Hundred Twenty Eight Rupees and Fifty Paise Only",
        )

    def test_rounding_across_whole_rupee_carries_paise(self):
        self.assertEqual(
            amount_in_words(7327.999999999),
            "Seven Thousand Three Hundred Twenty Eight Rupees Only",
        )

    def test_zero_and_indian_numbering_boundaries(self):
        cases = (
            (0, "Zero Rupees Only"),
            (100000, "One Lakh Rupees Only"),
            (10000000, "One Crore Rupees Only"),
        )
        for amount, expected in cases:
            with self.subTest(amount=amount):
                self.assertEqual(amount_in_words(amount), expected)


if __name__ == "__main__":
    unittest.main()
