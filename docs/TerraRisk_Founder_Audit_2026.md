# TerraRisk Founder Audit — 5 August 2026

**Prepared as:** technical co-founder / CTO, not engineer.
**Trigger:** explicit company-principles reset — "Customer before Code, Scientific honesty before impressive visuals, Product before Features, Evidence before Assumptions, Revenue before Scale."
**Grounding:** every factual claim below was checked against the live repo, the running (and non-running) infrastructure, and `docs/DECISIONS.md` in this session — not recalled from memory alone. Production was re-probed immediately before writing this: still unreachable (host key rejected, nginx 404 on every path, including `/api/v1/health`).

---

## Part 1 — Assumption Audit

### Validated (real evidence exists)

| Assumption | Evidence |
|---|---|
| The GEE pipeline produces real, regionally-correct output | Real jobs run this session: 564–640 mm/yr annualised rainfall for semi-arid Raichur, across 4 real villages, with genuinely different readings per neighbour (not shared-pixel artifacts) |
| Real Raichur village geometry now exists | Measured directly in PostGIS: 0 of 864 villages remain 5-point rectangles (was 542/542); district coverage 0.6% → 97.8% |
| The recommendation engine is internally consistent | 110+ deterministic unit tests, same input → same output, every recommendation traces to a real stored field |
| WELL Labs gave one piece of direct, real product feedback | Vivek Srinivasan, verbatim: *"why not represent this spatially?"* — a real data point, not fabricated |
| TerraRisk's positioning against WELL Labs' public methodology is evidence-grounded | Alignment report cites specific WELL Labs publications for every comparison, not guesses |

### Unvalidated (plausible, no real evidence yet)

- That WELL Labs actually wants a district-wide village water-stress screening tool in their workflow — inferred from public materials, never confirmed in a direct conversation.
- That DCCB Latur (or any bank) wants this product, in this form, at any price — **no LOI, no pilot agreement, no documented conversation exists anywhere in this repo.**
- That the composite 0–100 recharge-stress score would survive review by an actual practicing hydrologist — self-assessed only; the alignment report itself says no published WELL Labs score exists to check it against.
- That the Priority Queue's severity ranking matches how a real programme officer would triage field visits — flagged in the alignment report as the least publicly checkable dimension.
- That "FSID" would view TerraRisk favorably at its current stage — no information available to assess; this is a gap in my knowledge, not a judgment.

### Dangerous (if wrong, actively damages the company)

1. **"TerraRisk's IP is unambiguously ours to commercialize."** Service 2 was conceived and built during/adjacent to a WELL Labs internship. No IP-assignment or internship-contract terms are documented anywhere in this repo — I searched. If the internship agreement contains standard work-product IP-assignment language, WELL Labs or its affiliated institution could have a legitimate claim on part of Service 2. **This must be checked against the actual signed internship paperwork before any incorporation filing, funding conversation, or pilot agreement that lists Service 2 as a company asset.** This is the single highest-severity item in this entire audit — not because it's necessarily true, but because everything downstream (incorporation, fundraising, a WELL Labs pilot itself) is unsafe to build on top of an unanswered version of this question.
2. **"WELL Labs is a validated pilot/partner we can name in investor materials."** No signed pilot, LOI, or MOU exists — and no follow-up conversation has happened since Vivek's one comment. Naming WELL Labs as a "customer," "pilot," or "partner" in an FSID application or pitch deck before they agree to that characterization risks both the relationship and misrepresentation to a funder.
3. **"Our GEE usage is free and sustainable at pilot scale."** `docs/DECISIONS.md` already, correctly, flags this: *"GEE's free tier is noncommercial/research use only — selling to a bank requires a paid Earth Engine commercial license via Google Cloud, budgeted for at the paid-pilot stage, not before."* The dangerous failure mode is forgetting that "not before" deadline and running an actual paid bank pilot on the free tier.
4. **"The Esri World Imagery basemap is fine to keep using."** Also already self-flagged in `DECISIONS.md`: *"free with attribution for dev/demo use, licensing review required before commercial deployment."* That review has not happened.
5. **"Local demo data is safe to show."** The local database mixes real post-migration GEE reports with earlier artifacts. Nobody should run a live demo without first confirming exactly what's in the database that day.
6. **"Production being down is a minor, ongoing TODO."** A company that cannot currently be reached by anyone outside one laptop is not a company that can honestly claim "two production-ready services" — which matters for how any Phase 4 material describes current state to a funder.
7. **"It's fine to present the stress score without caveating it live, every time."** `resolution_flags` — the field specifically built to warn when a village is too small relative to a satellite product's pixel size — is hardcoded to `[]` and has never fired. Most Raichur villages (median ~715 ha) are sub-pixel for CHIRPS rainfall (~3,080 ha pixels). Presenting a number with more apparent certainty than the science supports, in front of a domain expert, is the fastest way to lose a room.

