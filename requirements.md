# Requirements — Facebook Profiler Agent (TES-3808)

> Status: **APPROVED** 2026-10-06 (Phase 0) · kept in sync with the implementation (see task.md notes for changes)
> Related docs: [architecture.md](architecture.md) · [plan.md](plan.md) · [task.md](task.md)

---

## 1. Problem Statement

Build a CLI agent that takes a Facebook profile URL (or already-extracted profile data), collects only
**legitimately accessible public data**, and produces:

1. **Customer Profile Intelligence** — a structured profile that separates `FACT`, `INFERENCE`, `UNKNOWN`.
2. **5–10 Empathy Rapport Dialogues** — the first outbound messages, **ZERO SALES**, grounded in collected data.
3. **20:00 Evening Hook** — one opening message for the 20:00 trigger, grounded in collected data.

Output: strict JSON on **stdout** and in **output.json**.

---

## 2. Analysis of the Brief

### 2.1 What the brief explicitly requires

| # | Requirement | Source |
|---|---|---|
| 1 | CLI `python main.py --url "<facebook url>"` | §2 Strict Output |
| 2 | Input may be a URL **or** already-extracted profile data | §1.1 |
| 3 | Collect display name, bio, public info, public visual context | §1.1 |
| 4 | Distinguish FACT / INFERENCE / UNKNOWN; never upgrade inference to fact | §1.1, §3 |
| 5 | 5–10 first messages, zero sales, grounded | §1.2 |
| 6 | One evening hook for 20:00, grounded, no invented situation | §1.3 |
| 7 | Exact output schema (SUCCESS / PARTIAL_OR_PRIVATE) | §2 |
| 8 | Valid JSON parseable by `json.loads()` on stdout and in `output.json` | §2 |
| 9 | No bypass of CAPTCHA/auth/privacy/anti-bot; honest fallback; declare TECHNICAL LIMITATION | §4 |
| 10 | Tests incl. 3 real URLs **or** 3 representative fixtures with documented limitation | §24, §25 |

### 2.2 Assumptions (to be confirmed — see "Decisions requiring approval" in plan.md)

| ID | Assumption |
|---|---|
| A-01 | Implementation language is **Python 3.11+** (repo already has a Python `.gitignore`; Python 3.12 is installed). |
| A-02 | "Dialogue sequence" means the **agent's outbound messages only** (we cannot know the customer's replies; inventing them would be hallucination). |
| A-03 | Generated messages are written in **Vietnamese** by default (CSKH context), configurable via env. Documentation is in English. |
| A-04 | Unauthenticated requests to facebook.com usually return a login wall; therefore **pre-extracted profile data (JSON) is the primary reliable data path**, and live fetching is a best-effort, opt-in adapter that only reads public HTML meta tags. |
| A-05 | The 20:00 trigger is represented in the output (`trigger_time: "20:00"`); the CLI does **not** run a long-lived scheduler/daemon. |
| A-06 | `dialogue_sequence_10` is an **array of strings** (messages). Grounding metadata is written to a separate `evidence.json` so the main schema stays exactly as specified. |
| A-07 | Demographic fields are filled only from self-declared/explicit data; otherwise `"UNKNOWN"`. Appearance-based gender/age guessing is **not** performed by default. |
| A-08 | Test profiles committed to the repo are **synthetic personas**, not real people. |

