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
| A-04 | Facebook may limit unauthenticated requests; profile JSON remains the reliable fallback. The URL-first CLI makes one best-effort unauthenticated browser visit to content Facebook exposes publicly and reports login/checkpoint/CAPTCHA walls without attempting to bypass them. |
| A-05 | The 20:00 trigger is represented in the output (`trigger_time: "20:00"`); the CLI does **not** run a long-lived scheduler/daemon. |
| A-06 | `dialogue_sequence_10` is an **array of strings** (messages). Grounding metadata is written to a separate `evidence.json` so the main schema stays exactly as specified. |
| A-07 | ~~Demographic fields only from self-declared data.~~ **Revised by CR-001:** self-declared data first; otherwise a labelled `INFERENCE` perceived from a public image (gender presentation, apparent age range) when confident; otherwise `"UNKNOWN"`. |
| A-08 | Test profiles committed to the repo are **synthetic personas**, not real people. |

### 2.3 Technical Risks

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R-01 | Facebook may block or limit unauthenticated access; automated collection is subject to Meta policies. | High | Very high | One best-effort public browser visit only; detect login/checkpoint/CAPTCHA → `PARTIAL_OR_PRIVATE`; never bypass, retry, or rotate IPs. Provide profile-file fallback and obtain required permissions. |
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
`--mode auto|llm|deterministic`, `--live|--no-live` (control public fetch, see FR-005).
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

### FR-005 — Live public fetch (best effort)
When no provided profile or matching local profile exists, the default URL flow MAY make one unauthenticated browser visit to the profile URL and read only content rendered publicly on that page. An optional single HTTP request may read public metadata.
It SHALL NOT log in, use cookies/credentials, solve CAPTCHAs, rotate IPs/user-agents, scroll repeatedly, click through access gates, or retry to evade blocks. `--no-live` disables all Facebook requests.
Login redirect / checkpoint / CAPTCHA page → `LOGIN_REQUIRED`; HTTP 404/410 or "content isn't available" → `NOT_FOUND`.
**Acceptance:** mocked browser pages for a public profile and login wall map to the correct access state; the browser source makes no login request and closes its fresh session.

### FR-006 — Normalization into a Fact Ledger
Raw data SHALL be normalized into a fact ledger: each item has `id`, `category`, `statement`, `source`, `epistemic_status ∈ {FACT, INFERENCE, UNKNOWN}`.
Missing fields SHALL be recorded as `UNKNOWN`, never filled.
**Acceptance:** a fixture with no bio yields a `bio` entry with `UNKNOWN`; no inferred entry has status `FACT`.

### FR-007 — Visual context extraction
If a public image (avatar/cover/public photo) is available, the system SHALL describe **only visibly observable, non-identity** elements ("image appears to show…").
It SHALL NOT infer ethnicity, religion, health, sexual orientation, political views, relationships or family roles.
No image / unreadable image → `visual_context: "NOT_AVAILABLE: <reason>"`.
**CR-001 (brief §4: "bị khóa kín (Private) hoặc không thu thập được hình ảnh"):** when no public image can be collected or read — no image, unreadable file/URL, image without provided description and no vision model, vision failure, or every observation rejected — the run SHALL end with `status: PARTIAL_OR_PRIVATE` and an `error_note` starting `NO_IMAGE:`.
**Acceptance:** "no image" fixture → `PARTIAL_OR_PRIVATE` / `NO_IMAGE:`; a vision output containing a forbidden attribute is rejected by the validator.

### FR-008 — Profile intelligence
The system SHALL produce `customer_name`, `visual_context`, `estimated_demographics.{gender, estimated_age_range, apparent_lifestyle}`.
- `gender`, `estimated_age_range` (**CR-001**): (1) self-declared data (gender field, pronouns, stated birth year); else (2) a perceived estimate from a public image analysed by the vision model, only when exactly one person is clearly visible — gender confidence ≥ 0.7, age range ≤ 15 years within 13–90 and confidence ≥ 0.6 — written as `INFERENCE: … (perceived from <kind> image, confidence x.xx) [F#]`; else `"UNKNOWN"`. Never from names; never ethnicity, religion, health, orientation, politics or family role.
- `apparent_lifestyle`: may be an INFERENCE, must be prefixed `INFERENCE:` and cite observed basis; else `"UNKNOWN"`.
**Acceptance:** without self-declared data and without a confident image estimate, both fields are `"UNKNOWN"`; an image estimate is labelled `INFERENCE:` with confidence and fact id; any lifestyle value is either `UNKNOWN` or starts with `INFERENCE:`.

