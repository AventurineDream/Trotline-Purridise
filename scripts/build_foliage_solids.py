"""Rebuild the foliage solids fixture from a git ref whose fishing package builds each lake
with World(lake).solid_props.

fishing/fixtures/foliage_solids.json pins every lake's solid props (rocks, stumps, knees,
deadpine snags, nebula kelp and meteors), so density work cannot move a wall that the boat or a
fish collides with. This script regenerates those rows from a git ref: `git archive` unpacks
the ref's fishing/ package into a scratch directory, a child Python process imports it from
there and builds each lake, and the rows are written as JSON to the output path given.
The `about` line records the exact command, the NumPy version and the platform, so a
regeneration can be checked against the committed file.

Usage, from the repository root; both arguments are required:
    python3 scripts/build_foliage_solids.py 36c17d2 fishing/fixtures/foliage_solids.json

This is a development script, not a test: unittest discovery only collects test*.py files.
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAKES = ("briar", "cedar", "flathead", "crater", "nebula")

# The child runs with the extracted ref as its working directory, so `fishing` imports from that
# ref and never from this worktree. The parent also checks the path the child reports, and
# PYTHONPATH is dropped from the child's environment so nothing else can shadow the package.
CHILD = """
import json, platform, sys
import numpy as np
import fishing
from fishing.world import World
print(json.dumps({
    "fishing": fishing.__file__,
    "numpy": np.__version__,
    "platform": platform.platform(),
    "solids": {lake: np.asarray(World(lake).solid_props, np.float64).tolist()
               for lake in sys.argv[1:]},
}))
"""


def extract(ref: str, dest: Path) -> str:
    """Unpack the `fishing/` package at `ref` into `dest` and return the commit it names.

    Args:
        ref: Any git revision, such as 36c17d2.
        dest: An existing empty directory that receives the extracted package.

    Returns:
        The full commit hash that `ref` resolves to, recorded in the fixture's `about` line.

    Raises:
        subprocess.CalledProcessError: If git cannot find `ref`.
    """
    archive = subprocess.run(["git", "archive", "--format=tar", ref, "fishing"], cwd=ROOT,
                             check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")
    commit = subprocess.run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=ROOT,
                            check=True, capture_output=True, text=True).stdout
    return commit.strip()


def build(package_root: Path) -> dict:
    """Build every lake's solids from the extracted package in a child process.

    Args:
        package_root: Directory holding the extracted `fishing/` package.

    Returns:
        A dict with the `numpy` and `platform` strings and `solids`: per lake, a list of
        [x m, z m, radius m] rows.

    Raises:
        RuntimeError: If the child imported `fishing` from outside `package_root`.
        subprocess.CalledProcessError: If the child build fails.
    """
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run([sys.executable, "-c", CHILD, *LAKES], cwd=package_root, env=env,
                            check=True, capture_output=True, text=True)
    report = json.loads(result.stdout.strip().splitlines()[-1])
    if not Path(report["fishing"]).resolve().is_relative_to(package_root.resolve()):
        raise RuntimeError(f"fishing imported from {report['fishing']}, not {package_root}")
    return report


def render(about: str, solids: dict) -> str:
    """Format the fixture the way the committed file is laid out: one row per line.

    Args:
        about: The `about` sentence, including the command, NumPy version and platform.
        solids: Lake name to rows of [x m, z m, radius m], in fixture order.

    Returns:
        The JSON text, ending in a newline.
    """
    lines = ["{", f'  "about": {json.dumps(about)},', '  "solids": {']
    names = list(solids)
    for index, lake in enumerate(names):
        lines.append(f'    "{lake}": [')
        rows = [json.dumps(row) for row in solids[lake]]
        for position, row in enumerate(rows):
            comma = "," if position < len(rows) - 1 else ""
            lines.append(f"      {row}{comma}")
        lines.append("    ]" + ("," if index < len(names) - 1 else ""))
    lines.extend(["  }", "}"])
    return "\n".join(lines) + "\n"


def main() -> None:
    """Rebuild the fixture from the ref named on the command line and write it.

    Side effects: writes the output file, and extracts into a temporary directory that is
    removed afterwards.
    """
    parser = argparse.ArgumentParser(
        description="Rebuild the foliage solids fixture from a git ref.")
    parser.add_argument("ref", help="git revision to build, such as 36c17d2")
    parser.add_argument("out", type=Path,
                        help="fixture file to write, such as fishing/fixtures/foliage_solids.json")
    args = parser.parse_args()
    command = " ".join([Path(sys.executable).name, *sys.argv])
    with tempfile.TemporaryDirectory() as scratch:
        commit = extract(args.ref, Path(scratch))
        report = build(Path(scratch))
    about = (f"Solid props (x m, z m, radius m) per lake, built from git ref {args.ref} "
             f"(commit {commit}). test_foliage compares the built worlds to these: x and z within "
             f"1 mm, radius within 1e-9 m. Generated by {command} on NumPy {report['numpy']} "
             f"({report['platform']}).")
    args.out.write_text(render(about, report["solids"]), encoding="utf-8")


if __name__ == "__main__":
    main()
