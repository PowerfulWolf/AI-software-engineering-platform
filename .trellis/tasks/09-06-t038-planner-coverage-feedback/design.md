# Bug analysis: Planner coverage feedback

## 1. Root cause category

B/D/E: cross-layer feedback and test gap, plus implicit assumption that a model can reconstruct
all global IDs and repair itself without receiving omissions. The coverage validator is correct.
The original live invalid response was not retained; its exact missing set is unknown. A deterministic
service/journal reproduction proves both omission paths lose feedback, not what the live model omitted.

## 2. Why fixes failed

No prior production fix attempted. First regression fixture used approval for the pre-extension
Product and correctly tripped the approval fence; corrected fixture identity before reproducing
the actual feedback defect. The true red signal was unchanged next_action after rejected coverage.

## 3. Prevention mechanisms

| Priority | Mechanism | Action | Status |
|---|---|---|---|
| P0 | Runtime | Keep strict coverage and three-attempt limit | DONE |
| P0 | Context | Share exact acceptance IDs between guard and context | DONE |
| P0 | Persistence | Append safe rejection diagnostics, never overwrite accepted plan | DONE |
| P0 | Tests | Restart, omission and exhaustion through real journal | DONE |

## 4. Systematic expansion

Other semantic Design/Plan errors still use their existing failure paths. Full rejected-provider
output storage is a separate evidence/privacy design, not added here. This fix is deliberately
limited to the observed coverage class; no arbitrary exception text is fed back. No schema fields
or migrations are needed. No spec-template tree exists in this repository.

## 5. Knowledge capture

Updated `.trellis/spec/core/multi-directory-delivery.md` with signatures, context fields, rejection
semantics, validation matrix, safe/unsafe patterns and executable regression assertions.
