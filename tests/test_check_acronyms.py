#!/usr/bin/env python3
"""Tests for scripts/check_acronyms.py.

Standard library only (unittest), to match the checker's zero-dependency
policy. Run from the repo root:

    python -m unittest discover -s tests -v

The interesting cases build a small but fully valid cheat sheet in a temp
directory, confirm it passes, then mutate one thing at a time and assert the
matching rule fires. That way the tests fail if a future edit weakens any
single check.
"""

import sys
import textwrap
import unittest
from pathlib import Path

# Make the checker importable without installing anything.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_acronyms as ca  # noqa: E402


def make_pdf(pages: int = 2) -> bytes:
    """Build minimal PDF-ish bytes with a controllable /Type /Page count.

    The checker only looks for a %PDF- header, a %%EOF trailer, and counts
    '/Type /Page' objects (excluding '/Type /Pages'), so this is enough to
    exercise every PDF branch without a real PDF library.
    """
    body = b"%PDF-1.4\n"
    body += b"1 0 obj\n<< /Type /Pages /Kids [] /Count %d >>\nendobj\n" % pages
    for i in range(pages):
        body += b"%d 0 obj\n<< /Type /Page >>\nendobj\n" % (i + 2)
    body += b"trailer\n<< >>\n%%EOF\n"
    return body


# A valid cheat sheet: 3 acronyms across 2 topics, a 2-page PDF.
VALID_README = textwrap.dedent(
    """\
    # Test Cheat Sheet

    A tiny fixture. 3 acronyms across 2 topics. 2 pages, print-friendly.

    ## [Download the PDF](./security-plus-acronyms-cheat-sheet.pdf)

    ## Topics

    | Topic | Acronyms |
    | --- | ---: |
    | Alpha | 2 |
    | Beta | 1 |

    ## The full list

    ### Alpha

    | Acronym | Term |
    | --- | --- |
    | `AAA` | Authentication, Authorization, and Accounting |
    | `BBB` | Big Bad Bug |

    ### Beta

    | Acronym | Term |
    | --- | --- |
    | `CCC` | Command and Control Center |
    """
)


class TempSheet:
    """Write a README string plus a PDF into a temp dir and hand back paths."""

    def __init__(self, tmp: Path, readme_text: str, pdf_bytes: bytes | None):
        self.readme = tmp / "README.md"
        self.readme.write_text(readme_text, encoding="utf-8")
        self.pdf = tmp / "security-plus-acronyms-cheat-sheet.pdf"
        if pdf_bytes is not None:
            self.pdf.write_bytes(pdf_bytes)

    def check(self) -> list[str]:
        return ca.check(readme=self.readme, pdf=self.pdf)


class RealArtifactsTest(unittest.TestCase):
    """The shipped README and PDF must stay internally consistent."""

    def test_real_cheat_sheet_passes(self):
        problems = ca.check()  # defaults point at the real files
        self.assertEqual(problems, [], f"real cheat sheet has problems: {problems}")


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.lines = VALID_README.splitlines()

    def test_parse_topics_table(self):
        topics = ca.parse_topics_table(self.lines)
        self.assertEqual(topics, {"Alpha": 2, "Beta": 1})

    def test_parse_full_list(self):
        sections = ca.parse_full_list(self.lines)
        self.assertEqual(sections, {"Alpha": ["AAA", "BBB"], "Beta": ["CCC"]})

    def test_parse_claims(self):
        claims = ca.parse_claims(VALID_README)
        self.assertEqual(claims["total_acronyms"], 3)
        self.assertEqual(claims["total_topics"], 2)
        self.assertEqual(claims["pdf_pages"], 2)

    def test_parse_claims_missing_numbers(self):
        # Prose with none of the headline patterns yields no claims.
        self.assertEqual(ca.parse_claims("nothing quantified here"), {})

    def test_count_pdf_pages_ignores_pages_object(self):
        # Two /Type /Page objects, one /Type /Pages container -> counts 2.
        self.assertEqual(ca.count_pdf_pages(make_pdf(2)), 2)
        self.assertEqual(ca.count_pdf_pages(make_pdf(5)), 5)

    def test_sort_key_is_case_insensitive(self):
        self.assertEqual(ca.sort_key("TLS"), "tls")
        self.assertEqual(ca.sort_key("IaaS"), "iaas")


