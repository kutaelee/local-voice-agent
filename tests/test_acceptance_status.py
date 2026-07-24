from __future__ import annotations

import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_totals_match_the_twenty_criterion_rows() -> None:
    source = (ROOT / "docs" / "acceptance-status.md").read_text(
        encoding="utf-8"
    )
    rows = re.findall(
        r"^\|\s*(\d+)\s*\|.*?\|\s*(VERIFIED|PARTIAL|FAILED)\s*\|",
        source,
        re.MULTILINE,
    )
    assert [int(number) for number, _ in rows] == list(range(1, 21))

    counts = Counter(status for _, status in rows)
    reported = {
        label.lower(): int(value)
        for label, value in re.findall(
            r"^- (Verified|Partial|Failed): (\d+)$",
            source,
            re.MULTILINE,
        )
    }
    assert reported == {
        "verified": counts["VERIFIED"],
        "partial": counts["PARTIAL"],
        "failed": counts["FAILED"],
    }
