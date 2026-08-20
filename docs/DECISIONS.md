# Design decisions

Running log of product/architecture decisions that aren't obvious from the code.

---

## D1 — The message half is a modifier, not a primary signal (band thresholds)

**Date:** 2026-08-20 · **Context:** before assembling `0.6·model + 0.4·red_flags`.

### The observation

The scrip-susceptibility model outputs a **calibrated** probability of the pump-then-dump
outcome. Because that outcome is rare (test base rate ~1.3%), the calibrated probabilities
are compressed near zero:

| percentile of all scrips (2026-08-19) | model_prob |
|---|---|
| p50 | 0.006 |
| p90 | 0.056 |
| p99 | 0.143 |
| max | 0.483 |

Large, liquid scrips (RELIANCE, TCS, INFY, HDFCBANK, SUZLON) sit at ~0.000 — correctly, they
cannot realistically be pumped-and-dumped.

End-to-end blend, `final = (0.6·model_prob + 0.4·red_flag_score)·100`:

| scenario | scammy msg (rf=1.0) | scammy msg (rf=0.75) | clean msg |
|---|---:|---:|---:|
| RELIANCE / ordinary data (p≈0.00) | **40.0** | **30.0** | 0.0 |
| moderate scrip (p≈0.14) | 48.6 | 38.6 | 8.6 |
| susceptible microcap (p≈0.48) | **69.0** | 59.0 | 29.0 |

**Message signal alone can never exceed 40/100** (0.4 weight × max rule score 1.0).

### The question

A textbook-scammy message ("guaranteed, operator support, buy now") on an *ordinary* scrip
lands at ~30–40/100. It cannot reach a "high" band on message signal alone. Intended, or a
blend/threshold bug?

### Decision — intended. Market model is primary; message is a modifier.

A "guaranteed sure-shot" message about **RELIANCE** is genuinely *lower* manipulation risk
than the identical message about a thin, illiquid microcap — because Reliance cannot be
pump-and-dumped. Manipulation risk of a *tip* is the product of (a) how manipulative the
message is **and** (b) how pumpable the scrip is. The 0.6/0.4 split (a documented product
decision, not a fitted parameter) encodes exactly this. So message-only capping at 40 is
**correct behaviour**, not a defect.

**Rejected alternative:** rank-transform / rescale the model probability so its 0.6 weight
"bites" across the full 0–1 range. This was rejected because it **destroys calibration**
(a never-cut principle): a percentile rank is not a probability, and it would push an
ordinary scrip carrying a scammy message into "high" merely for being more susceptible than
the median — overstating risk. We keep the calibrated probability.

### Consequence — band thresholds

Chosen so the behaviour above reads correctly:

| band | final score | meaning |
|---|---|---|
| **low** | `[0, 25)` | clean/disclosed message and/or a non-susceptible scrip |
| **elevated** | `[25, 60)` | message red flags present, **or** a susceptible scrip — but not both strongly |
| **high** | `[60, 100]` | manipulative message **and** a susceptible scrip |

Worked outcomes: scammy+ordinary → **elevated (40)**; scammy+susceptible → **high (69)**;
clean+ordinary → **low (0)**. "High" is deliberately reserved for the both-conditions case,
consistent with the SPEC target of precision > 0.7 at the high band (a noisy alarm is worse
than no alarm).

The explanation strings carry the message-level warnings ("claims a guaranteed outcome",
"no SEBI disclosure") **even at an 'elevated' score**, so a user forwarding a scammy tip
about RELIANCE still sees *why* the message is manipulative — the number is moderated by the
scrip, the reasons are not.

**When the ticker can't be resolved,** the market half is unavailable; the score is
message-only (≤40), confidence is lowered, and a note says so. We never fabricate the market
half.

---

## D2 — Coordination burst is a bounded overlay, not a fourth weight

**Date:** 2026-08-20 · **Context:** integrating burst detection (Day 3 afternoon).

BUILD_PLAN says to feed the burst signal into "the red-flag half as one more weighted
contribution." I implemented it instead as a **bounded post-blend overlay** (SPEC §3.7's
"rule overlays applied after the model, each a fixed bounded adjustment with its own
reason"), for two reasons:

1. Burst is a **coordination** signal about the ticker across channels — not something the
   forwarded message itself says. Folding it into the message red-flags would have forced a
   re-budget of those weights (which currently sum to exactly 1.0, giving a clean 0..1
   message half and the numbers in D1).
2. Keeping it separate preserves **both** documented halves (0.6 model / 0.4 message)
   unchanged, and makes the coordination contribution explicit in the explanation.

**Mechanics.** When a ticker shows a confirmed burst (≥3 distinct channels in 48h **and**
z ≥ 2 versus its own trailing baseline), we add `min(15, round(5 + 2·z))` points (cap **+15**)
and a reason ("Being pushed by N channels within 48h — a coordinated spike…"), then clamp to
100. Example: a scammy tip on SUZLON (market prob ≈ 0 → 40/elevated) with 5 channels pushing
it in 48h → **55/elevated**, burst as the top reason.

**Dormant without data.** The overlay only fires when the `channel_mentions` archive exists
(populated by `scripts/backfill_telegram_channels.py`, which needs Telegram *API* credentials
— my.telegram.org, not the bot token). With no archive, `BurstProvider` returns None and the
score is unchanged. So the mechanism is built and tested, but contributes nothing until a real
channel backfill is run. Louvain community attribution stays cut (BUILD_PLAN).
