# TerraRisk Execution Board

**Live operating document.** Updated continuously, not rewritten. Supersedes no audit — assumes both are accepted and closed.
**Milestones this board serves:** (1) production deployed · (2) first customer validation · (3) first pilot · (4) FSID funding · (5) incorporation · (6) first paying customer.

---

## 1. Execution Board

### READY NOW — no blockers, can start immediately

| # | Task | Why it matters | Expected outcome | Owner | Effort | Depends on | Success criteria |
|---|---|---|---|---|---|---|---|
| R1 | **Read internship contract for IP clause** | Gates incorporation, FSID, and any WELL Labs pilot simultaneously. Cheapest high-severity unknown we have. | A definite answer: TerraRisk-owned / WELL Labs claim / ambiguous | Founder | 1 hr | — | You can state in one sentence who owns Service 2, citing the clause |
| R2 | **Diagnose production via DigitalOcean console** | Cannot demo to anyone without it. Blocks 3 of 4 milestones. | Root cause known: rebuilt / destroyed / firewall / billing | Founder → Claude | 1–2 hrs | — | We know *why* SSH keys changed, not just that they did |
| R3 | **Decide: public or private repo** | Currently public by inheritance, not decision. Affects moat narrative and interacts with R1. | A recorded decision + rationale | Founder | 30 min | R1 informs it | Decision written into the Decision Register |
| R4 | **Wire `resolution_flags`** | You present to hydrologists. Median village is sub-pixel for CHIRPS; the honesty field has never fired. | Sub-pixel villages self-declare their own uncertainty | Claude | 4 hrs | — | A 233 ha catchment returns `rainfall_sub_pixel`; a 3,000 ha one does not |
| R5 | **Clean local demo data** | Prevents demoing pre-migration artifacts by accident | One known-good demo dataset | Claude | 1 hr | — | Every catchment in the demo DB is real, post-migration, and named intentionally |
| R6 | **Compile Dataset & License Register** | Closes GEE/Esri/DataMeet licensing questions into one diligence artifact | One table: dataset → license → commercial status → action needed | Claude | 3 hrs | — | Every external dataset has a named license and a yes/no on commercial use |
| R7 | **Create Customer Discovery Log** | Evidence, not memory. The artifact that turns "we think" into "they said" | An append-only log with a fixed schema | Both | 30 min | — | Exists and has a template entry |
| R8 | **Draft WELL Labs outreach message** | The single highest-value conversation available to us | A sent message requesting a specific meeting | Both | 30 min | R1 (shapes framing) | Message sent, not drafted |

### BLOCKED — real dependency, not procrastination

| # | Task | Why it matters | Owner | Effort | Blocked by | Success criteria |
|---|---|---|---|---|---|---|
| B1 | Restore or rebuild production | Precondition for every demo | Claude | 4–8 hrs | R2 | `http://<host>/api/v1/health` returns 200 from outside |
| B2 | End-to-end production verification | "Deployed" ≠ "working" | Claude | 2 hrs | B1 | Real GEE report generated in prod, PDF downloads, no console errors |
| B3 | Rehearse both demo paths | Avoidable failures are the worst kind | Both | 2 hrs | B2, R5 | Both run start-to-finish twice without improvisation |
| B4 | WELL Labs meeting | The only real customer signal we have | Founder | 1 hr | R1, B3, R4 | Meeting held; discovery log entry written same day |
| B5 | DCC Bank meeting | Service 1's actual buyer | Founder | 1 hr | B3 | Meeting held; discovery log entry written same day |
| B6 | Incorporation | Cannot sign or invoice without it | Founder + external | Days | R1 + (B4 or B5 outcome) | Entity registered, or a dated decision to defer |
| B7 | FSID application | Funding milestone | Founder | Days | Requirements unknown, B4/B5 evidence | Submitted |

### WAITING FOR CUSTOMER — do not build on assumption

| # | Task | Why it must wait | Unblocked by |
|---|---|---|---|
| W1 | Pricing model | Any number invented now is fiction | A bank conversation about actual budgets |
| W2 | Pilot scope + success criteria | Scope defined without the customer gets renegotiated anyway | WELL Labs confirming interest |
| W3 | Product roadmap | Roadmaps built on inference are the drift pattern we already named | ≥3 discovery conversations |
| W4 | Pilot agreement template | Don't draft terms for a pilot nobody agreed to | Confirmed pilot interest + R1 |
| W5 | Field calibration of the stress score | Needs someone else's ground data | A data-sharing agreement |
| W6 | **Any new product feature** | Company rule | A dated, named customer request |

### NOT WORTH DOING NOW — explicitly deferred

