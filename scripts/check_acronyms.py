#!/usr/bin/env python3
"""Integrity check for the Security+ acronyms cheat sheet.

Verifies that README.md is internally consistent and that the distributed PDF
matches what the README claims, so a future edit cannot silently drift the
counts or break the file. Standard library only, no dependencies.

Run from the repo root:

    python scripts/check_acronyms.py

Exits 0 when everything lines up, 1 with a list of problems otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
PDF = REPO_ROOT / "security-plus-acronyms-cheat-sheet.pdf"

# A markdown table data row, e.g. "| `CASB` | Cloud Access Security Broker |".
ACRONYM_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$")
# A topic summary row, e.g. "| Cloud & Virtualization | 10 |".
TOPIC_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*$")


def sort_key(acronym: str) -> str:
    """Ordering key used inside each section: case-insensitive on the acronym."""
    return acronym.lower()


def parse_topics_table(lines: list[str]) -> dict[str, int]:
    """Read the '## Topics' summary table into {topic: claimed_count}."""
    topics: dict[str, int] = {}
    in_table = False
    for line in lines:
        if line.strip() == "## Topics":
            in_table = True
            continue
        if in_table:
            if line.startswith("## "):
                break
            m = TOPIC_ROW.match(line)
            if not m:
                continue
            topic, count = m.group(1).strip(), int(m.group(2))
            if topic.lower() == "topic":  # header row
                continue
            topics[topic] = count
    return topics


def parse_full_list(lines: list[str]) -> dict[str, list[str]]:
    """Read the '## The full list' sections into {topic: [acronyms in order]}."""
    sections: dict[str, list[str]] = {}
    in_list = False
    current: str | None = None
    for line in lines:
        if line.strip() == "## The full list":
            in_list = True
            continue
        if not in_list:
            continue
        if line.startswith("## "):  # next top-level heading ends the list
            break
        if line.startswith("### "):
            current = line[4:].strip()
            sections[current] = []
            continue
        if current is None:
            continue
        m = ACRONYM_ROW.match(line)
        if not m:
            continue
        acronym = m.group(1).strip()
        if acronym.lower() == "acronym":  # header row
            continue
        sections[current].append(acronym)
    return sections


def parse_claims(text: str) -> dict[str, int]:
    """Pull the headline numbers the README states in prose."""
    claims: dict[str, int] = {}
    m = re.search(r"(\d+)\s+acronyms\s+across\s+(\d+)\s+topics", text)
    if m:
        claims["total_acronyms"] = int(m.group(1))
        claims["total_topics"] = int(m.group(2))
    m = re.search(r"(\d+)\s+pages", text)
    if m:
        claims["pdf_pages"] = int(m.group(1))
    return claims


def count_pdf_pages(data: bytes) -> int:
    """Count page objects without a PDF library: /Type /Page not /Type /Pages."""
    return len(re.findall(rb"/Type\s*/Page(?![s])", data))


def check() -> list[str]:
    problems: list[str] = []

    if not README.exists():
        return ["README.md is missing"]
    text = README.read_text(encoding="utf-8")
    lines = text.splitlines()

    topics = parse_topics_table(lines)
    sections = parse_full_list(lines)
    claims = parse_claims(text)

    if not topics:
        problems.append("could not parse the Topics summary table")
    if not sections:
        problems.append("could not parse any sections under 'The full list'")
    if not topics or not sections:
        return problems

    # Every topic in the summary has a matching section and vice versa.
    summary_topics = set(topics)
    list_topics = set(sections)
    for missing in sorted(summary_topics - list_topics):
        problems.append(f"topic '{missing}' is in the summary table but has no section")
    for extra in sorted(list_topics - summary_topics):
        problems.append(f"section '{extra}' has no row in the summary table")

    # Per-topic counts agree between the summary and the actual rows.
    for topic in sorted(summary_topics & list_topics):
        claimed = topics[topic]
        actual = len(sections[topic])
        if claimed != actual:
            problems.append(
                f"'{topic}': summary says {claimed}, full list has {actual}"
            )

    # Headline claims line up with the data.
    summary_total = sum(topics.values())
    if "total_acronyms" in claims and claims["total_acronyms"] != summary_total:
        problems.append(
            f"intro claims {claims['total_acronyms']} acronyms, "
            f"summary table totals {summary_total}"
        )
    if "total_topics" in claims and claims["total_topics"] != len(topics):
        problems.append(
            f"intro claims {claims['total_topics']} topics, "
            f"summary table has {len(topics)}"
        )

    # No duplicates and stable alphabetical order within each section.
    for topic, acronyms in sections.items():
        seen: set[str] = set()
        for a in acronyms:
            key = sort_key(a)
            if key in seen:
                problems.append(f"'{topic}': duplicate acronym '{a}'")
            seen.add(key)
        ordered = sorted(acronyms, key=sort_key)
        if acronyms != ordered:
            for got, want in zip(acronyms, ordered):
                if got != want:
                    problems.append(
                        f"'{topic}': out of order near '{got}' "
                        f"(expected '{want}')"
                    )
                    break

    # The relative download link points at the file that ships.
    if "(./security-plus-acronyms-cheat-sheet.pdf)" not in text:
        problems.append("README is missing the relative link to the PDF")

    # The PDF is real and its page count matches the claim.
    if not PDF.exists():
        problems.append("the cheat sheet PDF is missing")
    else:
        data = PDF.read_bytes()
        if not data.startswith(b"%PDF-"):
            problems.append("PDF does not start with a %PDF- header")
        if b"%%EOF" not in data[-2048:]:
            problems.append("PDF has no %%EOF trailer near the end")
        pages = count_pdf_pages(data)
        if "pdf_pages" in claims and pages != claims["pdf_pages"]:
            problems.append(
                f"README claims {claims['pdf_pages']} pages, "
                f"PDF has {pages} page objects"
            )

    return problems


def main() -> int:
    problems = check()
    if problems:
        print("FAIL: cheat sheet integrity check found problems:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: README and PDF are consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