### FR-009 — Sufficiency gate (SUCCESS vs PARTIAL_OR_PRIVATE)
`status = SUCCESS` only if: access state is `PUBLIC` or `PARTIAL`, `customer_name` is known, there are ≥ `MIN_GROUNDING_FACTS` (default 2) usable non-name facts, and (CR-001) a visual context could be extracted from a public image (FR-007).
Otherwise `status = PARTIAL_OR_PRIVATE` with an explanatory `error_note`. Data SHALL never be invented to reach SUCCESS.
**Acceptance:** fixture with name only → `PARTIAL_OR_PRIVATE`.

### FR-010 — Core empathy angle
The system SHALL produce one `core_empathy_angle` grounded in ≥ 1 cited fact.
**Acceptance:** evidence.json shows the cited fact IDs; all exist in the ledger.

### FR-011 — Rapport dialogue sequence (5–10, ZERO SALES)
The system SHALL generate 5–10 outbound messages (`dialogue_sequence_10`), target 10 when data allows, never fewer than 5 on SUCCESS.
Each message is either (a) grounded — cites ≥ 1 fact ID and makes no claim beyond the cited facts, or (b) neutral — courtesy/open question with no factual claim about the person.
Messages SHALL NOT contain: products, prices, discounts, promotions, purchase invitations, links, phone numbers, CTAs to buy/register/consult.
**CR-002 (original brief §2: "không nhắc đến tên thương hiệu Dr.Bee"):** messages, hook and angle SHALL NOT mention the brand **Dr.Bee** in any spelling (`Dr.Bee`, `Dr. Bee`, `DrBee`, `dr bee`, `Bác sĩ Bee`…), nor the product domain: hair/scalp problems and hair-care products (`rụng tóc`, `da đầu`, `dầu gội`, `serum`, `hair loss`…) — not even when the customer's own data mentions them. Generic beauty/pharma words (`tóc`, `mỹ phẩm`, `dược sĩ`, `điều trị`…) are allowed only when they appear verbatim in a cited fact (e.g. the customer works as a pharmacist).
`sales_mention_check = "ZERO_SALES_CONFIRMED"` only when the zero-sales validator passes; otherwise the output is regenerated or falls back — never emitted with a false confirmation.
**Acceptance:** count in [5, 10]; zero-sales validator passes; all cited IDs exist; any brand spelling or hard product-domain term is rejected even when cited (CR-002).

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
`auto` (default): use an LLM if a provider key is configured, else deterministic. **CR-004:** providers are Claude (`ANTHROPIC_API_KEY`) and Gemini (`GEMINI_API_KEY`); `LLM_PROVIDER=auto|anthropic|gemini` selects one (auto prefers Claude when both keys exist). `llm`: require LLM (fail to PARTIAL with note if unavailable). `deterministic`: template-based generation from facts, no network calls to LLM.
**Acceptance:** with no API key, `--mode auto` produces a valid SUCCESS output for a rich fixture.

### FR-017 — Forms of address (CR-001)
Messages SHALL address the customer as **"chị"** (female) or **"anh"** (male), with the agent as **"em"**, when gender is self-declared (gender field, or pronouns she/her / he/him) or perceived from an image with confidence ≥ 0.7 (FR-008). Otherwise the neutral **"bạn"** / **"mình"** is used. The basis is recorded in evidence.json.
**Acceptance:** self-declared female fixture → messages use "chị"/"em" and never "bạn"; unknown gender → "bạn"/"mình"; all drafts still pass the guardrails.