---

## Part 2 — Risk Register (ranked)

| # | Risk | Category | Severity | Likelihood | Why it's ranked here |
|---|---|---|---|---|---|
| 1 | IP ownership ambiguity (WELL Labs internship overlap) | Legal | Company-threatening if real | Unknown until checked | Gates incorporation, fundraising, and a WELL Labs pilot simultaneously |
| 2 | Production unreachable | Infrastructure | High | **Confirmed true right now** | Blocks every demo, every pilot conversation, every "show, don't tell" moment |
| 3 | Zero confirmed pilots or LOIs | Customer / Business | High | Confirmed true | This is the actual gap between "startup" and "project" |
| 4 | `resolution_flags` never wired + unvalidated composite score | Scientific credibility | Medium–high | Will surface on first serious technical review | Reputational, not existential, but fast to trigger |
| 5 | GEE / Esri commercial-license terms unresolved | Licensing | Medium | Certain to matter at first paid pilot | Already self-identified internally; not yet closed out |
| 6 | FSID readiness unknown | Funding | Unassessable | — | Information gap, not yet a risk — need program details from the user |
| 7 | No formal Dataset & License Register | Data governance | Medium | Matters at Phase 4/5 due diligence | Underlying facts exist (ODbL, Esri terms) but aren't compiled |
| 8 | No incorporated entity | Operational/Legal | Medium | Certain to matter once a pilot or funding offer is real | Can't sign anything, can't take payment, no liability shield |
| 9 | Core engineering quality | Technical | **Low** | — | Explicitly the one area that is NOT a bottleneck — tests pass, real data verified, caveat infrastructure exists (even if underused) |

**The one-line version:** the engineering is in better shape than the company. Every top risk is legal, commercial, or a validation gap — not a technical one.

---

## Part 3 — Milestone Roadmap

Only items that raise the probability of a pilot, funding, or a customer. No features.

| # | Milestone | Type |
|---|---|---|
| M1 | Resolve the IP-ownership question against the actual internship agreement | Legal check (not engineering) |
| M2 | Restore production | Infrastructure |
| M3 | Real follow-up conversation with Vivek — show v2, collect actual reaction, ask directly whether WELL Labs would consider a structured pilot | Customer validation |
| M4 | Same structured conversation with DCCB Latur or an actual bank contact | Customer validation |
| M5 | Wire `resolution_flags` (half a day) | Scientific honesty fix |
| M6 | Compile the Dataset & License Register; close out GEE/Esri commercial terms | Data governance / licensing |
| M7 | Incorporate — once a pilot, a funding requirement, or M1 makes it necessary, not before | Legal/operational |
| M8 | Draft Phase 4 investor materials — only once M3/M4 produce real evidence to put in them | Fundraising prep |
| M9 | FSID application, sequenced against its actual requirements once known | Funding |

M1 and M3 block almost everything else. They come first.

---

## Part 4 — BUILD / VALIDATE FIRST / DON'T BUILD

