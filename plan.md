# Plan — Facebook Profiler Agent (TES-3808)

> Status: **APPROVED** 2026-10-06 (Phase 0) · kept in sync with the implementation (see task.md notes for changes)
> Task status tracking lives **only** in [task.md](task.md). This file describes decisions, order and strategy.

---

## 1. MVP Definition

The MVP is done when a reviewer can:

1. `pip install -r requirements.txt`
2. `python main.py --url "https://www.facebook.com/fixture.minh.anh"`
3. Get a schema-exact SUCCESS JSON on stdout and in `output.json` — **without an API key** (deterministic mode) —
   and a richer LLM-generated version when `ANTHROPIC_API_KEY` is set.
4. See honest `PARTIAL_OR_PRIVATE` results for private / dead / insufficient / unreachable profiles.
5. Read `test_results.json` covering ≥ 3 representative profiles, and `evidence.json` showing grounding.

MVP priority (from the brief): CLI → input → acquisition w/ honest fallback → intelligence → rapport →
evening hook → strict JSON → zero hallucination → error handling → 3 test cases → README → clean repo.

---

## 2. User / Business Flow

```text
CSKH operator has a customer's Facebook URL (+ optionally the profile data they legitimately exported/collected)
        │
        ▼
python main.py --url <url> [--profile-file data.json]
        │
        ├─ data inaccessible ─► PARTIAL_OR_PRIVATE + reason + TECHNICAL LIMITATION  ─► operator decides manually
        │
        ▼
Profile summary (facts vs inferences vs unknowns)
        │
        ▼
5–10 rapport messages (zero sales)  +  20:00 evening hook
        │
        ▼
Operator reviews evidence.json, then sends messages manually (system never sends anything)
```

---

## 3. Architecture Decisions (ADR summary)

| ID | Decision | Rationale | Alternatives rejected |
|---|---|---|---|
| AD-01 | Python 3.11+, stdlib `argparse`, Pydantic v2 | Brief uses `python main.py`; Pydantic gives strict schema validation. | Node.js (no advantage); Typer/Click (extra dep). |
| AD-02 | Resolve supplied files and local profiles first; otherwise make one best-effort, unauthenticated browser visit for publicly rendered content; optional metadata-only HTTP source | Supports the brief's URL-first path without credentials or access-control bypass; blocked pages remain honest partial results. | Logged-in sessions, persistent cookies, proxy rotation, CAPTCHA handling, repeated scrolling or retries. |
| AD-03 | Fact Ledger with IDs + mandatory citations from the LLM | Makes "zero hallucination" machine-checkable. | Trusting prompt instructions alone. |
| AD-04 | Two AI calls: vision (optional) + one structured engagement call | Coherent tone, fewer calls, per-section validation still possible. | One call per section (3–4 calls, more cost/latency). |
| AD-05 | Deterministic template generator always available | Runability without API key; guaranteed-safe fallback. | LLM-only (reviewer may have no key). |
| AD-06 | Demographics: self-declared first, then a labelled perceived estimate from an image (CR-001), else `UNKNOWN` | The original brief asks for estimated demographics; labelling keeps facts and inferences apart. | Unlabelled guesses; estimates from names. |
| AD-07 | Main output schema kept exact; provenance in separate `evidence.json` | Brief requires exact schema; reviewers still need traceability. | Extra keys in output.json. |
| AD-08 | `dialogue_sequence_10` = outbound agent messages only, array of strings | Customer replies unknown → inventing them is hallucination. | Two-sided simulated dialogue. |
| AD-09 | Invalid input reuses `PARTIAL_OR_PRIVATE` + `INVALID_INPUT:` note + exit code 2 | Brief defines only two statuses. | New `ERROR` status (see Decision D-5). |
| AD-10 | Claude Opus 5.5 (`claude-opus-5-5`) via official `anthropic` SDK, behind `LLMClient` adapter | Vision + structured outputs; provider isolated for swapability. | Direct SDK use across modules. |
| AD-11 | Tests fully offline: fake LLM + `httpx.MockTransport` | Deterministic CI, no keys needed. | Live calls in tests. |
| AD-12 | All logs → stderr; stdout = one JSON doc; UTF-8 forced | Strict JSON + Vietnamese on Windows. | — |