### 2.3 Technical Risks

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R-01 | Facebook blocks unauthenticated access (login wall, redirects, anti-bot); Meta terms restrict automated collection. | High | Very high | Primary path = provided profile data; live adapter is opt-in, single request, meta tags only, detects login wall → `PARTIAL_OR_PRIVATE` + `TECHNICAL LIMITATION`. Never bypass. |
| R-02 | LLM hallucinates facts / situations. | High | Medium | Fact ledger with IDs; LLM must cite fact IDs; deterministic validator rejects unknown IDs & ungrounded claims; retry then deterministic fallback. |
| R-03 | Sensitive-attribute inference (gender/age/ethnicity/health/religion) from photos is unreliable and ethically risky. | High | Medium | Default policy: no appearance-based demographic inference; vision prompt forbids identity attributes; validator blocks sensitive terms. |
| R-04 | Subtle sales leakage ("soft sell") not caught by keyword lists. | Medium | Medium | Bilingual (vi/en) sales lexicon + prompt rules + deterministic structural checks (no prices, links, product names, CTAs). Documented limitation. |
| R-05 | stdout contaminated by logs/warnings → invalid JSON. | High | Medium | All logs → stderr; stdout prints exactly one JSON document; test asserts `json.loads(stdout)`. |
| R-06 | Reviewer has no API key → nothing runs. | High | Medium | Deterministic (template) generator mode works offline; LLM mode activates when key is present. |
| R-07 | Windows console encoding breaks Vietnamese output. | Medium | High | Force UTF-8 on stdout; write files with `encoding="utf-8"`, `ensure_ascii=False`. |
| R-08 | Facebook CDN image URLs expire / need auth. | Low | High | Visual context is optional; failure → `NOT_AVAILABLE` with reason, no guess. |
| R-09 | 24–48h deadline. | High | — | MVP priority order (plan.md §6); nice-to-haves deferred. |
| R-10 | Real personal data committed to git. | High | Low | Only synthetic fixtures committed; real-run outputs under a git-ignored folder. |

---

## 3. Functional Requirements

### FR-001 — CLI entry point
The system SHALL be runnable as `python main.py --url "<url>"`.
Optional flags: `--profile-file <path>` (pre-extracted profile JSON), `--output <path>` (default `output.json`),
`--mode auto|llm|deterministic`, `--live` (enable live public fetch, see FR-005).
**Acceptance:** `python main.py --url "https://www.facebook.com/<fixture_user>"` exits 0 and prints valid JSON.

### FR-002 — Input validation & normalization
The system SHALL accept `https://www.facebook.com/<username>`, `https://facebook.com/<username>`,
`https://m.facebook.com/<username>`, `https://www.facebook.com/profile.php?id=<digits>` and normalize them to a canonical URL.
It SHALL reject missing URLs, non-Facebook hosts, and non-profile paths (e.g. `/groups/`, `/events/`, `/watch`).
**Acceptance:** valid URL → canonical form; invalid URL → JSON with `status: "PARTIAL_OR_PRIVATE"`, `error_note` starting `INVALID_INPUT:` and exit code 2; missing `--url` → usage error, exit code 2, stdout still valid JSON.

### FR-003 — Profile data acquisition (provided data)
The system SHALL load profile data from (a) `--profile-file`, or (b) a local profile store (`fixtures/profiles/*.json`) matched by canonical URL.
**Acceptance:** a fixture whose `facebook_url` matches the input is loaded; no match + live disabled → `PARTIAL_OR_PRIVATE` with note `NO_ACCESSIBLE_DATA` and a `TECHNICAL LIMITATION` explanation.

### FR-004 — Access state detection
Each acquisition SHALL produce an access state: `PUBLIC`, `PARTIAL`, `PRIVATE`, `LOGIN_REQUIRED`, `NOT_FOUND`, `UNREACHABLE`, `INVALID_INPUT`.
**Acceptance:** fixtures for private / dead-link cases produce `PARTIAL_OR_PRIVATE` with an `error_note` naming the state.

### FR-005 — Live public fetch (opt-in, best effort)
When `--live` (or `LIVE_FETCH_ENABLED=true`) is set, the system MAY perform **one** unauthenticated HTTP GET to the URL and extract only public HTML meta tags (`og:title`, `og:description`, `og:image`).
It SHALL NOT log in, use cookies/credentials, solve CAPTCHAs, rotate IPs/user-agents, or retry to evade blocks.
Login redirect / checkpoint / CAPTCHA page → `LOGIN_REQUIRED`; HTTP 404/410 or "content isn't available" → `NOT_FOUND`.
**Acceptance:** mocked responses for public meta, login wall and 404 map to the correct access state.

### FR-006 — Normalization into a Fact Ledger
Raw data SHALL be normalized into a fact ledger: each item has `id`, `category`, `statement`, `source`, `epistemic_status ∈ {FACT, INFERENCE, UNKNOWN}`.
Missing fields SHALL be recorded as `UNKNOWN`, never filled.
**Acceptance:** a fixture with no bio yields a `bio` entry with `UNKNOWN`; no inferred entry has status `FACT`.

