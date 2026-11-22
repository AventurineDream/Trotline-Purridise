# QA note template

Copy this file to a dated note for each QA pass (for example `QA-2026-11-21-linux.md`,
kept outside the repository or in `docs/` for a recorded pass). It records one build on
one machine. The release steps are in [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md); the
play-through steps are in [QA-CHECKLIST.md](QA-CHECKLIST.md). Do not fill in a box you
did not run.

## 1. Build and machine

- Commit (`git rev-parse HEAD`):
- Build: source clone / packaged archive (name and SHA-256):
- Python (source runs only) and install command:
- OS, desktop session, GPU and driver:
- Display size and scale (`--detail` tier used, if any):
- Save path used: a disposable scratch path, never the normal save. Path:
- Tester and date:

## 2. Automated gates

Run from the repository root. Record the exact command and the last line of output.

| Command | Result | Notes |
| --- | --- | --- |
| `python -m fishing --selftest --software` | `selftest ok` expected | Headless. |
| `python -m fishing --selftest` | `selftest ok` expected | Native renderer; needs an OpenGL context. |
| `python -m fishing --smoke` | `window ok ...` line, exit 0 | Real window, run from the repository root. Runs a 5-second throttle sequence, a 12x midnight crossing, two boat purchases with fuel-free sailing, and Cedar and Briar lake swaps. Writes `shots/window*.png` and `shots/midnight.png` relative to the working directory. Uses the OpenGL window; `--software` has no effect here. |
| `XDG_DATA_HOME=<scratch> python -m fishing --check-save` | `migrated=yes` for a v1 save | Put an old `saves/briar.json` in the clone root first. Set `XDG_DATA_HOME` to a scratch folder, or this checks the real save location. The migrated save and its `backup/` folder go under that scratch folder. `--save PATH` skips the legacy migration and prints `migrated=no`. |
| `python -m unittest discover` | all tests pass | About 20 to 25 minutes on CI-class hardware. |
| `ruff check .` | `All checks passed!` | Rules in `ruff.toml`. |

Packaged builds (RELEASE-CHECKLIST, "What CI proves"): record the `package-smoke`
run URL, or the local `./trotline-purridise --selftest --software` result.

## 3. Manual checks

From RELEASE-CHECKLIST, "Manual checks before a release". Use a machine without Python
or developer tools for the packaged build.

- [ ] 1. Launch with a window. Result:
- [ ] 2. Five minutes of play: set a line, anchor, check it, sell at the landing. Result:
- [ ] 3. Save, quit, relaunch. Money, lines and boats persist. Result:
- [ ] 4. v1 save migration (`--check-save`, then launch). Result:
- [ ] 5. Licenses present in `_internal/licenses/` (packaged builds). Result:

For a play-through, list the QA-CHECKLIST sections you ran, for example
"Boat controls" and "Save, reload, resume". Do not tick a box unless you saw the
expected result on this build.

## 4. Findings

One row per defect. Give the smallest repro you have.

| ID | Severity | Screen or step | Expected | Actual | Repro | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |

Severity: **blocker** (cannot play or loses saved data), **major** (a documented feature
fails), **minor** (wrong text or visual, workaround exists).

## 5. Not verified

List what this pass did not cover, so a clean table is not read as a full pass. Include
any platform, control device, audio check or Windows and macOS build you did not run.

## 6. Sign-off

- Verdict: pass / pass with findings / fail
- Known open findings (IDs):
- Note for Iolite or Aven:
