# GA-05A — Session-variation review guide for BIDS-oriented research
**Version:** 0.1 review draft · **Prepared:** 2026-10-17  
**Type:** Original, synthetic-only, non-normative community contribution proposal  
**Status:** Public standalone research-note draft in the owner's CohortSeal repository; NOT an upstream BIDS contribution, not reviewed by maintainers, not run with BIDS Validator, not scientifically validated.

## 1. What actual community problem motivates this?

[BIDS Validator issue #432](https://github.com/bids-standard/bids-validator/issues/432) reports that `MISSING_SESSION` is not emitted in a real example. Maintainer feedback in [the same discussion](https://github.com/bids-standard/bids-validator/issues/432#issuecomment-4935770020) says the rule was internally triaged **WONTFIX** because an empty-room recording is not expected to share human participant sessions. The issue remains *open* at the time checked, but **open does not mean an implementation is wanted**. This guide responds to the substantive false-positive problem with a **review-only reasoning table**, not an automatic error rule or feature request.

A separate [Neurostars question about duplicate `participants.tsv` IDs](https://neurostars.org/t/masivar-participants-tsv-contains-non-unique-participant-id-bids-validator-reports-tsv-index-value-not-unique/34647) illustrates why participant-index uniqueness and session metadata need to be distinguished. It was answered by community members; this guide does not reopen that thread.

**BIDS primary source:** [schema `participants` definition](https://github.com/bids-standard/bids-specification/blob/master/src/schema/objects/files.yaml), [session entity definition](https://github.com/bids-standard/bids-specification/blob/master/src/schema/objects/entities.yaml), [validator contribution policy](https://github.com/bids-standard/bids-validator/blob/main/CONTRIBUTING.md).

## 2. The three independent questions

| Layer | Question | Verdict and its meaning | What the guide cannot establish |
|---|---|---|---|
| A — Structural BIDS validity | Does a concrete dataset conform to a pinned BIDS spec, including prescribed participant rows and paths? | **Use the official BIDS Validator**; this guide includes only human inspection examples. | No official validator result is produced here. |
| B — Session design review | Is a missing/different session accidental, expected by study design, or an empty-room/calibration exception? | **REVIEW / INTENTIONAL / UNKNOWN**. No automatic failure from unequal session sets alone. | Does not certify missingness, consent or scientific design. |
| C — ML evaluation independence | Do observations associated with the same participant occur in disjoint evaluation partitions? | **PASS** if subject-level grouping is declared and respected; **FAIL** if same participant spans holdout and training. | Does not prove statistical validity, absence of pixel duplicates or clinical efficacy. |

**Critical distinction:** BIDS structural validity does not guarantee train/test independence. Conversely, a split problem does not imply a BIDS format error. Both need separate evidence.

## 3. Decision logic — to apply by hand, not automatic rules

1. **Scope the dataset root.** Identify the raw BIDS dataset to validate (the directory with `dataset_description.json` and subject folders). Data nested in a `sourcedata/` tree may be a distinct dataset needing separate validation. Do not assume its contents are in the parent validation scope. [Answered 2026 Neurostars example](https://neurostars.org/t/bids-study-dataset-structure-and-validation-issue/36130).
2. **Read the actual schema version.** If `participants.tsv` exists, `participant_id` must be one row per participant and cover the subject directories; session-varying metadata needs appropriate session-level representation. Do not pre-adopt proposed `participant+sessions.tsv` from [BIDS PR #2403](https://github.com/bids-standard/bids-specification/pull/2403), which remained an open proposal at inspection.
3. **Inventory observed subject×session keys.** Distinguish subject/session directory occurrence from inferred scheduled visit. Use an explicit study-design mapping to decide whether a visit was expected.
4. **Identify nonparticipant acquisitions.** A special `sub-emptyroom` or calibration record may have legitimately different sessions. Role must come from trusted protocol metadata/human review; do **not** infer exclusion just from a string. For ambiguous records use UNKNOWN, not an automatic waiver.
5. **Classify session gaps only after checking design.** `INTENTIONAL` if source-supported scheduling explains them; `REVIEW` if planned and missing; `UNKNOWN` if no plan exists. Unequal sets alone are not a new BIDS validation error.
6. **Independently inspect ML partitions** (if ML splits exist). If any genuine participant appears in train and test or train and validation when independence is required, classify **FAIL subject-group independence**. Never silently relabel or delete holdout records.
7. **Document provenance and limitations.** Record manifest revision, BIDS spec/validator release used if actually executed, dataset rights, group-key definition and the human review decision. The supplied CSV is only invented instructional metadata.

## 4. Hypothetical case matrix (not run, not official validator expectations)

| ID | Toy situation | Layer A (BIDS) | Layer B (design review) | Layer C (group ML split) |
|---|---|---|---|---|
| T01 | Two true participants each have A and B visits | Needs actual validator | Nothing unusual indicated | PASS if assigned wholly to one partition |
| T02 | Participant P02 has A but not B; B planned and missed | Not automatically a BIDS format failure | REVIEW with study plan | PASS if P02 remains in one partition |
| T03 | Participant P02 has only A; B was never planned | Not automatically a BIDS format failure | INTENTIONAL if protocol verifies | PASS if P02 remains in one partition |
| T04 | `sub-emptyroom` has unrelated calibration sessions | Do not infer whole-dataset validity | EXCEPTION only with trusted role proof | Exclude from participant check only if role proven |
| T05 | P03 has A in training and B in test | May be structurally valid BIDS | Session distribution unrelated | **FAIL** required participant independence |
| T06 | `participants.tsv` lists P04 twice | **Structural rule violation** for a participants table | Irrelevant | Not a substitute for checking group partition |
| T07 | Subject folder P05 has no matching `participant_id` in an existing participants table | **Structural rule violation** if table in scope | Irrelevant | Not a substitute for checking group partition |
| T08 | P06 has missing visit; no documented expected schedule | Not automatically invalid | **UNKNOWN** rather than automatic WARN | PASS if group not split |
| T09 | P07's session appears twice with incompatible train/test annotations | A participant/session mapping should be investigated (not a BIDS error conclusion) | REVIEW | **FAIL** if same participant in different partitions |
| T10 | Only an invented top-level study root contains participants table but subjects are inside `sourcedata/raw/` | Must select correct BIDS dataset root | Unknown | Cannot determine split integrity from parent directory alone |

T06 and T07 are *specification-based* examples, not newly discovered bugs. T02–T04 are motivated by the false-positive concern in #432. T05 and T09 concern independent ML design and do **not** claim a BIDS validator defect.

## 5. Companion synthetic fixture and manual reproduction

File: [`GA-05A_toy_sessions.csv`](GA-05A_toy_sessions.csv). **This CSV is an educational audit manifest, NOT an actual `participants.tsv` or valid BIDS dataset.** Every ID is fictional; there are no scans or images.

Columns: `record_id,subject_id,session_id,record_role,planned_status,observation_status,ml_split,reason`. `ml_split` is an analysis-time partition, **not a BIDS-defined field**. Values `NA` and `unknown` reflect review state, not measured biological outcomes.

Usage — entirely manually or in any browser-based CSV viewer, without installing software:
1. Open the fixture. Group rows by `subject_id`.
2. Mark all records with `record_role=calibration` as *potential special cases*, pending independent evidence of role, not because their IDs look different.
3. For genuine `participant` rows, check whether `planned_status` is `yes`, `no` or `unknown`; compare to `observation_status`. For `unknown`, preserve uncertainty.
4. Identify participant IDs with more than one non-`NA` `ml_split`. The toy example includes **P03** in both `train` and `test` (deliberate negative control).
5. Contrast the missing/planned session for **P02** with the never-planned P04 case. Missingness alone is not evidence of an invalid BIDS acquisition.
6. Do not run `bids-validator` on this single CSV and do not present manually inspected verdicts as actual software outputs. A genuine BIDS validation would require a complete, permission-compatible dataset and a logged, pinned validator version.

### Readout to report (after actual manual review)

```
BIDS_VALIDITY: NOT_RUN
SESSION_REVIEW: design-dependent (P02 needs investigation; P04 intentionally unplanned)
ML_PARTICIPANT_SPLIT_INTEGRITY: FAIL (synthetic P03 across train/test)
EMPTYROOM_STATUS: hypothetical calibration role; human confirmation required in real data
```

These are **expected interpretations from the fictional design**, not computed experimental measurements.

## 6. Limits and integration boundaries

- **Does not implement** `MISSING_SESSION`, change the BIDS specification, validate BIDS trees or submit a patch.
- **Not a proposal to reopen WONTFIX as a coding defect**; the concrete question for maintainers is whether a non-normative documented example would add value.
- Real acquisition schedules, group identity, calibration exceptions and data-use permissions require study-specific provenance, not filename heuristics.
- No claim of catching near-duplicate MRI pixels, hidden participant IDs, site confounding, temporal leakage, false-positive rates, statistical generalization, regulatory compliance or ethics/consent clearance.
- The guide's cases must not be used as ground truth for official BIDS-validator regression tests without maintainers establishing appropriate expectations.
- Not part of PsychNeuro OpenBench (P01); no overlap with PM-17's upstream patch, 8-target shortlist or 12-maintainer search. This is a GA-side, *standalone documentation proposal*, not a merged code contribution.

## 7. Release and licensing

- This **original guide** is released under **CC BY 4.0** (attribution required): https://creativecommons.org/licenses/by/4.0/
- The **entirely invented fixture** is released under **CC0 1.0** (public-domain dedication): https://creativecommons.org/publicdomain/zero/1.0/
- No upstream BIDS code or real dataset is reproduced or relicensed. Source links are citations, not copied assets.
- BIDS Validator's code uses an MIT license: https://github.com/bids-standard/bids-validator/blob/main/LICENSE ; those conditions matter **only if** actual MIT-licensed code is copied or adapted. Here none was.
- If the guide enters an upstream repo, obey that repo's existing license, CONTRIBUTING and conduct policy and obtain human approval; these suggested document licenses do not override project governance.
- If machine assistance is relevant under a target venue's policy, disclose it accurately; human reviewer must verify sources and claimed behavior.

## 8. Review gates and evidence

**Completed:** official sources inspected; issue #432 and comments read; authored the synthetic guide + fixture.  
**Public comment:** originally drafted separately and not necessarily posted; confirm current thread status and any later posting independently.  
**Not performed:** BIDS validator execution, subject-level audit on real data, upstream code modifications, published artifact, registration, participation or external endorsement.  
**Go/no-go:** GO to *ask whether a documentation-only example is welcome* **only after explicit approval and latest issue recheck**; NO-GO to implement an automatic `MISSING_SESSION` error on existing evidence.