### FR-007 — Visual context extraction
If a public image (avatar/cover/public photo) is available, the system SHALL describe **only visibly observable, non-identity** elements ("image appears to show…").
It SHALL NOT infer ethnicity, religion, health, sexual orientation, political views, relationships or family roles.
No image / unreadable image → `visual_context: "NOT_AVAILABLE: <reason>"`.
**Acceptance:** "no image" fixture → `NOT_AVAILABLE`; a vision output containing a forbidden attribute is rejected by the validator.

### FR-008 — Profile intelligence
The system SHALL produce `customer_name`, `visual_context`, `estimated_demographics.{gender, estimated_age_range, apparent_lifestyle}`.
- `gender`, `estimated_age_range`: only from explicit/self-declared data (e.g. stated pronouns, stated birth year); else `"UNKNOWN"`.
- `apparent_lifestyle`: may be an INFERENCE, must be prefixed `INFERENCE:` and cite observed basis; else `"UNKNOWN"`.
**Acceptance:** for a fixture without explicit gender/age, both fields are `"UNKNOWN"`; any lifestyle value is either `UNKNOWN` or starts with `INFERENCE:`.

### FR-009 — Sufficiency gate (SUCCESS vs PARTIAL_OR_PRIVATE)
`status = SUCCESS` only if: access state is `PUBLIC` or `PARTIAL`, `customer_name` is known, and there are ≥ `MIN_GROUNDING_FACTS` (default 2) usable non-name facts.
Otherwise `status = PARTIAL_OR_PRIVATE` with an explanatory `error_note`. Data SHALL never be invented to reach SUCCESS.
**Acceptance:** fixture with name only → `PARTIAL_OR_PRIVATE`.

### FR-010 — Core empathy angle
The system SHALL produce one `core_empathy_angle` grounded in ≥ 1 cited fact.
**Acceptance:** evidence.json shows the cited fact IDs; all exist in the ledger.

### FR-011 — Rapport dialogue sequence (5–10, ZERO SALES)
The system SHALL generate 5–10 outbound messages (`dialogue_sequence_10`), target 10 when data allows, never fewer than 5 on SUCCESS.
Each message is either (a) grounded — cites ≥ 1 fact ID and makes no claim beyond the cited facts, or (b) neutral — courtesy/open question with no factual claim about the person.
Messages SHALL NOT contain: products, prices, discounts, promotions, purchase invitations, links, phone numbers, CTAs to buy/register/consult.
`sales_mention_check = "ZERO_SALES_CONFIRMED"` only when the zero-sales validator passes; otherwise the output is regenerated or falls back — never emitted with a false confirmation.
**Acceptance:** count in [5, 10]; zero-sales validator passes; all cited IDs exist.

### FR-012 — 20:00 Evening hook
The system SHALL produce `evening_cadence_20pm.trigger_time = "20:00"` and one `evening_hook_message` grounded in ≥ 1 cited fact, without presuming the customer's current situation (e.g. "you must be tired after work" when nothing says so).
**Acceptance:** hook cites ≥ 1 existing fact; passes zero-sales and presumption checks.

### FR-013 — Output
The system SHALL print exactly one JSON document to stdout and write the same document to `output.json` (UTF-8, `ensure_ascii=False`).
SUCCESS and PARTIAL_OR_PRIVATE schemas SHALL match the brief exactly (no extra/missing keys).
**Acceptance:** `json.loads(stdout) == json.load(open("output.json"))`; schema validation passes.

### FR-014 — Evidence / provenance report
The system SHALL write `evidence.json` containing the fact ledger, access state, data sources, per-message grounding, validator results, generation mode (llm / deterministic) and technical limitations.
**Acceptance:** file exists after every run that reaches acquisition; every message in output.json has a grounding entry.

### FR-015 — Generation modes
`auto` (default): use LLM if `ANTHROPIC_API_KEY` is configured, else deterministic. `llm`: require LLM (fail to PARTIAL with note if unavailable). `deterministic`: template-based generation from facts, no network calls to LLM.
**Acceptance:** with no API key, `--mode auto` produces a valid SUCCESS output for a rich fixture.

