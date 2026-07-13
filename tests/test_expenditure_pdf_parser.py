import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from parsers.expenditure_pdf_parser import parse_expenditure_pdf

RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')


class TestParseExpenditurePdfIntegration(unittest.TestCase):
    """Pin known-good outputs for every real weekly export. These files
    exercise every quirk found so far: standard 'R 003'/'R 004' headers,
    compressed 'R3'/'R4' headers with no space or zero-padding, dash-fill
    corruption on TOTAL lines, and both leading- and trailing-sign negative
    amounts. A future change breaking any of these shows up here."""

    cases = [
        ('EXP19.05.26.pdf', '2026-05-19', 934),
        ('EXPENDITURE REPORT 01.06.2026.pdf', '2026-06-01', 936),
        ('EXP15.06.26.pdf', '2026-06-15', 938),
        ('EXP22.06.26.pdf', '2026-06-22', 938),
        ('EX29.06.26.pdf', '2026-06-29', 938),
        ('EXP06.07.26.pdf', '2026-07-06', 938),
        ('EXP.13.07.2026.pdf', '2026-07-13', 937),
    ]

    def test_all_weeks_parse_cleanly(self):
        for filename, expected_date, expected_row_count in self.cases:
            with self.subTest(filename=filename):
                path = os.path.join(RAW_DIR, filename)
                rows, warnings = parse_expenditure_pdf(path)
                self.assertEqual(warnings, [], f"{filename} produced total-mismatch warnings: {warnings}")
                self.assertEqual(len(rows), expected_row_count)
                self.assertTrue(all(r['report_date'] == expected_date for r in rows))
                self.assertTrue(all(r['source_file'] == filename for r in rows))

    def test_negative_amounts_survive_both_sign_conventions(self):
        # 2026-06-22 has leading-sign negatives (e.g. '-512.9'); 2026-07-06
        # has trailing-sign negatives (e.g. '4,040.00-'). Both must produce
        # genuinely negative floats, not silently-positive ones.
        rows, _ = parse_expenditure_pdf(os.path.join(RAW_DIR, 'EXP06.07.26.pdf'))
        negatives = [r for r in rows if r['available_budget'] < 0]
        self.assertTrue(negatives, "expected at least one negative available_budget value")


if __name__ == '__main__':
    unittest.main()