| # | Task | Why not now |
|---|---|---|
| N1 | Pitch deck / exec summary | No customer evidence to put in it. Would be assumptions in slide form |
| N2 | Financial model | Depends on W1 |
| N3 | Raster tile serving / canal / LULC / terrain layers | No customer asked; needs their data |
| N4 | Any UI or map refinement | Already iterated four times on one comment |
| N5 | `SECURITY.md`, incident response, DR rehearsal, multi-tenancy | Real, but triggered by a paid pilot — not before |
| N6 | Deep competitor analysis | Needed for FSID, not for the next two meetings |
| N7 | Co-founder search | Premature before validation. You'd be recruiting to an unproven thesis |

---

## 2. Critical Path

```
  R1 IP check (1h) ──────────────┬──────────────► B6 Incorporation
   ★ gates 3 milestones          │
                                 ├──► R3 repo decision
                                 │
                                 └──► B4 WELL Labs ──┐
                                          ▲          │
  R2 Prod diagnosis (1-2h) ──► B1 Restore├─► B2 ─► B3│──► FSID
   ★★ gates 3 of 4 milestones             │          │  (+ requirements
                                          └─► B5 DCCB┘   still unknown)
  R4 resolution_flags (4h) ───────────────┘
```

**The two starred tasks:**

- **R2 → B1 (production)** blocks WELL Labs, DCC Bank, *and* FSID. Highest structural leverage. Nothing customer-facing moves until this clears.
- **R1 (IP check)** blocks incorporation, the WELL Labs *pilot* conversation, and FSID. Costs one hour. Worst effort-to-leverage ratio on the board — in our favour.

**They are independent.** Do R1 while production diagnosis is in flight. Do not sequence them.

**Shortest honest path to each milestone:**

| Milestone | Path | Realistic timeline |
|---|---|---|
| Production deployed | R2 → B1 → B2 | 2–5 days (depends on R2 root cause) |
| WELL Labs meeting | R1 + R4 + B3 → B4 | ~2 weeks (their calendar dominates) |
| DCC Bank meeting | B3 → B5 | ~2–3 weeks (institutional buyers are slow) |
| FSID pitch | B4/B5 evidence → application | 4–6 weeks, and **requirements still unknown to me** |

---

## 3. Decision Register

