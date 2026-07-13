import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from parsers.common import clean_amount, split_trailing_amounts, parse_report_date_from_text


class TestCleanAmount(unittest.TestCase):
    def test_none_and_blank(self):
        self.assertEqual(clean_amount(None), 0.0)
        self.assertEqual(clean_amount(''), 0.0)
        self.assertEqual(clean_amount('-'), 0.0)

    def test_passthrough_numeric_types(self):
        self.assertEqual(clean_amount(4240), 4240.0)
        self.assertEqual(clean_amount(4240.5), 4240.5)

    def test_comma_formatted_string(self):
        self.assertEqual(clean_amount('4,240.00'), 4240.0)
        self.assertEqual(clean_amount('108,075.16'), 108075.16)
        self.assertEqual(clean_amount('500'), 500.0)

    def test_leading_negative_sign(self):
        self.assertEqual(clean_amount('-57,349.19'), -57349.19)
        self.assertEqual(clean_amount('-512.9'), -512.9)

    def test_trailing_negative_sign(self):
        # COBOL-style trailing sign, seen in one week's PDF export.
        self.assertEqual(clean_amount('4,040.00-'), -4040.0)
        self.assertEqual(clean_amount('22,183.02-'), -22183.02)

    def test_dash_fill_corruption_is_stripped_not_treated_as_sign(self):
        # Multiple dashes indicate mainframe dash-fill bleeding into the
        # number (TOTAL-line corruption), not a genuine negative sign.
        self.assertEqual(clean_amount('--------1-,019,446.23'), 1019446.23)
        self.assertEqual(clean_amount('2--,-529,810.44'), 2529810.44)
        self.assertEqual(clean_amount('1-,-5-10,402.34'), 1510402.34)


class TestSplitTrailingAmounts(unittest.TestCase):
    def test_normal_leaf_line(self):
        text = 'S&W:BASIC SALARY (RES) 835,333.30 0 4,058,000.00 3,222,666.70'
        desc, amounts = split_trailing_amounts(text, 4)
        self.assertEqual(desc, 'S&W:BASIC SALARY (RES)')
        self.assertEqual(amounts, ['835,333.30', '0', '4,058,000.00', '3,222,666.70'])

    def test_header_line_with_no_amounts_returns_none(self):
        self.assertIsNone(split_trailing_amounts('COMPENSATION OF EMPLOYEES', 4))
        self.assertIsNone(split_trailing_amounts('GOODS AND SERVICES', 4))

    def test_description_ending_in_comma_is_not_mistaken_for_an_amount(self):
        # 'ECONO,' must not be treated as a numeric field just because it
        # ends in a punctuation character that's part of the amount charset.
        self.assertIsNone(split_trailing_amounts('ECONO, TRADE AND ADVISORY', 4))

    def test_dash_glued_total_line(self):
        text = ('EXEC SUP & STAKEHOLD MANAG (DDG) --------1-,019,446.23 '
                '55,161.12 5,047,160.00 3,972,552.65')
        desc, amounts = split_trailing_amounts(text, 4)
        self.assertEqual(desc, 'EXEC SUP & STAKEHOLD MANAG (DDG)')
        self.assertEqual(amounts[0], '--------1-,019,446.23')
        self.assertEqual(amounts[1:], ['55,161.12', '5,047,160.00', '3,972,552.65'])

    def test_no_space_before_dash_fill(self):
        text = 'COMPENSATION OF EMPLOYEES-----------------1,227,426.07 0 6,159,000.00 4,931,573.93'
        desc, amounts = split_trailing_amounts(text, 4)
        self.assertEqual(desc, 'COMPENSATION OF EMPLOYEES')
        self.assertEqual(amounts[0], '-----------------1,227,426.07')


class TestReportDateExtraction(unittest.TestCase):
    def test_extracts_and_normalizes_date(self):
        self.assertEqual(parse_report_date_from_text('DATE: 22/06/2026'), '2026-06-22')
        self.assertEqual(
            parse_report_date_from_text('BAS DATE: 01/06/2026\nTIME: 08:17:58'),
            '2026-06-01',
        )

    def test_no_date_present_returns_none(self):
        self.assertIsNone(parse_report_date_from_text('REPORT INTRODUCTORY PAGE'))


if __name__ == '__main__':
    unittest.main()
