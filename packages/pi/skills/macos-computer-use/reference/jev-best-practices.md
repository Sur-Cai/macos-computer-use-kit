# Jev / TypeSafe System One — practices that survived contact with real use

Sources: TypeSafe documentation plus community write-ups (ArchCrux, flaviocopes,
systemonemodels, Bloss0m, apidog, volanea), 2026-09.

## It is a decision layer, not a workflow

```
LLM generates  |  Jev judges  |  code controls  |  humans handle the edges
```

Jev answers narrow questions inside a bounded option set and returns typed
answers plus calibrated probabilities. It does not write prose and does not do
multi-hop reasoning. Control flow and side effects stay in your code.

## Question design

1. **One judgment per question.** "Is this lead valuable, urgent, and likely to
   close?" is three questions. Split them and combine the answers in code.
2. **Match the primitive to the shape of the judgment:**
   - graded (severity, quality, relevance) → `score` (2–10 levels)
   - a single fact → `noul`
   - a fixed option set → `choice` (up to 255 options; use two stages beyond that)
3. **Describe situations, not degrees.** Each Score level should say what state
   it describes ("feature is broken but there is a workaround"), not "medium".
   Spell out the boundaries between adjacent options.
4. **Always provide an escape hatch:** `other`, `none_of_the_above`, `unknown`,
   `not_stated`, `needs_human_review`. If the option set cannot cover reality,
   the model can only pick a wrong answer.
5. **`instructions` and `criteria` must say the same thing**, in language a
   colleague would understand. Contradictions between them cost accuracy.
6. **Do not ask the model to explain itself.** The answer is the decision, the
   probability, and the confidence — nothing else.

## State

- **Include only what the judgment needs.** Irrelevant text measurably degrades
  accuracy (context rot). Filter deterministically when you can; when you cannot,
  use a `noul` per chunk to decide relevance and drop the rest.
- Request limit: 64K tokens, with `state` + longest question ≤ 32K.
- Treat user-controlled content as **untrusted input** (prompt injection). It must
  not be able to influence system permissions or policy.

## Parallelism (speculative fan-out)

- Put every **mutually independent** question in **one request** (the official
  cookbook reports 13 batched questions at 12.2× cheaper and 10× faster).
- Send a second request only when the next question depends on a previous answer
  (fetching new evidence, or determining the option set).
- The cost: you pay for judgments you may not use. In logs, distinguish
  `unused` / `rejected` / `policy_conflict`.

## Confidence and policy

- **Confidence is a model signal, not authorization.** Identity, permissions,
  resource scope, and approvals must be validated by the runtime.
- Set thresholds by **the cost of being wrong**: read-only or reversible → low;
  recoverable external action → high; irreversible or sensitive → a human.
- Starting reference (calibrate on your own data): >0.85 act; 0.55–0.85 escalate
  to a stronger model or a second judgment; <0.55 ask a person.
- Keep the **raw dimensions + weights version + final routing**, not just one
  composite score.

## Operations

- **Pin the model version.** `jev-latest` drifts; automation paths should use a
  concrete version such as `jev-1.13.0` (in this toolkit: `TYPESAFE_MODEL`).
- Version questions, thresholds, and the decision schema independently.
- Log state snapshots, question versions, model version, probabilities, policy
  version, and the final outcome — otherwise you cannot reproduce or calibrate.
- Test on labeled real samples: beyond the confusion matrix, watch the
  coverage–risk curve, escalation rate, p95 latency, and cost per successful task.
- Classify failures: schema failures / semantic failures / calibration failures /
  policy failures — each has a different fix.

## Where not to use Jev

Arithmetic, exact counting, date math, multi-hop reasoning, anything requiring
generated text, anything requiring reading an image, and **anything ordinary code
already decides correctly**. A free `if` beats a fraction-of-a-cent `if` that can
be wrong.

## How this maps onto the toolkit

- `macos-cu jev guard` — pre-action guard. One request fans out right-target /
  input-correctness / blocker / next-action judgments, and code applies the
  thresholds. Only `switch_target` and `retype_input` may come from the model,
  because neither can send or submit anything; everything else asks the user.
- `macos-cu jev select` — element selection from AX candidates, with a `none`
  escape hatch and a confidence gate
  (`gate: auto | low_confidence_review | no_match`).
- Blank-frame detection, overlay drawing, and signature comparison deliberately
  do **not** use Jev: they are deterministic and free.