---

## 4. Implementation Order & Dependencies

```text
TASK-001 Bootstrap
   └─► TASK-002 Config
         └─► TASK-003 Domain & output models
               ├─► TASK-004 Input validation
               │     └─► TASK-005 Provided-data source (+ first fixtures)
               │           └─► TASK-006 Live public-meta source (opt-in)
               │                 └─► TASK-007 Fact ledger + sufficiency gate
               │                       └─► TASK-008 LLM adapter (Anthropic + Fake)
               │                             └─► TASK-009 Visual context
               │                                   └─► TASK-010 Profile intelligence (demographics/lifestyle)
               │                                         └─► TASK-011 Guardrail validators
               │                                               └─► TASK-012 Deterministic generator
               │                                                     └─► TASK-013 LLM generator + retry
               │                                                           └─► TASK-014 Pipeline + error handling + evidence
               │                                                                 └─► TASK-015 CLI + output writer
               │                                                                       └─► TASK-016 Full fixture set
               │                                                                             └─► TASK-017 Integration tests
               │                                                                                   └─► TASK-018 3-profile run → test_results.json
               │                                                                                         └─► TASK-019 README
               │                                                                                               └─► TASK-020 Final review & cleanup
```

The chain is intentionally linear (one active task rule). Guardrails (TASK-011) come **before** any generator
so every generator is built against the validators from the start.

---

## 5. Major Technical Decisions — details

### 5.1 Data acquisition chain
`ProvidedFileSource(--profile-file)` → `FixtureStoreSource(PROFILE_STORE_DIR, match canonical URL)` → `LivePublicMetaSource` (only if enabled).
First source that returns a result wins. If none: `NO_ACCESSIBLE_DATA` + TECHNICAL LIMITATION note explaining that
Facebook requires login for profile content and how to supply data via `--profile-file`.

### 5.2 Sufficiency gate
SUCCESS needs: access ∈ {PUBLIC, PARTIAL} ∧ name known ∧ ≥ `MIN_GROUNDING_FACTS` (2) usable non-name FACTs.
Rationale: with fewer than 2 real facts, 5 messages + a hook would be mostly filler or invention.

### 5.3 Message composition rule
Each message is `grounded` (cites facts, claims nothing beyond them) or `neutral` (greeting / open question, no claim about the person).
Target 10; minimum 5; at least ⌈n/2⌉ grounded when ≥ 3 facts exist. Deterministic generator reduces count rather than padding with claims.

### 5.4 Zero-sales validator
Bilingual lexicon (vi/en) for: buy/order/price/discount/promo/sale/product/service/consult/register/trial/voucher/ship/inbox-for-price,
plus structural detectors: currency (`đ`, `vnd`, `k`, `$`, `%`), URLs, phone numbers, hashtags of brands. Any hit → violation.
Limitation (documented): paraphrased soft-sells may evade lexicons; mitigated by prompt rules and review of evidence.

### 5.5 Presumption validator (evening hook)
Patterns asserting the customer's current state/activities without a cited fact (e.g. "chắc bạn vừa", "hôm nay bạn đã",
"bạn đang mệt", "sau giờ làm"). Hook must cite ≥1 fact and may only reference that fact.

---

## 6. Testing Strategy

