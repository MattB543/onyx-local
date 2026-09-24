#!/usr/bin/env python3
"""Fail on new ty diagnostics in backend/, compared with a committed baseline.

Fork-only (MattB543/onyx-local). Upstream runs ty only on pull requests and
merge queues (.github/workflows/pr-python-checks.yml). This fork pushes straight
to main, so the pre-push hook (scripts/git-hooks/pre-push) and the fork-only
workflow (.github/workflows/fork-ty-gate.yml) run this script instead.

Each diagnostic is normalized to "path<TAB>description" (repo-relative, forward
slashes, no line numbers, so unrelated edits do not churn the baseline) and
compared as a multiset with two baselines: production code and backend/tests/.
Trade-off: a like-for-like replacement of a baselined diagnostic goes unnoticed.

Usage (from any directory):
    python scripts/ty_baseline_gate.py             # check; exit 1 on new diagnostics
    python scripts/ty_baseline_gate.py --update    # rewrite both baselines

Run it with the repo venv's interpreter (.venv/Scripts/python.exe on Windows,
.venv/bin/python elsewhere). ty resolves third-party imports from that venv.

Exit codes: 0 = pass, 1 = new diagnostics, 2 = tool or setup failure.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO_ROOT / "scripts" / "ty_baseline"
BASELINE_NAMES = ("production", "tests")
TESTS_PREFIX = "backend/tests/"
# Same checker config as upstream CI (pyproject.toml [tool.ty], run from the
# repo root). The platform is pinned so Windows and Linux runs agree.
TY_ARGS = [
    "check",
    "--python-platform",
    "linux",
    "--output-format",
    "gitlab",
    "--color",
    "never",
    "--no-progress",
]
UPDATE_HINT = "python scripts/ty_baseline_gate.py --update"


class GateError(Exception):
    """A tool or setup failure (exit 2), as opposed to new diagnostics (exit 1)."""


@dataclass(frozen=True)
class Diagnostic:
    key: str  # "path<TAB>description", the baseline format
    path: str
    description: str
    line: int | None
    column: int | None

    @property
    def location(self) -> str:
        if self.line is None:
            return self.path
        return f"{self.path}:{self.line}:{self.column or 1}"


def baseline_path(name: str) -> Path:
    return BASELINE_DIR / f"{name}.txt"


def pinned_ty_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pins: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            match = re.fullmatch(r"ty\s*==\s*([\w.+-]+)", node.strip())
            if match:
                pins.add(match.group(1))
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(data.get("project", {}))
    walk(data.get("dependency-groups", {}))
    if len(pins) != 1:
        raise GateError(
            f"expected exactly one 'ty==<version>' pin in pyproject.toml, found {sorted(pins)}"
        )
    return pins.pop()


def find_ty(explicit: str | None) -> str:
    if explicit:
        return explicit
    bin_dir = Path(sys.executable).parent
    for name in ("ty.exe", "ty"):
        candidate = bin_dir / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ty")
    if found:
        return found
    raise GateError(
        f"ty not found next to {sys.executable} or on PATH. "
        "Run this script with the repo venv's python."
    )


def default_python_env() -> str | None:
    # The venv that runs this script is the one ty should resolve imports from.
    if sys.prefix != sys.base_prefix:
        return sys.prefix
    return None


def installed_ty_version(ty: str) -> str:
    proc = subprocess.run([ty, "--version"], capture_output=True, check=False)
    output = proc.stdout.decode("utf-8", errors="replace").strip()
    match = re.match(r"ty (\S+)", output)
    if proc.returncode != 0 or not match:
        raise GateError(f"'{ty} --version' failed (exit {proc.returncode}): {output}")
    return match.group(1)


def normalize_path(raw: str) -> str:
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            pass
    path = raw.replace("\\", "/")
    return path.removeprefix("./")


def escape_field(text: str) -> str:
    return text.replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")


def parse_position(location: dict[str, Any]) -> tuple[int | None, int | None]:
    begin = (location.get("positions") or {}).get("begin")
    if isinstance(begin, dict):
        return begin.get("line"), begin.get("column")
    lines = location.get("lines")
    if isinstance(lines, dict):
        return lines.get("begin"), None
    return None, None


def run_ty(ty: str, python_env: str | None) -> list[Diagnostic]:
    cmd = [ty, *TY_ARGS]
    if python_env:
        cmd += ["--python", python_env]
    # PYTHONPATH may point at another checkout and change import resolution.
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, env=env, check=False)
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
    # ty exits 0 with no diagnostics, 1 with diagnostics, >1 on a tool failure.
    if proc.returncode > 1 or proc.returncode < 0:
        raise GateError(
            f"ty failed (exit {proc.returncode}): {' '.join(cmd)}\n{stderr}"
        )
    try:
        raw = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"ty output is not valid gitlab JSON: {exc}\n{stderr}") from exc
    if not isinstance(raw, list):
        raise GateError("ty gitlab output is not a JSON list")

    diagnostics: list[Diagnostic] = []
    for item in raw:
        location = item.get("location") or {}
        path = escape_field(normalize_path(str(location.get("path", ""))))
        description = escape_field(str(item.get("description", "")))
        line, column = parse_position(location)
        diagnostics.append(
            Diagnostic(
                key=f"{path}\t{description}",
                path=path,
                description=description,
                line=line,
                column=column,
            )
        )
    return diagnostics


def bucket(diagnostic: Diagnostic) -> str:
    return "tests" if diagnostic.path.startswith(TESTS_PREFIX) else "production"


def split(diagnostics: list[Diagnostic]) -> dict[str, list[Diagnostic]]:
    buckets: dict[str, list[Diagnostic]] = {name: [] for name in BASELINE_NAMES}
    for diagnostic in diagnostics:
        buckets[bucket(diagnostic)].append(diagnostic)
    return buckets


def read_baseline(name: str) -> Counter[str]:
    path = baseline_path(name)
    if not path.is_file():
        raise GateError(
            f"baseline {path.relative_to(REPO_ROOT).as_posix()} is missing. Run: {UPDATE_HINT}"
        )
    keys = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    return Counter(keys)


def write_baseline(path: Path, name: str, keys: list[str], ty_version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# ty {ty_version} --python-platform linux, {name} diagnostics "
        f"(path<TAB>description). Regenerate with: {UPDATE_HINT}\n"
    )
    body = "".join(f"{key}\n" for key in sorted(keys))
    path.write_text(header + body, encoding="utf-8", newline="\n")


def gha_escape(text: str, is_property: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if is_property:
        text = text.replace(":", "%3A").replace(",", "%2C")
    return text


def check(current: dict[str, list[Diagnostic]], ty_version: str) -> int:
    new_total = 0
    gone_lines: list[str] = []
    new_keys: list[str] = []
    report: list[str] = []
    annotations: list[str] = []

    for name in BASELINE_NAMES:
        baseline = read_baseline(name)
        counts = Counter(d.key for d in current[name])
        new = counts - baseline
        gone = baseline - counts

        if new:
            by_key: dict[str, list[Diagnostic]] = {}
            for diagnostic in current[name]:
                by_key.setdefault(diagnostic.key, []).append(diagnostic)
            count = sum(new.values())
            new_total += count
            rel = baseline_path(name).relative_to(REPO_ROOT).as_posix()
            report.append(f"\n{name} ({rel}): {count} new")
            for key in sorted(new):
                occurrences = by_key[key]
                path, _, description = key.partition("\t")
                allowed = baseline.get(key, 0)
                suffix = (
                    f"  [{counts[key]} found, baseline allows {allowed}]"
                    if allowed
                    else ""
                )
                report.append(f"  {description}{suffix}")
                for occurrence in occurrences:
                    report.append(f"      at {occurrence.location}")
                    if occurrence.line is not None:
                        annotations.append(
                            f"::error file={gha_escape(path, True)},"
                            f"line={occurrence.line},col={occurrence.column or 1},"
                            f"title=New ty diagnostic::{gha_escape(description)}"
                        )
                new_keys.extend([key] * new[key])

        gone_lines.extend(
            f"  [{name}] {key.replace(chr(9), ': ', 1)}"
            for key in sorted(gone)
            for _ in range(gone[key])
        )

    totals = ", ".join(f"{len(current[n])} {n}" for n in BASELINE_NAMES)
    if new_total:
        print(
            f"FAIL: ty baseline gate (ty {ty_version}): {new_total} new diagnostic(s) not in the baseline."
        )
        print("\n".join(report))
        print("\nBaseline lines for the new diagnostics (path<TAB>description):")
        for key in new_keys:
            print(key)
        print(
            "\nFix them, or suppress a false positive with `# ty: ignore[<rule>]`.\n"
            f"To accept them on purpose, run `{UPDATE_HINT}` and commit scripts/ty_baseline/."
        )
        if annotations and os.environ.get("GITHUB_ACTIONS") == "true":
            print("\n".join(annotations))
    else:
        print(
            f"PASS: ty baseline gate (ty {ty_version}): {totals} diagnostics, none new."
        )

    if gone_lines:
        print(
            f"\nNOTE: {len(gone_lines)} baseline diagnostic(s) are no longer reported. "
            f"Shrink the baseline with `{UPDATE_HINT}`:"
        )
        print("\n".join(gone_lines))

    return 1 if new_total else 0


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite both baselines from the current tree",
    )
    parser.add_argument(
        "--ty", help="ty executable (default: next to this interpreter, then PATH)"
    )
    parser.add_argument(
        "--python",
        help="Python environment ty resolves imports from (default: the venv running this script)",
    )
    parser.add_argument(
        "--write-current",
        metavar="DIR",
        help="also write the current diagnostics in baseline format to DIR (for CI artifacts)",
    )
    args = parser.parse_args()

    try:
        ty = find_ty(args.ty)
        pinned = pinned_ty_version()
        installed = installed_ty_version(ty)
        if installed != pinned:
            raise GateError(
                f"ty {installed} is installed ({ty}), but pyproject.toml pins ty=={pinned}. "
                "Diagnostics differ between ty versions, so the baseline only holds for the pinned one. "
                "Re-sync the venv (uv sync --frozen)."
            )

        current = split(run_ty(ty, args.python or default_python_env()))

        if args.write_current:
            out_dir = Path(args.write_current)
            for name in BASELINE_NAMES:
                write_baseline(
                    out_dir / f"{name}.txt",
                    name,
                    [d.key for d in current[name]],
                    installed,
                )

        if args.update:
            for name in BASELINE_NAMES:
                write_baseline(
                    baseline_path(name), name, [d.key for d in current[name]], installed
                )
                rel = baseline_path(name).relative_to(REPO_ROOT).as_posix()
                print(f"Wrote {rel}: {len(current[name])} diagnostics")
            return 0

        return check(current, installed)
    except GateError as exc:
        print(f"ERROR: ty baseline gate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