| Candidate action | Classification | Why |
|---|---|---|
| Wire `resolution_flags` | **BUILD** | Correctness/honesty fix, not a feature bet — needs no customer validation |
| Fix production deployment | **BUILD** | Infrastructure precondition, not a feature |
| Clean local demo/test data | **BUILD** | Trivial, prevents an embarrassing accidental demo of pre-migration data |
| Compile Dataset & License Register | **BUILD** | Documents facts that already exist; directly de-risks Phase 4/5 |
| Canal-command / LULC / terrain layers | **DON'T BUILD** | Needs WELL Labs' own data; building it unilaterally is the exact drift pattern already named and blocked |
| GEE raster tile serving (spatial "Option C") | **DON'T BUILD** | No customer has asked for it; TerraRisk has no per-pixel output to justify it yet |
| Further map/AOI polish | **DON'T BUILD** | The map exists in two forms already; a third refinement without new customer input repeats the drift |
| WELL Labs pilot proposal document | **VALIDATE FIRST** | Don't draft terms for a pilot that hasn't been discussed |
| Legal/IP check against internship terms | **VALIDATE FIRST** | This is a "go find out" action — can't be engineered around |
| Second follow-up conversation with Vivek | **VALIDATE FIRST** | This *is* the validation step |
| Pitch deck / Executive Summary / Financial Plan | **VALIDATE FIRST** | Needs at least one real customer-conversation outcome to be evidence, not fiction |
| Company incorporation paperwork | **DON'T BUILD YET** | Premature until M1, M3, or a funding requirement makes it necessary |

**The filter, applied:** for every BUILD item above — does it increase the probability of a pilot, funding, or a customer? Yes, all four, but instrumentally (credibility, precondition, hygiene, due-diligence readiness) — none of them are a customer-facing feature guess. That's the tell for what belongs in BUILD right now.

---

## Part 5 — The straight answer

**Is TerraRisk ready to demo?** Technically, close. The product itself (both services) is more solid than most pre-seed deep-tech demos. **Is TerraRisk ready to fundraise or sign a pilot?** No — and not because of the product. Because of M1 (IP), M2 (can't currently show anyone), and the fact that zero real customer conversations have happened since v1 shipped.

**Should we stop building and go talk to people?** Yes, with two exceptions: fix production first (you can't demo a dead server), and check the IP question first (you shouldn't build a company narrative you might have to unwind).

---

## Part 6 — TerraRisk Founder Operating System

The permanent workflow, from this point forward.

**1. How product decisions are made.** No feature ships without being traceable to either (a) a specific, direct request from a named customer/prospect in a real, dated conversation, or (b) a scientific/legal/credibility correction that needs no customer validation because it's a correctness fix, not a bet. A single comment from one contact earns one responsive iteration, then a follow-up conversation before iterating again — never a fourth or fifth round on the same unconfirmed guess.

**2. How engineering priorities are chosen.** Apply, in writing, in this literal order, before starting: Customer Value → Scientific Validity → Business Value → Engineering → Scale. If the honest answer to "which named customer conversation does this unblock, and when did they ask for it?" is "nobody asked, I'm inferring" — default to VALIDATE FIRST or DON'T BUILD.

**3. How customer feedback is processed.** Every piece of feedback gets logged — who, when, verbatim if possible — as a project memory *before* any engineering response is designed. Feedback is never acted on twice without a check-in in between.

**4. How startup documents are maintained.** `docs/` is the single source of truth. Strategic documents are dated and superseded, not silently overwritten — corrections get appended with the old number left visible (as already practiced this session with the alignment-score correction).

**5. How deployment is handled.** Production status is checked live, not assumed, at the start of any session that might involve a demo commitment. "Works locally" and "production-ready" are never used interchangeably.

**6. How investor preparation is handled.** Phase 4 materials do not start until at least one Phase 3 milestone has produced real evidence. Every claim in an investor-facing document must trace to either a memory-logged customer interaction or a verified technical fact — never an assumption dressed as one.

**7. How pilots are executed.** No pilot terms are drafted before a real conversation establishes interest. Legal/IP questions are resolved *before* a pilot agreement is drafted, not discovered after signing.

**8. How risks are reviewed.** The Risk Register is revisited — updated, not rewritten — at the start of any new strategic mission.

---

*This document supersedes nothing; it is the first Founder Audit. Future audits should reference and update it, not replace it.*