| Layer | What | How |
|---|---|---|
| Unit | URL validation (valid/invalid/missing), source loading, access-state mapping, ledger building, gate, demographics rules, each validator, deterministic generator, output models | `pytest`, pure functions |
| Adapter | Live meta source: public meta, login wall, 404, timeout | `httpx.MockTransport` |
| AI | Valid structured output; invalid JSON/schema; unknown fact IDs; sales leakage; presumption; refusal/`max_tokens`; retry → fallback | `FakeLLMClient` scripted responses |
| Integration | CLI end-to-end via `subprocess`: stdout parses, equals output.json, schema valid, exit codes | fixtures: public-rich, partial, private, dead, no-image, name-only |
| Acceptance run | ≥ 3 representative profiles → `test_results.json` (+ optional real URLs supplied by user, outputs in git-ignored `runs/`) | `scripts/run_test_profiles.py` |
| Manual | One LLM-mode run with real API key (if available), recorded in test_results.json | — |

Coverage targets from the brief §24 are mapped one-to-one to test files in task.md.

---

## 7. Deployment / Runability Strategy

- `requirements.txt` with pinned minimum versions: `anthropic`, `pydantic>=2`, `httpx`, `python-dotenv`, `pytest`.
- `.env.example` documents every variable; app runs with **no** `.env`.
- Single command run; no services, no DB, no scheduler.
- README quick start verified in a fresh venv during TASK-020.

---

## 8. Decisions Requiring Approval

| ID | Decision | Recommendation |
|---|---|---|
| D-1 | Data access strategy | **Revised for URL-first brief:** provided files and matching local profiles take precedence; otherwise one unauthenticated public-browser visit is enabled by default and may be disabled with `--no-live`. No login or access-control bypass. |
| D-2 | Test data | 3+ **synthetic** fixture personas committed; real URLs only if you supply consenting profiles, outputs kept out of git. |
| D-3 | Demographics policy | **Revised by CR-001 (approved 2026-10-06):** self-declared data first; else a perceived estimate from a public image labelled `INFERENCE` with confidence; else `UNKNOWN`. |
| D-4 | Output extras | Exact schema in output.json; grounding/provenance in separate `evidence.json`; messages as array of strings. |
| D-5 | Invalid input status | Reuse `PARTIAL_OR_PRIVATE` + `INVALID_INPUT:` note + exit code 2 (vs. adding a new `ERROR` status). |
| D-6 | LLM provider & offline mode | Claude Opus 5.5 via adapter; deterministic template mode when no key (`--mode auto`). **CR-004:** Gemini (`gemini-3.8-flash`) added as a second adapter because the Anthropic API needs billing. |
| D-7 | Message language | Vietnamese generated messages; English docs. |
| D-8 | No collectable image (CR-001) | **Approved:** `PARTIAL_OR_PRIVATE` with `NO_IMAGE:` (brief §4), instead of SUCCESS with `NOT_AVAILABLE`. |
| D-9 | Forms of address (CR-001) | **Approved:** "chị"/"anh" – "em" when gender is self-declared or confidently perceived; "bạn" – "mình" otherwise. |

## 9. Change Request CR-001

Source: review of the original brief after Phase 1 (gaps reported to the user). Items approved and scheduled first:
1 (no image → PARTIAL), 2 (perceived demographic estimate), 5 (forms of address). Implementation order:
TASK-021 → TASK-022 → TASK-023 (addressing uses the gender result of TASK-022). Remaining gaps (brand blocking,
Vietnamese output text, real-profile test runs, emotional quality / live LLM) are pending further decisions.

## 10. Change Request CR-002

Approved after CR-001: block the Dr.Bee brand and its product domain in every generated text (original brief §2).
Implemented as TASK-024.

## 11. Change Request CR-003

User asked to fix the remaining gaps. Implemented now: TASK-025 (Vietnamese output text) → TASK-026 (emotional
quality) → TASK-027 (real-profile tooling). Still requiring the user: an `ANTHROPIC_API_KEY` to verify Claude live, and
consented real profile data for the brief's "3 real Facebook links" run.

## 12. Change Request CR-004

User request: use Gemini because the Anthropic API requires billing. Implemented as TASK-028 before TASK-026, so the
emotional-quality work can be verified against a live model. Live verification needs the user's `GEMINI_API_KEY`.
