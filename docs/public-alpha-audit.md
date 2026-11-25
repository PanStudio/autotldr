# Public-alpha audit and release candidate

**Date:** 2026-09-16  
**Starting checkpoint:** `6849cf21d6aae8803ff277e5ba3c848d97e5b68c` (`0.1.1`)  
**Historical candidate:** `0.2.0a1`, prepared locally for review; not published

**Update, 2026-09-17:** this candidate became `0.2.0` (D-055), which also replaced the
loopback runtime profiles with one OpenAI-compatible transport (D-056). Findings below
about loopback discovery describe the September 16 code, not 0.2.0. The dated audit
evidence remains a record of that run; its five-user publication gate is a follow-up
research plan, not a claim of completed user research.

## Product judgment

The vision is clear and worth preserving: a local-first Unix tool that explains a mixed
technical artifact through native, addressable evidence. The strongest part is the single
representation connecting spreadsheet formulas, data schemas, scientific metadata, code,
prose, cross-source relationships, and six output shapes. The next release should make that
existing product trustworthy and approachable before expanding its format inventory.

The previous checkpoint was not release-green. Its branch CI finished with **2 failed,
1,008 passed**; the tag CI exceeded the 30-minute limit. Both failures were in the live
Markdown render evaluator after the human-output escaping change. Historical local checks
were useful evidence but did not establish a passing release gate.

This audit covers architecture and documented scope, the public acquisition/synthesis/
rendering path, native XLSX semantics, watch state, MCP authority, test and release
infrastructure, dependency advisories, and an independent five-format acceptance package.
It combines code inspection, independent standards/spec reviews, adversarial regressions,
the full existing suite, package builds, and clean-install checks. It is not a formal proof
of every parser, every possible Excel expression, or every model-generated sentence.

## Repaired findings

| Area | Reproduced defect | Candidate behavior |
| --- | --- | --- |
| Formula identity | `"B7"` became a cell reference, `LOG10` became a cell, and apostrophes in quoted sheet names were misread | Native token operands distinguish strings, functions, and references; native sheet identity is preserved |
| Formula ranges | Only endpoints of `SUM(A1:A5)` survived; an interior dependency or cycle disappeared | Every populated cell in the range participates in the graph |
| Unsupported formula semantics | Named, external, dynamic, table, and intersection references could be silently incomplete or misrepresented | Explicit unresolved findings point to the formula; intersections do not invent union edges |
| Sparse spreadsheets | Reading a rectangle ending at `XFD1048576` could materialize billions of empty cells | Extraction uses the native sparse cell map |
| Workbook allocation | ZIP/XML input, merged ranges, and hyperlink ranges lacked consistent preflight limits | Package, XML, populated-cell, expanded-cell, dependency, and range-work limits fail explicitly |
| Native parser parity | Renamed XML parts and alternate namespaces could bypass newly added checks | XML bytes are inspected independently of suffix; allocation checks match native local-name handling |
| Ordinary range workloads | A first safety limit rejected 1,000 small formulas because every range scanned the whole sheet | A sparse row index and range cache bound actual examined candidates |
| Watch policy | Unchanged bytes hid a changed detail, model mode, configuration, or output budget | Cache reuse includes effective product/rendering policy and package version |
| Watch recovery | Deleted artifacts stayed absent; failed files and failed roll-ups were not retried | Missing outputs and failures are retried on the next scan; repeated failures remain failures |
| Watch completeness | A shared roll-up could omit failed members without reporting them | Failed members remain visible in the roll-up's gaps |
| Snapshot consistency | A watch hash and subsequent acquired source could represent different bytes | Successful publication requires the acquired snapshot hash to match the scan |
| Growing local files | Snapshot copying/hashing could keep chasing a continuously advancing EOF | Reads stop at the observed size plus one detection byte and reject the mutation |
| Deferred MCP work | A queued source could be replaced before execution | Execution rechecks the creating server's persisted roots |
| MCP result ownership | Retargeting a source symlink could transfer access to an already-computed private result | Historical results retain their original canonical source authority |
| MCP transport | Deep JSON, invalid numbers, duplicate keys, or escaped surrogates could break containment or produce ambiguous requests | Invalid requests are contained and later requests remain serviceable |
| Runtime discovery | A general URL opener could follow redirects or use an environment proxy when identifying the local model | Discovery uses direct loopback HTTP, rejects redirects, and retains bounded responses |
| Live evaluator | The reader did not understand inert Markdown code-span omission records | It accepts current and historical framing and continues checking exact records and digests |
| Budget implementation | Exhaustive search retained every prefix set and rebuilt the same projection during byte-count convergence | Prefix-set storage is linear and fixed-point counting reuses the projection; selection remains exhaustive |
| First-run instructions | Checkout installation did not activate the environment before using `autotldr` | Activation and a no-model evidence check are explicit |
| CI evidence | Dependencies were not explicitly locked, action runtimes were deprecated, and failed runs lost useful artifacts | Locked sync, pinned current actions, duration/JUnit reporting, and retained artifacts |

The independent reviews caught defects in the first repair itself. Those reproductions
became regression tests before the candidate was built. No frozen role/fusion/synthesis
corpus, truth label, policy, or scored result was regenerated or retuned.

