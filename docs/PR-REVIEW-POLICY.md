# PR review and merge policy

The sole required reviewer is **Amaranth**, until the owner changes this policy.
On 17 October 2026 the owner instructed: "ignore jules. Single reviewer for now
until i figure something else out". This explicit temporary decision supersedes
the earlier requirement for both Amaranth and Jules. Do not require, request, or
escalate missing Jules reviews or Jules authentication while this decision is
in effect. Preserve previous Jules evidence and notifications as history.

On 18 October 2026 the owner corrected the review delay to 30 minutes. Both the
PR creation time and the first-observed time of each head SHA must be at least
30 minutes old before review feedback can be read.

Amaranth may use the owner's GitHub account. Agent identity and review evidence
determine the review's provenance; a separate GitHub login and a formal GitHub
approval are not required. The implementing/merging agent cannot supply the
required review itself.

Codex connector reviews remain useful supplementary evidence. The scheduled
`second-review-pass` Python script performs syntax and text checks and posts a
comment. Neither is a substitute for Amaranth's substantive review.

The machine-readable settings are in `.github/merge-policy.json`. The automation
must enforce all of the following:

1. A PR is open and ready for review. Wait until both 30 minutes after PR
   creation and 30 minutes after first observing its current head have elapsed
   before reading its review feedback. Every changed head starts a new review round.
   CI may be inspected immediately so execution failures can be fixed promptly.
2. Amaranth reviewed the exact current head and reported `VERDICT: GREEN`,
   with no outstanding actionable findings. Record Amaranth's verdict, full
   resolved SHA, source comment URL, and known automation provenance. A shared
   GitHub login, including the PR author's, does not disqualify the review. A login alone does not identify an agent.
   A missing, ambiguous, stale, failed or incomplete Amaranth review blocks merge.
3. No actionable review findings, outstanding substantive requests for changes,
   or unresolved blocking review threads remain. Inspect all pages of reviews,
   comments and threads. A green summary alone does not dismiss another
   reviewer's outstanding findings.
4. The latest push run of `.github/workflows/validation.yml` for that exact head
   completed successfully, with its `gameplay-tests` job successful. Verify the
   workflow identity, event, full run head SHA and GitHub Actions check identity.
   Missing, skipped, cancelled, pending or failed required jobs block merge.
   The job verifies its checkout SHA, runs all persistence regressions, and runs
   the full headless gameplay/software-rendering self-test. Any additional
   GitHub-required checks must also pass if protection becomes available.
5. Immediately before merging, re-fetch the open PR and verify the same head,
   mergeability, Amaranth's verdict, threads and latest required run. Supply the
   expected head SHA to GitHub's merge API and use the configured normal merge
   commit method. A changed head restarts the 30-minute wait.

## Reviewer comment format

Amaranth should post its own substantive review, using this header and
actual values, followed by findings and executed/inspection-only validation:

```text
Reviewer: Amaranth
Reviewed-Head: <full 40-character current head SHA>
VERDICT: GREEN
<!-- agent-review:v1 {"reviewer":"Amaranth","head_sha":"<full SHA>","verdict":"GREEN"} -->
```

Findings use `VERDICT: CHANGES NEEDED` and the matching marker value. These are
review results,
not merge instructions. Reject copied/quoted review text, review requests,
implementer-written verdicts, and deterministic workflow summaries. Existing
Amaranth comments may use `Amaranth review of head ...` or the observed
`VERDICT`/`Reviewed head ...` format if their source is unambiguously established
as Amaranth. A legacy abbreviated SHA must resolve uniquely to the current full
head; otherwise the result is stale or ambiguous. Record that provenance.

The hourly follow-through does not trigger or monitor Jules while its review
requirement is suspended. The native Jules fallback schedule is paused. Restoring
a second reviewer requires a new owner decision; the controller cannot invent a
replacement or restore the requirement on its own.

## Check-policy verification and follow-through

As verified on 17 October 2026, GitHub's branch endpoint reports `main` as
unprotected, with `protection.enabled == false`, no required status-check
contexts, and enforcement `off`. The dedicated protection/rules endpoints return
HTTP 403 because those features require a different plan for this private repo.
The repository stays private. The automation enforces the explicit review and
CI gates above. If the branch endpoint or policy cannot be verified, or
protection changes, investigate before merging; a 403 by itself is never
evidence that checks passed.

The automation keeps the per-head delay, fix history, agent-review evidence and
notification state in its existing memory. It may make bounded fixes only on
the existing PR branch and must wait again after every push. It sends email
only for a concrete human decision or final merge, suppresses repeated unchanged
blocker notices, and starts the next documented ticket only when no PRs,
including drafts, are open.

Future runs must not weaken this policy to clear a failure. Policy changes
require owner authorization. The owner's temporary single-reviewer instruction
is the authorization for this revision. Amaranth's substantive current-head
GREEN review, the per-head delay, all actionable findings, required CI, and final
merge checks remain mandatory.
