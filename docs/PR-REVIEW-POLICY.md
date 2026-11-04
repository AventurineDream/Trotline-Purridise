# PR review and merge policy

Every pull request requires a completed, clear review from **Claude**. The
review must cover the full current head commit. A review for an earlier commit,
or a pending, failed, or incomplete review, does not satisfy the gate. A review
by the agent session that implemented the pull request does not count either
(`implementing_agent_self_review` in the machine-readable settings).

Codex and Amaranth are no longer part of this review process. Neither is a
reviewer signal or a merge requirement, and a Codex review or comment neither
satisfies nor blocks the gate.

A review is clear when it has no actionable findings or unresolved requests for
changes. Resolve all findings and blocking review threads before merging. If a
finding requires a code change, push the fix to the same pull request and
restart the review cycle: Claude must complete a clear review of the new full
head commit. Reviews of older commits do not carry forward.

Before merging, verify all of the following:

1. Claude has completed a clear review of the exact current head SHA.
2. No actionable findings, outstanding change requests, or unresolved blocking
   review threads remain.
3. The latest push run of `.github/workflows/validation.yml` for that exact
   head completed successfully, including the `gameplay-tests` job. Check the
   run's full head SHA and workflow identity. Missing, skipped, cancelled,
   pending, or failed required jobs block the merge. Any additional GitHub
   required checks must also pass.
4. Immediately before merging, re-fetch the open pull request and verify the
   unchanged head, mergeability, the review, review threads, and latest
   required run. Supply the expected head SHA to GitHub's merge API and use the
   configured merge method.

The machine-readable settings are in `.github/merge-policy.json`. Review
feedback can be read as soon as the automatic reviews finish; there is no
fixed waiting period. Automated scope checks, syntax checks, and review
summaries do not replace the required review.

The repository is `AventurineDream/Trotline-Purridise`. If GitHub branch
protection or required-check policy cannot be verified, or protection changes,
investigate before merging. An unavailable protection endpoint is not evidence
that checks passed; verify the workflow run directly.