## Verification and evidence boundary

Detailed local logs and generated artifacts are under `.agent/audit/2026-09-16/`.
The final release verification records the full-suite result and clean-install outcome.

- **Final focused regressions:** 176 passed, including local snapshots, watch, input
  integrity, product configuration/discovery, startup, MCP, and native XLSX correctness.
  Both independent review axes closed their blocking findings.
- **Installed wheel:** separate clean Python 3.12 environments passed base-only and
  all-extras checks outside the source checkout. The base environment contained only
  AutoTLDR, rendered addressed text, and explained the missing office extra. The complete
  install rendered a five-format folder to JSON/HTML, wrote and reused watch artifacts,
  exposed its runtime format inventory, and installed the bundled agent Skill.
- **Independent acceptance package:** Markdown, XLSX, SQLite, Parquet, and NetCDF; five
  acquired sources, 51 addressable units, 45 relations, and six gaps. Every relation endpoint
  resolves. ANSI, Markdown, HTML, PDF, JSON, and JSONL all fit an explicit 262,144-byte
  ceiling. This is an evidence-mode proof, not a substitute for live prose acceptance.
  The bounded PDF keeps four units and reports 47 omitted units; a separate reading PDF
  uses a 1 MiB ceiling to retain all 51. The size of its omission inventory is a real
  presentation cost, not missing acquisition evidence.
- **Dependency advisory scan:** `pip-audit` checked 29 locked runtime dependencies with
  no skipped entries and no known vulnerabilities reported at audit time. This is a dated
  advisory result, not a guarantee about unknown defects or future advisories.
- **Render compatibility:** ten text-render configurations retained identical output
  hashes or identical retryable budget refusals before and after the projection optimization.
  The small timing sample showed modest changes; it does not justify a broad speed claim.
- **Live model:** the required loopback LM Studio endpoint was unavailable. No model was
  loaded, invoked, unloaded, or substituted. Fresh prose quality and conformance are pending.
- **Remote CI:** the starting checkpoint's failures were inspected directly. The candidate
  workflow has not been run remotely because this working tree has not been pushed.

An initial test run overlapped the evaluator edit and therefore saw four additional
evaluator-hash mismatches. That run is retained as diagnostic evidence; it is not used as
the final regression result. The final run uses the corrected, stable evaluator.

## Release requirements recorded on September 16

1. Run fresh `setup`/`doctor` and the four documented acceptance jobs against one explicitly
   selected, eligible, already-active local generation model. Inspect claim entailment,
   useful detail progression, failure behavior, and latency; a valid citation ID is not
   proof that the wording follows from its evidence.
2. Run remote CI for the exact reviewed candidate commit and validate the built wheel on
   the supported Python 3.12 environment. The full optional parser set is qualified on
   Python 3.12; broader Python/platform support is not implied by the base package metadata.
3. Complete the five observed sessions in `first-user-validation.md`, or record a deliberate
   new release decision before changing that gate. No participant outcomes are fabricated.
4. Review the candidate artifact, support contact, public documentation, and release notes
   before publishing a GitHub release or uploading to a package registry.

## Highest-value improvements after this candidate

| Priority | Opportunity | Acceptance criterion |
| --- | --- | --- |
| High | Faster exact human-output budgeting | A fresh large mixed-folder workload completes within an agreed interactive latency target while retaining the maximal valid prefix and the complete omission inventory |
| High | Smaller agent JSON | A compact projection substantially lowers the observed 56–74 KB evidence-package output while preserving resolvable citations, gaps, exact omissions, and the model-run audit |
| High | Lower-friction local model onboarding | New users reach a useful cited answer without facilitator intervention, measured by the existing first-user plan |
| High | Independent claim-quality evaluation | Fresh non-hero sources expose unsupported compositions and referent errors; model profiles pass per-claim entailment checks instead of relying only on schema validity |
| Medium | More complete Excel references | Named ranges, structured table references, and reference expressions gain native addressed evidence and independent correctness tests before their unresolved findings are removed |
| Medium | Focused module boundaries | Split the largest acquisition, synthesis, rendering, and extension modules along measured responsibilities while preserving the public pipeline and startup contract |
| Medium | Watch operational behavior | Measure model calls, recovery latency, concurrent-writer behavior, and configuration changes during long-running sessions before adding more daemon features |

The exact-budget algorithm remains expensive for large collections. This audit removes
redundant work and quadratic prefix-set storage; it does not claim to have solved D-029's
latency problem. Watch retries occur on subsequent scans, not through an unbounded background
model retry loop. Native parsers run in-process; root guards and snapshots do not constitute
an OS sandbox. These limits belong in the release description.

## Deliverable

The deliverable is **AutoTLDR 0.2.0a1: a reviewable public-alpha release candidate of the
existing local-first Unix tool**. It consists of repaired source, regression evidence,
wheel/sdist artifacts, checksums, a version-bound participant bundle, a mixed-format example
in all six outputs, and this release-readiness record. The candidate preserves the four
lead jobs in `product-alpha.md`; it does not introduce a hosted service, GUI, chat product,
new model lifecycle authority, or a format-expansion sprint.

“Candidate prepared” and “public release validated” are separate states. Publication and
claims of first-user usefulness follow the remaining evidence requirements above.
