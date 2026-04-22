from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "docs"

DEFAULT_TARGETS = {
    "01-总册-上.md": 100_000,
    "02-总册-中.md": 120_000,
    "03-总册-下.md": 100_000,
    "04-练习总卷.md": 30_000,
}


FENCED_BLOCK_RE = re.compile(r"```.*?```", flags=re.S)
TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*$", flags=re.M)


@dataclass(frozen=True)
class AuditResult:
    name: str
    chinese_chars: int
    target: int

    @property
    def gap(self) -> int:
        return self.target - self.chinese_chars

    @property
    def passed(self) -> bool:
        return self.chinese_chars >= self.target


def strip_non_body(text: str) -> str:
    text = FENCED_BLOCK_RE.sub("", text)
    text = TABLE_SEP_RE.sub("", text)
    return text


def count_chinese_chars(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def audit_file(path: Path, target: int) -> AuditResult:
    text = path.read_text(encoding="utf-8")
    body = strip_non_body(text)
    chinese_chars = count_chinese_chars(body)
    return AuditResult(name=path.name, chinese_chars=chinese_chars, target=target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit learning docs by Chinese body-character count.")
    parser.add_argument(
        "--fail-on-gap",
        action="store_true",
        help="Exit with code 1 if any document is below its target.",
    )
    args = parser.parse_args()

    results: list[AuditResult] = []
    for name, target in DEFAULT_TARGETS.items():
        path = ROOT / name
        if not path.exists():
            raise SystemExit(f"missing target document: {path}")
        results.append(audit_file(path, target))

    total_current = sum(item.chinese_chars for item in results)
    total_target = sum(item.target for item in results)

    print("Learning docs audit")
    print("===================")
    for item in results:
        status = "PASS" if item.passed else "GAP"
        print(
            f"{item.name}: current={item.chinese_chars} target={item.target} "
            f"gap={max(item.gap, 0)} status={status}"
        )
    print("-------------------")
    print(
        f"TOTAL: current={total_current} target={total_target} "
        f"gap={max(total_target - total_current, 0)}"
    )

    if args.fail_on_gap and any(not item.passed for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
