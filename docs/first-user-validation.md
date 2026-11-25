# First-user validation plan

This is the preregistered private-alpha learning plan. It exists to keep product decisions
from being rewritten after seeing favorable or unfavorable sessions. The product contract
is `product-alpha.md`; the reproducible engineering gate is `../acceptance/README.md`.

**Release update, 2026-09-17:** D-055 makes owner acceptance and exact-commit CI the
publication gates for v0.2.0. This five-user study remains follow-up research with its
original measures and thresholds intact. No completed sessions or passing cohort are
claimed.

## Cohort

Recruit five terminal-capable users who did not work on AutoTLDR:

- two developers receiving an unfamiliar technical handoff;
- two research or data practitioners working with structured/scientific data; and
- one owner of a formula-heavy operational workbook.

Each participant brings one non-sensitive artifact that AutoTLDR has not been tuned or
evaluated against. Do not collect or retain the artifact after the session without explicit
permission. Never ask a participant to expose credentials, production secrets, protected
personal data, or regulated data.

## Session procedure

Keep the session to 45 minutes and observe rather than teach.

1. Give the participant the released installation instructions and stop talking.
2. Record whether they can reach a green `autotldr doctor`, every error they encounter,
   and whether recovery text is sufficient without developer intervention.
3. Ask them to use AutoTLDR on their artifact with no prescribed detail level.
4. Ask: “What is this artifact for, what matters, and what would you inspect next?”
5. Ask them to follow one important citation back to native evidence.
6. Ask them to identify one documented gap or limitation.
7. Have them compare the other two detail levels and explain the difference in their own
   words.
8. For an agent user, repeat one task with JSON and an explicit context budget; verify that
   the client preserves claims, gaps, and omissions rather than displaying only prose.

Do not rescue a confusing workflow until its failure and the participant's expected next
step have been recorded.

## Measures

Record these facts for every session:

- install-to-green-doctor time and intervention count;
- green-doctor-to-first-useful-answer time;
- chosen detail level and whether its meaning matched the participant's expectation;
- number of claims the participant judged useful, incorrect, unsupported, or redundant;
- whether the inspected citation resolved and entailed the claim;
- whether a gap changed the participant's confidence or next action;
- whether AutoTLDR improved the answer to the three comprehension questions compared with
  the participant's initial inspection method;
- the first missing capability they asked for; and
- whether they would use the product again on a similar artifact.

Record one privacy-safe JSON file per session by copying
`acceptance/session-template.json`. Use a pseudonymous participant ID and a generic
artifact kind only. Do not put a participant name, source path, source excerpt, artifact,
generated report, credential, or other source content in the record; the strict evaluator
rejects unknown fields and requires `source_content_recorded` to remain false.

After all five sessions, evaluate the preregistered gate without manually transcribing its
thresholds:

```bash
uv run python scripts/evaluate_alpha_sessions.py --json \
  session-1.json session-2.json session-3.json session-4.json session-5.json \
  > first-user-gate.json
```

The evaluator exits `0` only when every gate criterion passes, `1` for a valid but failed
cohort, and `2` for incomplete, unsafe, or structurally invalid records. Keep session files
and the report in gitignored `.agent/` state unless participants explicitly authorize a
different retention boundary. Durable conclusions contain aggregate findings only.

## Preregistered study criteria

The original private-alpha gate required all of the following across five sessions.
Evaluate the follow-up study against these same criteria:

- at least four participants reach green doctor without developer intervention;
- all five receive either a valid cited TLDR or a specific actionable decline—never an
  empty success or silent fallback;
- every sampled citation resolves, and at least 90% of sampled claims are judged entailed;
- at least four participants correctly explain gaps and the selected detail level;
- median green-doctor-to-useful-answer time, including local inference, is under five minutes;
- no participant reports an undisclosed source boundary or model lifecycle action; and
- at least three would use AutoTLDR again for the same job.

A failed gate is product evidence, not a reason to relax the threshold after the fact.
Classify each failure as onboarding, extraction, selection, synthesis, presentation,
authority, performance, or missing use case. Fix the highest-frequency/highest-severity
class before adding formats.

## Release posture

The first cohort should receive a versioned release bundle. The bundle contains the exact
wheel and sdist, rendered participant
guide, security and change notes, manifest, and checksums. Its builder requires an explicit
support contact and refuses overwrite:

```bash
uv build --out-dir dist
uv run python scripts/check_release.py dist
uv run python scripts/build_release_bundle.py \
  dist /new/path/autotldr-release \
  --support "PRIVATE SUPPORT CONTACT"
```

The participant sees the rendered form of `install-guide.md`, with an exact version and
support contact. Publication follows D-055: owner acceptance, remote CI for the reviewed
commit, clean installation, and the documented support boundary. Registry publication
must be recorded separately from a GitHub release.
