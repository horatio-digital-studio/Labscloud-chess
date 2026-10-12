"""Fail if tests/traceability.json and docs/requirements.md / the test suite disagree.

- every REQ-… ID in docs/requirements.md has an entry, and there are no extra entries;
- every listed pytest node exists ("[*]" means "every parametrised case of this test");
- every requirement with automated verification (U, I, E) lists at least one pytest node.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def collected_nodes() -> set[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit",
            "tests/contract",
            "tests/integration",
            "tests/e2e",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    nodes = {line.strip() for line in result.stdout.splitlines() if "::" in line}
    if not nodes:
        print(result.stdout, result.stderr)
        raise SystemExit("could not collect tests")
    return nodes


def main() -> int:
    requirements = set(
        re.findall(
            r"^\| (REQ-[A-Z]+-\d+) \|", (ROOT / "docs/requirements.md").read_text("utf-8"), re.M
        )
    )
    trace = json.loads((ROOT / "tests/traceability.json").read_text("utf-8"))
    entries = {entry["id"]: entry for entry in trace["requirements"]}
    nodes = collected_nodes()
    bases = {node.split("[", 1)[0] for node in nodes}
    problems: list[str] = []

    for missing in sorted(requirements - set(entries)):
        problems.append(f"{missing}: in requirements.md but not in traceability.json")
    for extra in sorted(set(entries) - requirements):
        problems.append(f"{extra}: in traceability.json but not in requirements.md")
    for rid, entry in sorted(entries.items()):
        pytest_refs = [t for t in entry["tests"] if t.startswith("tests/")]
        for ref in pytest_refs:
            if ref.endswith("[*]"):
                base = ref[:-3]
                if not any(node.startswith(base + "[") for node in nodes):
                    problems.append(f"{rid}: no parametrised cases for {base}")
            elif ref not in nodes and ref not in bases:
                problems.append(f"{rid}: test not found: {ref}")
        automated = set(entry["verified_by"]) & {"U", "I", "E"}
        if automated and not pytest_refs:
            problems.append(f"{rid}: verified by {sorted(automated)} but lists no tests")

    for problem in problems:
        print(problem)
    print(f"traceability: {len(entries)} requirements, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