| # | Decision | When | Information required | Who provides it | Cost of deciding wrong |
|---|---|---|---|---|---|
| D1 | **Public vs private repo** | This week | R1 outcome; whether any moat depends on method secrecy | Founder (contract), Claude (what's exposed) | *Wrong-public:* methodology copied; weakens moat narrative. *Wrong-private:* loses portfolio credibility, low cost to reverse. **Asymmetric — private is the reversible choice** |
| D2 | **Incorporate now vs later** | After R1 + first customer signal | IP clarity; whether a pilot needs a legal entity; FSID requirements | Founder, CA/lawyer | *Too early:* compliance overhead, cost, possible restructuring. *Too late:* cannot sign a pilot or receive funding when the moment arrives |
| D3 | **GEE commercial licensing** | Before first paid pilot | Google's pricing at our volume; expected report count | Claude (usage), Google (pricing) | Running a paid pilot on the free tier is a license violation — reputationally and legally worse than the cost |
| D4 | **Esri basemap vs alternative** | Before first paid deployment | Esri commercial terms; cost of MapTiler/self-hosted tiles | Claude | Low severity, easy swap — the URL is already env-configurable |
| D5 | **Service 1 pricing model** | After ≥2 bank conversations | What banks currently spend on credit assessment; per-loan economics | Bank contacts | Wrong pricing kills a deal quietly — you rarely get told why |
| D6 | **Pilot: free / subsidised / paid** | At pilot offer | Whether the customer needs budget approval; what we need (data vs money) | Customer | Free pilots produce polite engagement, not commitment. Paid pilots are slower but real |
| D7 | **Co-founder or solo** | After validation, before fundraising | Whether gaps are skill-based or bandwidth-based | Founder | Adding one too early wastes equity; too late looks like key-person risk |
| D8 | **Raise or bootstrap** | After first pilot | Runway; whether the bottleneck is money or evidence | Founder | Raising on no evidence is a bad round or no round |
| D9 | **WELL Labs: customer, partner, or neither** | At/after B4 | Their reaction; the IP position | WELL Labs | Misreading this shapes the whole company narrative — and the FSID story |
| D10 | **Open-source strategy** | Only if D1 = public | Whether openness is a distribution strategy or a default | Founder | Half-open with no strategy gets the costs of both models and the benefits of neither |

---

## 4. Customer Validation System

### 4.1 Before every meeting

- [ ] Production verified live **that morning**
- [ ] Demo rehearsed once, same day
- [ ] Discovery log entry pre-created with date, person, role, company
- [ ] One specific ask decided in advance
- [ ] Known-limitations list open in another tab

### 4.2 Agenda (45 min, same structure every time)

| Time | Segment | Purpose |
|---|---|---|
| 0–5 | Context, no pitch | Establish why you're there |
| 5–20 | **Their world.** Questions only. No product. | Learn how decisions actually get made |
| 20–30 | Show, briefly | Anchor the conversation in something concrete |
| 30–40 | Their reaction — mostly silence from you | Real signal lives here |
| 40–45 | The ask + next step | Convert to commitment |

**Ratio to hold:** they talk 70%, you talk 30%. If it inverts, you pitched instead of learning.

### 4.3 Questions to ask

**WELL Labs**
- "Walk me through the last time your team decided which villages to visit. What did you actually look at?"
- "What happens today when a community hydrologist's reading disagrees with a satellite estimate?"
- "How do you currently pick a control village for a difference-in-differences comparison?"
- "What's the most annoying part of producing a village water account right now?"
- "If this existed and worked perfectly, whose job changes — and how would they feel about that?"
- "What would have to be true for this to be worth your team's time?"

**DCC Bank**
- "Walk me through the last KCC application you rejected. What made you reject it?"
- "When a crop loan goes bad, when do you find out — and what did you know beforehand?"
- "Who decides whether to approve, and what's on their desk when they decide?"
- "What do you currently spend on assessing agricultural risk — people, time, or vendors?"
- "What would your board need to see before approving a new assessment tool?"

### 4.4 Questions never to ask

| Never ask | Why | Ask instead |
|---|---|---|
| "Would you use this?" | Hypothetical. Invites politeness | "What do you do today?" |
| "Do you like it?" | Fishes for compliments | "What's confusing or wrong here?" |
| "How much would you pay?" | Invented numbers | "What do you spend on this today?" |
| "Would you pilot this?" *(too early)* | Traps them into a soft yes | "What would have to be true first?" |
| "Don't you think X is a problem?" | Leading — you supplied the answer | "What's the hardest part of X?" |
| "Is this better than Jaltol?" | Invites diplomacy, not truth | "Where does your current approach fall short?" |
| Anything revealing the answer you want | Contaminates the signal | Open, past-tense, behavioural |

### 4.5 Evidence to collect

Rank by strength — compliments are the weakest signal in the room:

1. **Money** — budget named, LOI, pre-order
2. **Reputation** — intro to their boss, to a peer institution, to a partner
3. **Time** — a second meeting scheduled, a data-sharing offer, a colleague pulled in
4. *(weak)* Verbal enthusiasm with no commitment

Also capture: verbatim quotes about pain, current tools/workarounds, who actually signs, what "working" means to them.

### 4.6 Immediate follow-up — same day, non-negotiable

- [ ] Discovery log entry written while memory is fresh
- [ ] Verbatim quotes captured, not paraphrases
- [ ] Commitment level recorded (money / reputation / time / none)
- [ ] Thank-you with the agreed next step in writing
- [ ] Any feature request logged with date, person, exact words

### 4.7 What can be decided after one meeting

**Can decide:** wording and framing changes · which service to lead with · demo order · known-limitation phrasing · whether to pursue them further.

**Must wait for pattern (≥3 conversations):** new features · roadmap changes · pricing · architecture · market positioning · pivots.

**One customer's request is a data point. Three customers with the same request is a signal.**

---

## 5. Founder Dashboard

Filled every Friday. Six questions, nothing else. If a row is empty, that's the week's answer.

```
TERRARISK — WEEK OF ____________

1. WHAT DID WE BUILD?
   (Ship-level only. "Nothing, we were selling" is a valid and often good answer.)

2. WHAT CUSTOMER EVIDENCE DID WE COLLECT?
   Conversations: ___    New quotes: ___    Commitments (money/reputation/time): ___
   ⚠ Two consecutive zero weeks = we have drifted back to building

3. WHAT BUSINESS RISK WAS REDUCED?
   (IP, incorporation, licensing, pricing clarity)

4. WHAT SCIENTIFIC RISK WAS REDUCED?
   (Calibration, honesty flags, validation, expert review)

5. WHAT INFRASTRUCTURE RISK WAS REDUCED?
   (Production uptime, deployment, backups, security)

6. WHAT DECISIONS ARE WAITING?
   Decision | Blocked on | Days waiting
   ⚠ Anything waiting >14 days is being avoided, not deliberated

WEEK'S ONE-LINE VERDICT:
Did this week increase the probability of a pilot, funding, or a customer? YES / NO / PARTLY
```

---

*Board reviewed weekly. Tasks move between columns as dependencies clear — nothing is deleted, so we can see what we chose not to do and why.*