class ValidFixtureTest(unittest.TestCase):
    def test_valid_fixture_has_no_problems(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            sheet = TempSheet(Path(d), VALID_README, make_pdf(2))
            self.assertEqual(sheet.check(), [])


class ProblemDetectionTest(unittest.TestCase):
    """Each mutation should surface exactly the rule it violates."""

    def _check(self, readme_text=VALID_README, pdf_bytes=make_pdf(2)):
        import tempfile

        # A fresh temp dir per call keeps the fixtures isolated.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        return TempSheet(Path(self._tmp.name), readme_text, pdf_bytes).check()

    def assertAnyContains(self, problems, needle):
        self.assertTrue(
            any(needle in p for p in problems),
            f"expected a problem containing {needle!r}, got {problems}",
        )

    def test_per_topic_count_mismatch(self):
        bad = VALID_README.replace("| Alpha | 2 |", "| Alpha | 5 |")
        problems = self._check(bad)
        self.assertAnyContains(problems, "summary says 5, full list has 2")

    def test_topic_in_summary_without_section(self):
        bad = VALID_README.replace("| Beta | 1 |", "| Beta | 1 |\n| Gamma | 4 |")
        problems = self._check(bad)
        self.assertAnyContains(problems, "'Gamma' is in the summary table but has no section")

    def test_section_without_summary_row(self):
        # Drop Beta from the summary but keep its section.
        bad = VALID_README.replace("| Beta | 1 |\n", "")
        problems = self._check(bad)
        self.assertAnyContains(problems, "section 'Beta' has no row in the summary table")

    def test_duplicate_acronym(self):
        bad = VALID_README.replace(
            "| `BBB` | Big Bad Bug |",
            "| `AAA` | Duplicate of AAA |",
        )
        # Alpha now claims 2 and has [AAA, AAA]; catch the duplicate specifically.
        problems = self._check(bad)
        self.assertAnyContains(problems, "duplicate acronym 'AAA'")

    def test_out_of_order_acronym(self):
        bad = VALID_README.replace(
            "| `AAA` | Authentication, Authorization, and Accounting |\n"
            "| `BBB` | Big Bad Bug |",
            "| `BBB` | Big Bad Bug |\n"
            "| `AAA` | Authentication, Authorization, and Accounting |",
        )
        problems = self._check(bad)
        self.assertAnyContains(problems, "out of order")

    def test_headline_total_mismatch(self):
        bad = VALID_README.replace("3 acronyms across 2 topics", "9 acronyms across 2 topics")
        problems = self._check(bad)
        self.assertAnyContains(problems, "intro claims 9 acronyms")

    def test_headline_topic_count_mismatch(self):
        bad = VALID_README.replace("3 acronyms across 2 topics", "3 acronyms across 7 topics")
        problems = self._check(bad)
        self.assertAnyContains(problems, "intro claims 7 topics")

    def test_missing_pdf_link(self):
        bad = VALID_README.replace("(./security-plus-acronyms-cheat-sheet.pdf)", "(https://example.com/x.pdf)")
        problems = self._check(bad)
        self.assertAnyContains(problems, "missing the relative link to the PDF")

    def test_missing_pdf_file(self):
        problems = self._check(pdf_bytes=None)
        self.assertAnyContains(problems, "PDF is missing")

    def test_pdf_page_count_mismatch(self):
        # README claims 2 pages, ship a 4-page PDF.
        problems = self._check(pdf_bytes=make_pdf(4))
        self.assertAnyContains(problems, "PDF has 4 page objects")

    def test_pdf_without_header(self):
        problems = self._check(pdf_bytes=b"not a pdf at all %%EOF")
        self.assertAnyContains(problems, "does not start with a %PDF- header")

    def test_pdf_missing_eof_trailer(self):
        # Header is present and the page count matches, but the %%EOF trailer
        # got truncated off the end. Only the trailer rule should fire.
        no_eof = make_pdf(2).replace(b"%%EOF", b"")
        problems = self._check(pdf_bytes=no_eof)
        self.assertAnyContains(problems, "no %%EOF trailer")

    def test_repeated_section_heading(self):
        # Alpha shows up twice under 'The full list'. Its second batch of rows
        # used to replace the first, so the lost rows never got counted.
        bad = VALID_README.replace(
            "### Beta\n",
            "### Alpha\n\n"
            "| Acronym | Term |\n"
            "| --- | --- |\n"
            "| `DDD` | Doubled Down Data |\n\n"
            "### Beta\n",
        )
        problems = self._check(bad)
        self.assertAnyContains(problems, "section 'Alpha' appears more than once")

    def test_repeated_section_heading_keeps_both_batches(self):
        # Whatever else fires, the rows under the second heading have to survive
        # the parse. Losing them is how a miscount slips through.
        bad = VALID_README.replace(
            "### Beta\n",
            "### Alpha\n\n"
            "| Acronym | Term |\n"
            "| --- | --- |\n"
            "| `DDD` | Doubled Down Data |\n\n"
            "### Beta\n",
        )
        sections = ca.parse_full_list(bad.splitlines())
        self.assertEqual(sections["Alpha"], ["AAA", "BBB", "DDD"])

    def _with_extra_beta_row(self, row: str) -> str:
        """VALID_README plus one more row in Beta, with the counts kept honest."""
        return (
            VALID_README.replace("3 acronyms across 2 topics", "4 acronyms across 2 topics")
            .replace("| Beta | 1 |", "| Beta | 2 |")
            .replace(
                "| `CCC` | Command and Control Center |",
                f"{row}\n| `CCC` | Command and Control Center |",
            )
        )

    def test_same_acronym_and_term_in_two_topics(self):
        # AAA already lives under Alpha. Pasting the identical entry into Beta
        # is the copy-paste mistake, and every count still adds up.
        bad = self._with_extra_beta_row(
            "| `AAA` | Authentication, Authorization, and Accounting |"
        )
        problems = self._check(bad)
        self.assertAnyContains(problems, "'AAA' is in both 'Alpha' and 'Beta'")

    def test_same_acronym_different_term_is_allowed(self):
        # This is the SoC / SOC case from the real sheet: System on Chip sits
        # under Endpoint, Security Operations Center under Security Operations.
        # Same letters, different terms, both correct.
        ok = self._with_extra_beta_row("| `aaa` | American Automobile Association |")
        self.assertEqual(self._check(ok), [])

    def test_repeated_topic_row(self):
        # Two summary rows for Alpha. The second count silently won, so a stale
        # first row could sit in the table forever without anything complaining.
        bad = VALID_README.replace("| Beta | 1 |", "| Alpha | 2 |\n| Beta | 1 |")
        problems = self._check(bad)
        self.assertAnyContains(problems, "topic 'Alpha' has more than one row")

    def test_readme_without_topics_table(self):
        # Drop the whole Topics summary; the full list still parses.
        no_topics = VALID_README.replace(
            "## Topics\n\n"
            "| Topic | Acronyms |\n"
            "| --- | ---: |\n"
            "| Alpha | 2 |\n"
            "| Beta | 1 |\n\n",
            "",
        )
        problems = self._check(no_topics)
        self.assertAnyContains(problems, "could not parse the Topics summary table")

    def test_readme_without_sections(self):
        # Keep the Topics table but cut everything under 'The full list'.
        no_sections = VALID_README.split("## The full list")[0]
        problems = self._check(no_sections)
        self.assertAnyContains(problems, "could not parse any sections")

    def test_missing_readme(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "nope.md"
            self.assertEqual(ca.check(readme=missing, pdf=Path(d) / "x.pdf"), ["README.md is missing"])


class MainTest(unittest.TestCase):
    """CI reads the exit code, so both branches of main() need pinning down."""

    def _run_main(self, problems):
        import contextlib
        import io
        from unittest import mock

        out = io.StringIO()
        with mock.patch.object(ca, "check", return_value=problems):
            with contextlib.redirect_stdout(out):
                code = ca.main()
        return code, out.getvalue()

    def test_main_succeeds_when_nothing_is_wrong(self):
        code, out = self._run_main([])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_main_fails_and_lists_every_problem(self):
        code, out = self._run_main(["first thing", "second thing"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        # A summary that swallows problems is as bad as not checking at all.
        self.assertIn("first thing", out)
        self.assertIn("second thing", out)


if __name__ == "__main__":
    unittest.main()