### FR-018 — Vietnamese output text (CR-003)
Every human-readable text in the output and evidence (`error_note`, `visual_context`, `estimated_demographics`, technical limitations) SHALL be Vietnamese, matching the brief's examples ("Nữ / Nam", "25 - 35 tuổi", "Trang cá nhân bị khóa riêng tư…"). Machine-readable status codes stay as fixed English prefixes (`INVALID_INPUT:`, `PRIVATE_PROFILE:`, `NOT_FOUND:`, `NO_IMAGE:`, `INSUFFICIENT_DATA:`, `UNREACHABLE:`, `INTERNAL_ERROR:`, `TECHNICAL LIMITATION:`, `NOT_AVAILABLE:`, `INFERENCE:`, `UNKNOWN`).
**Acceptance:** every SUCCESS / PARTIAL output of the fixtures reads in Vietnamese after its code prefix.

### FR-019 — Emotional quality (CR-003)
Messages SHALL read as a warm, sincere friend, following the brief: honour the customer, empathise with their efforts, compliment their positive spirit, and open with a warm greeting that mentions the profile picture when an image description exists. Grounded family topics are allowed when a cited fact is itself about family; a work-related evening wish ("sau giờ làm") is allowed when a work fact is cited. AI vision observations (INFERENCE) may ground a tentative mention of the profile picture; perceived demographic estimates never may.
**Acceptance:** template output contains an avatar-aware greeting and varied, empathetic phrasing; the brief's own hook examples pass the guardrails when supported by a cited fact and are still rejected without one.

### FR-020 — Real-profile test runs (CR-003)
The project SHALL provide tooling to run consented real profiles: a profile-data template generator and a batch run over a directory of profile files whose results stay in the git-ignored `runs/` folder unless the user chooses to publish them. No real data is collected by the agent itself.
**Acceptance:** `scripts/new_profile.py` writes a valid template; `scripts/run_test_profiles.py --profiles-dir DIR` runs every file and writes `runs/test_results_real.json`.

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
| C-005 | ZERO SALES in rapport messages and evening hook, including no mention of the Dr.Bee brand or its product domain (CR-002). |
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
| FR-007, FR-009 (CR-001 no image) | TASK-021 |
| FR-008 (CR-001 image estimate) | TASK-022 |
| FR-017 | TASK-023 |
| FR-011 (CR-002 brand / product domain) | TASK-024 |
| FR-018 | TASK-025 |
| FR-019 | TASK-026 |
| FR-020 | TASK-027 |
| FR-015 (CR-004 Gemini provider) | TASK-028 |
| NFR-001, NFR-008 | TASK-015 |
| NFR-002 | TASK-011, TASK-013, TASK-017 |
| NFR-003 | TASK-019, TASK-020 |
| NFR-004, NFR-006 | TASK-016, TASK-017 |
| NFR-005 | TASK-008, TASK-005, TASK-006 |

---

## 8. Change Log

| ID | Date | Source | Change |
|---|---|---|---|
| CR-001 | 2026-10-06 | Review against the original brief (`DE BAI TEST CHINH THUC … FACEBOOK PROFILER AGENT.md`), approved by the user (items 1, 2, 5) | FR-007/FR-009: no collectable image → `PARTIAL_OR_PRIVATE` (`NO_IMAGE:`). FR-008 / A-07: labelled perceived gender & age estimate from a public image. FR-017: "chị/anh – em" forms of address. |
| CR-002 | 2026-10-06 | Original brief §2 ("không nhắc đến tên thương hiệu Dr.Bee"), approved by the user | FR-011 / C-005: block the Dr.Bee brand (absolute) and its product domain (hard terms absolute, generic terms only when self-declared in a cited fact). |
| CR-003 | 2026-10-06 | User: "khắc phục những thiếu sót" (remaining gaps vs. the original brief) | FR-018 Vietnamese output text; FR-019 emotional quality (warmer templates, avatar greeting, grounded family / work themes, AI vision observations citable tentatively, LLM style guide); FR-020 tooling for consented real-profile runs. Live Claude verification and real data still require the user's API key and consented profiles. |
| CR-004 | 2026-10-06 | User: Anthropic API needs billing; use another provider such as Gemini | FR-015: add a Gemini adapter (`google-genai`, default `gemini-3.8-flash`, free tier available) behind the existing `LLMClient` protocol; provider selection via `LLM_PROVIDER`. Note: Gemini free-tier content may be used by Google to improve its products — fine for synthetic fixtures, not for real customer data without consent / a paid tier. |