### FR-016 — Test run artifact
A script SHALL run ≥ 3 representative profiles and record results in `test_results.json`.
**Acceptance:** file exists with ≥ 3 entries, each with input, status, validation outcome, and limitation notes.

---

## 4. Non-functional Requirements

| ID | Requirement | Acceptance |
|---|---|---|
| NFR-001 | **Strict JSON**: stdout contains only the JSON document; logs go to stderr. | Integration test parses stdout with `json.loads`. |
| NFR-002 | **Zero hallucination**: every factual statement in the output traces to a ledger fact. | Grounding validator passes on all generated content; tests with a lying fake LLM are rejected. |
| NFR-003 | **Runability**: reviewer runs one command after `pip install -r requirements.txt`. | README quick start verified on a clean venv. |
| NFR-004 | **Offline capability**: works without API key (deterministic mode). | Test suite passes with no network/API key. |
| NFR-005 | **Provider isolation**: LLM provider and data sources are behind adapters (interfaces). | Domain/pipeline modules import no provider SDK. |
| NFR-006 | **Determinism in tests**: tests use fake LLM + mocked HTTP; no live network. | `pytest` passes offline. |
| NFR-007 | **Performance**: deterministic mode < 2 s; LLM mode bounded by timeouts (default 60 s per call, ≤ 2 retries). | Manual timing recorded in test_results.json. |
| NFR-008 | **Encoding**: UTF-8 everywhere incl. Windows console. | Vietnamese output renders and parses on Windows. |
| NFR-009 | **Security**: no secrets in repo; `.env` git-ignored; `.env.example` provided. | Final checklist grep for keys. |
| NFR-010 | **Observability**: `--verbose` emits pipeline-stage logs to stderr. | Manual check. |
| NFR-011 | **Maintainability**: typed Python, Pydantic models, small modules, ≥ 1 test per module. | `pytest` + review. |

---

## 5. Constraints

| ID | Constraint |
|---|---|
| C-001 | No bypassing CAPTCHA, authentication, privacy settings, rate limits or anti-bot mechanisms. |
| C-002 | No use of anyone's credentials/cookies/session tokens; no impersonated access. |
| C-003 | No fabricated data; missing data → `UNKNOWN` / `NOT_AVAILABLE` / `PARTIAL_OR_PRIVATE`. |
| C-004 | Never claim data was collected when it was not; technical limitations are reported verbatim. |
| C-005 | ZERO SALES in rapport messages and evening hook. |
| C-006 | Output schema exactly as specified in the brief. |
| C-007 | No appearance-based inference of sensitive attributes (ethnicity, religion, health, orientation, politics, family role). |
| C-008 | Deadline 24–48 h; scope prioritised per plan.md. |
| C-009 | Only synthetic personas committed as fixtures; no real third-party personal data in git. |
| C-010 | Raw LLM output is never trusted: always schema-validated + rule-validated. |

---

## 6. Out of Scope (MVP)

- Logging into Facebook, Graph API app review, or any authenticated scraping.
- Crawling friends lists, posts behind login, or multiple pages per profile.
- A running scheduler that actually sends the 20:00 message / any message sending.
- Customer reply handling / multi-turn conversation simulation.
- Web UI / REST API.

---

## 7. Traceability (Requirement → Task)

| Requirement | Tasks |
|---|---|
| FR-001 | TASK-015 |
| FR-002 | TASK-004 |
| FR-003, FR-004 | TASK-005 |
| FR-005 | TASK-006 |
| FR-006, FR-009 | TASK-007 |
| FR-007 | TASK-009 |
| FR-008 | TASK-010 |
| FR-010–FR-012 | TASK-011, TASK-012, TASK-013 |
| FR-013 | TASK-003, TASK-015 |
| FR-014 | TASK-014 |
| FR-015 | TASK-008, TASK-012, TASK-014 |
| FR-016 | TASK-018 |
| NFR-001, NFR-008 | TASK-015 |
| NFR-002 | TASK-011, TASK-013, TASK-017 |
| NFR-003 | TASK-019, TASK-020 |
| NFR-004, NFR-006 | TASK-016, TASK-017 |
| NFR-005 | TASK-008, TASK-005, TASK-006 |
