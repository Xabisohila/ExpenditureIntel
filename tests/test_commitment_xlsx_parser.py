import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from parsers.commitment_xlsx_parser import parse_level_code, extract_description, parse_commitment_workbook

RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')


class TestParseLevelCode(unittest.TestCase):
    def test_none_is_not_a_level(self):
        self.assertIsNone(parse_level_code(None))

    def test_standard_letter_space_number(self):
        self.assertEqual(parse_level_code('F 002'), ('F', 2, False))
        self.assertEqual(parse_level_code('R 003'), ('R', 3, False))
        self.assertEqual(parse_level_code('R 004'), ('R', 4, False))
        self.assertEqual(parse_level_code('I 004'), ('I', 4, False))

    def test_total_prefix_with_double_space(self):
        self.assertEqual(parse_level_code('TOTAL  I 003'), ('I', 3, True))
        self.assertEqual(parse_level_code('TOTAL  R 004'), ('R', 4, True))

    def test_bare_int_is_treated_as_r_level(self):
        # One week's export drops the 'R' letter entirely, leaving a bare
        # int in the TYPE column instead of 'R 003' / 'R 004'.
        self.assertEqual(parse_level_code(3), ('R', 3, False))
        self.assertEqual(parse_level_code(4), ('R', 4, False))

    def test_non_level_text_returns_none(self):
        self.assertIsNone(parse_level_code('--- ORDER NO : OR-084970   001  6820111001----------------------'))
        self.assertIsNone(parse_level_code('====HARVEY WORLD TRAVEL E'))


class TestExtractDescription(unittest.TestCase):
    def test_single_column_description(self):
        row = [None, 'CATERING:DEPARTMENTL ACTIVIT', None, None, None]
        self.assertEqual(extract_description(row, 1, 2), 'CATERING:DEPARTMENTL ACTIVIT')

    def test_mid_word_split_across_spacer_column_is_concatenated_not_joined(self):
        # The 6-column layout splits a long description mid-word across the
        # description column and its spacer overflow column, with no space
        # in the source between the fragments.
        row = ['I 006', 'AUDIT FEES:EXT PREVIOUS YEA', 'R', None, None, None]
        self.assertEqual(extract_description(row, 1, 3), 'AUDIT FEES:EXT PREVIOUS YEAR')

    def test_empty_columns_are_skipped(self):
        row = [None, 'GOODS AND SERVICES', None, None, None]
        self.assertEqual(extract_description(row, 1, 3), 'GOODS AND SERVICES')


class TestParseCommitmentWorkbookIntegration(unittest.TestCase):
    """Pin known-good outputs for every real weekly export so a future
    change to the parser (or a new week's file with a similar quirk) shows
    up as a test failure instead of silently reintroducing a bug."""

    cases = [
        ('COM19.05.26.xlsx', '2026-05-19', 116),
        ('COMMITMENT REPORT 01.06.2026.xlsx', '2026-06-01', 176),
        ('COM15.06.26.xlsx', '2026-06-15', 162),
        ('COM22.06.26.xlsx', '2026-06-22', 182),
        ('COM29.06.26.xlsx', '2026-06-29', 165),
        ('COM06.07.26.xlsx', '2026-07-06', 129),
        ('COMM13.07.26.xlsx', '2026-07-13', 118),
    ]

    def test_all_weeks_parse_cleanly(self):
        for filename, expected_date, expected_row_count in self.cases:
            with self.subTest(filename=filename):
                path = os.path.join(RAW_DIR, filename)
                rows, warnings = parse_commitment_workbook(path)
                self.assertEqual(warnings, [], f"{filename} produced total-mismatch warnings: {warnings}")
                self.assertEqual(len(rows), expected_row_count)
                self.assertTrue(all(r['report_date'] == expected_date for r in rows))
                self.assertTrue(all(r['source_file'] == filename for r in rows))


if __name__ == '__main__':
    unittest.main()
