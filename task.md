# task.md — SINGLE SOURCE OF TRUTH for implementation status

> Read this file **before every coding session**. Only one task may be `IN_PROGRESS` at a time.
> Allowed statuses: `TODO` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `SKIPPED`
> A task is `DONE` only with implementation + acceptance criteria met + relevant tests passing.

## Project Phase

- Phase 0 — Project Discovery: **COMPLETE** (2026-10-06) — approved by user (`APPROVED — START IMPLEMENTATION`, 2026-10-06); decisions D-1…D-7 accepted as recommended in plan.md §8
- Phase 1 — Implementation: **COMPLETE** (2026-10-06) — all 20 tasks + BUG-001 DONE; see TASK-020 for the final checklist

## Status Summary

| Task | Title | Status | Depends on |
|---|---|---|---|
| TASK-001 | Project bootstrap | DONE | — |
| TASK-002 | Configuration | DONE | 001 |
| TASK-003 | Domain & output models | DONE | 002 |
| TASK-004 | Input validation | DONE | 003 |
| TASK-005 | Provided-data source (+ first fixtures) | DONE | 004 |
| TASK-006 | Live public-meta source (opt-in) | DONE | 005 |
| TASK-007 | Fact ledger + sufficiency gate | DONE | 006 |
| TASK-008 | LLM adapter (Anthropic + Fake) | DONE | 007 |
| TASK-009 | Visual context extraction | DONE | 008 |
| TASK-010 | Profile intelligence | DONE | 009 |
| TASK-011 | Guardrail validators | DONE | 010 |
| TASK-012 | Deterministic generator | DONE | 011 |
| TASK-013 | LLM generator + retry/fallback | DONE | 012 |
| TASK-014 | Pipeline, error handling, evidence report | DONE | 013 |
| TASK-015 | CLI + output writer | DONE | 014 |
| TASK-016 | Full fixture set | DONE | 015 |
| TASK-017 | Integration tests | DONE | 016 |
| TASK-018 | Three-profile test run → test_results.json | DONE | 017 |
| TASK-019 | README | DONE | 018 |
| TASK-020 | Final review & cleanup | DONE | 019 |
| BUG-001 | Double punctuation after quoted fact text | DONE | (related TASK-012) |

Counts: TODO 0 · IN_PROGRESS 0 · BLOCKED 0 · DONE 21 · SKIPPED 0

---

## TASK-001 — Project bootstrap

Status: DONE
Priority: HIGH
Dependencies: None
Requirements: NFR-003, NFR-009, NFR-011

Goal:
Create the project skeleton so later tasks have a place to live and tests can run.

Scope:
- Create `app/` package (empty `__init__.py`), `tests/`, `fixtures/profiles/`, `scripts/`.
- `requirements.txt` (anthropic, pydantic>=2, httpx, python-dotenv, pytest).
- `.env.example` (all variables from architecture.md §7.2, no real values).
- `.gitignore`: add `runs/`, keep `.env` ignored.
- No `main.py` yet (created in TASK-015).
- `tests/test_smoke.py` asserting `import app` works.

Acceptance Criteria:
- [x] `pip install -r requirements.txt` succeeds in a fresh venv.
- [x] `pytest` runs and passes (smoke test).
- [x] `.env.example` lists every config variable; `.env` and `runs/` are git-ignored.

Expected Files:
- app/__init__.py, tests/__init__.py, tests/test_smoke.py, requirements.txt, .env.example, .gitignore (edit)

Test:
- `python -m pytest -q`

Completed:
- Package skeleton: app/, tests/, fixtures/profiles/, scripts/ (empty dirs kept with .gitkeep).
- requirements.txt (anthropic>=1.0, pydantic>=2.7, httpx>=0.27, python-dotenv>=1.0, pytest>=8.0).
- .env.example with all 9 variables from architecture.md §7.2 (API key left empty).
- .gitignore: added `runs/`; `.env` and `.venv` were already ignored.
- Smoke test.

Files Changed:
- app/__init__.py (new), tests/__init__.py (new), tests/test_smoke.py (new)
- fixtures/profiles/.gitkeep (new), scripts/.gitkeep (new)
- requirements.txt (new), .env.example (new), .gitignore (edit: +runs/)

Tests:
- Fresh venv (`python -m venv .venv`, Python 3.12.10): `pip install -r requirements.txt` → exit 0
  (resolved: anthropic 1.11.0, pydantic 2.13.5, httpx 0.28.1, python-dotenv 1.2.4, pytest 9.1.1).
- `python -m pytest -q` → 1 passed.
- `git check-ignore`: `.env` ignored, `runs/x.json` ignored, `.env.example` NOT ignored.

Result:
PASS

Notes:
- anthropic 1.x pulls in `httpx2` transitively; the project itself uses `httpx` (declared explicitly) for the live-meta source.
- Nothing committed yet (no commit requested).

---

## TASK-002 — Configuration

Status: DONE
Priority: HIGH
Dependencies: TASK-001
Requirements: FR-015, NFR-005, NFR-009

Goal:
Load settings from env / optional `.env` with safe defaults; no provider SDK import.

Scope:
- `app/config.py`: `Settings` (Pydantic) with fields from architecture.md §7.2; `load_settings(overrides)`.
- Validation: `DEFAULT_MESSAGE_COUNT` in 5..10, `MIN_GROUNDING_FACTS` ≥ 1, booleans parsed.
- `has_llm_credentials` property (key present, never logged).

Acceptance Criteria:
- [x] Defaults load with an empty environment.
- [x] Env vars override defaults; invalid values raise a clear error.
- [x] API key never appears in `repr(settings)`.

Expected Files:
- app/config.py, tests/test_config.py

Test:
- `pytest tests/test_config.py`

Completed:
- `Settings` (frozen Pydantic model, `extra="forbid"`) with the 9 fields of architecture.md §7.2 and range checks
  (message count 5..10, min facts ≥ 1, timeout 0..600 s, retries 0..5, 2-letter language code).
- `load_settings(overrides, env=, dotenv_path=)`: precedence overrides > environment > `.env` > defaults;
  blank values treated as unset; `.env` read with `dotenv_values` (does not mutate `os.environ`).
- `ConfigError` names the offending env variable.
- API key stored as `SecretStr`; `has_llm_credentials` property.
- Relative `PROFILE_STORE_DIR` anchored at project root (works from any cwd).

Files Changed:
- app/config.py (new), tests/test_config.py (new)

Tests:
- `python -m pytest -q` → 18 passed (17 config tests + smoke).
- Manual: `DEFAULT_MESSAGE_COUNT=4` → `ConfigError: Invalid configuration: DEFAULT_MESSAGE_COUNT: Input should be greater than or equal to 5`.
- Manual: `repr(settings)` shows `anthropic_api_key=SecretStr('**********')`.

Result:
PASS

Notes:
- Bug found and fixed during the task: field validator did not run on the default `profile_store_dir`; fixed with `validate_default=True`.
- `has_llm_credentials` only checks `ANTHROPIC_API_KEY` (as specified); other SDK auth sources (auth token/profiles) are not considered for `--mode auto`.

---

## TASK-003 — Domain & output models

Status: DONE
Priority: HIGH
Dependencies: TASK-002
Requirements: FR-006, FR-013, FR-014, C-006

Goal:
Define all typed data structures, including the exact output schema from the brief.

Scope:
- `app/models.py`: AccessState, EpistemicStatus, RawProfile (fixture format, architecture.md §4.1), Fact, FactLedger, AcquisitionResult.
- `app/schema.py`: SuccessOutput, PartialOutput (`extra="forbid"`, literal status values, 5..10 messages, `trigger_time == "20:00"`, `sales_mention_check == "ZERO_SALES_CONFIRMED"`), EvidenceReport.

Acceptance Criteria:
- [x] A SuccessOutput built from the brief's example serializes to exactly the brief's key set.
- [x] Extra keys, wrong status, <5 or >10 messages, wrong trigger time are rejected.
- [x] PartialOutput has exactly `status`, `facebook_url`, `error_note`.

Expected Files:
- app/models.py, app/schema.py, tests/test_schema.py

Test:
- `pytest tests/test_schema.py`

Completed:
- app/models.py: `AccessState` (8 states) + `READABLE_STATES`, `EpistemicStatus`, provided-data models
  (`RawProfile`, `AccessInfo`, `PublicInfo`, `PublicPost`, `ProfileImage`; blank strings → None, unknown keys rejected),
  `AcquisitionResult`, `Fact` (id `F<n>`, category literal, confidence 0..1, UNKNOWN not allowed as an entry),
  `FactLedger` (unique ids; `get`, `ids`, `name_fact`, `usable_facts`).
- app/schema.py: `SuccessOutput` / `PartialOutput` (all levels `extra="forbid"`, literals for status /
  `trigger_time="20:00"` / `ZERO_SALES_CONFIRMED`, 5..10 non-empty messages, non-empty strings),
  `parse_output` (discriminated on `status`), `to_json_dict`, and `EvidenceReport` (+ `Grounding`,
  `MessageGrounding`, `ValidationSummary`).

Files Changed:
- app/models.py (new), app/schema.py (new), tests/test_schema.py (new)
- architecture.md §4.1/§4.2/§4.4 (synced with implementation, see Notes)

Tests:
- `python -m pytest -q` → 45 passed (27 new in tests/test_schema.py).
- Covered: exact brief key set + key order; 5 and 10 messages accepted; 0/4/11 rejected; wrong status,
  trigger time (`21:00`, `8pm`), sales check literal, blank name/message rejected; extra keys rejected at every
  nesting level; missing key rejected; PartialOutput exactly 3 keys; discriminated parsing.

Result:
PASS

Notes:
- Small additions vs. the Phase 0 data model (documented in architecture.md): `public_info.interests`,
  `public_info.gender` (self-declared, as displayed), fact category `gender`, evidence fields
  `output_status`, `synthetic_data`, `grounding.apparent_lifestyle`. No change to the output.json schema.
- `PartialOutput.facebook_url` may be empty (missing `--url` case); `SuccessOutput.facebook_url` must be non-empty.
- Fixed during task: field named `date` shadowed the `date` type in `PublicPost` → imported as `Date`.

---

## TASK-004 — Input validation

Status: DONE
Priority: HIGH
Dependencies: TASK-003
Requirements: FR-002

Goal:
Validate and canonicalize Facebook profile URLs.

Scope:
- `app/input.py`: `validate_profile_url(raw) -> CanonicalUrl | InputError`.
- Accept `www.`, bare, `m.`, `mbasic.` hosts; `/<username>` and `/profile.php?id=<digits>`; strip tracking params, trailing slash, fragments.
- Reject: empty, non-http(s), non-Facebook hosts (incl. look-alikes such as `facebook.com.evil.io`), reserved paths (`groups`, `events`, `pages`, `watch`, `marketplace`, `login`, `share`, …), `profile.php` without numeric id.

Acceptance Criteria:
- [x] ≥ 8 valid URL variants canonicalize correctly.
- [x] ≥ 8 invalid inputs (incl. missing/empty, look-alike host) rejected with a reason.

Expected Files:
- app/input.py, tests/test_input.py

Test:
- `pytest tests/test_input.py`

Completed:
- `validate_profile_url(raw) -> CanonicalUrl` (url, kind `username|profile_id`, identifier, original);
  raises `InputError` with `.reason` and `.error_note` (`INVALID_INPUT: ...`).
- Hosts: facebook.com, www., m., mbasic., web. (exact match, case-insensitive). Scheme-less `facebook.com/...` accepted.
- Canonical `https://www.facebook.com/<username lowercased>` or `.../profile.php?id=<digits>`;
  `/people/<name>/<id>` mapped to the profile.php form; query/fragment/trailing slash and profile sub-pages
  (about, photos, friends, posts, videos, reels, followers) stripped.
- Rejects: missing/blank, non-URL text, non-http(s), look-alike hosts, embedded credentials (`facebook.com@evil.io`),
  explicit ports, reserved feature paths (groups, events, watch, marketplace, login, share, …),
  profile.php without numeric id, invalid usernames, deep non-profile paths.

Files Changed:
- app/input.py (new), tests/test_input.py (new)

Tests:
- `python -m pytest -q` → 82 passed (37 new: 15 valid variants, 22 invalid inputs).

Result:
PASS

Notes:
- Usernames accept `_` because the brief's own example is `example_user` (real Facebook usernames use a-z, 0-9, `.`).
- Exit code 2 / JSON emission for invalid input is wired in TASK-014/015 using `InputError.error_note`.

---

## TASK-005 — Provided-data source (+ first fixtures)

Status: DONE
Priority: HIGH
Dependencies: TASK-004
Requirements: FR-003, FR-004, NFR-005, C-009

Goal:
Load legitimately provided profile data from `--profile-file` or the fixture store.

Scope:
- `app/sources/base.py`: `ProfileSource` protocol, chain helper (first non-None wins).
- `app/sources/provided.py`: `ProvidedFileSource`, `FixtureStoreSource` (match by canonical URL; respect `access.state` in file).
- Malformed JSON / schema errors → clear error, not crash.
- Fixtures: `fixture.minh.anh` (public, rich) and `fixture.private.user` (PRIVATE). All marked `"synthetic": true`.

Acceptance Criteria:
- [x] Matching fixture loads as RawProfile with access PUBLIC.
- [x] Private fixture returns access PRIVATE with no profile fields used.
- [x] Unknown URL returns None (so chain can continue / report NO_ACCESSIBLE_DATA).
- [x] Malformed file produces a handled error.

Expected Files:
- app/sources/__init__.py, app/sources/base.py, app/sources/provided.py, fixtures/profiles/minh_anh.json, fixtures/profiles/private_user.json, tests/test_sources_provided.py

Test:
- `pytest tests/test_sources_provided.py`

Completed:
- app/sources/base.py: `ProfileSource` protocol, `SourceError`, `result_from_raw` (declared access state honoured;
  `raw` withheld unless PUBLIC/PARTIAL; synthetic + access notes → limitations), `acquire_from_chain`
  (first non-None wins; none → `NO_ACCESSIBLE_DATA` with a `TECHNICAL LIMITATION:` note).
- app/sources/provided.py: `load_raw_profile` (UTF-8/BOM, JSON + schema errors → `SourceError` with location),
  `ProvidedFileSource` (rejects a file whose facebook_url ≠ --url), `FixtureStoreSource` (lazy index by canonical
  URL; malformed/duplicate files skipped and listed in `load_errors`, missing dir handled).
- Fixtures: fixtures/profiles/minh_anh.json (PUBLIC, rich, synthetic), fixtures/profiles/private_user.json (PRIVATE, synthetic).

Files Changed:
- app/sources/__init__.py, app/sources/base.py, app/sources/provided.py (new)
- fixtures/profiles/minh_anh.json, fixtures/profiles/private_user.json (new); fixtures/profiles/.gitkeep (removed)
- app/models.py (edit: `AcquisitionResult.synthetic`), architecture.md §4.2 (synced)
- tests/test_sources_provided.py (new)

Tests:
- `python -m pytest -q` → 96 passed (14 new).
- Covered: rich fixture → PUBLIC RawProfile; non-canonical input URL still matches; private fixture → PRIVATE with
  raw=None; unknown URL → None → chain NO_ACCESSIBLE_DATA; chain order; invalid JSON / schema / unknown key /
  bad facebook_url / missing file / mismatched URL → SourceError; store skips broken + duplicate files;
  missing store dir; all repo fixtures load and are `synthetic: true`.

Result:
PASS

Notes:
- Added `AcquisitionResult.synthetic` so the synthetic flag survives when `raw` is withheld (private/dead cases).
- Pipeline (TASK-014) must map `SourceError` from `--profile-file` to `INVALID_INPUT:` (exit 2).
- Fixture personas, organisations ("Studio Lá Xanh", "Học viện Thiết kế Sông Hồng") are fictional.

---

## TASK-006 — Live public-meta source (opt-in)

Status: DONE
Priority: MEDIUM
Dependencies: TASK-005
Requirements: FR-005, C-001, C-002, C-004

Goal:
Best-effort, compliant single-request read of public meta tags; honest failure states.

Scope:
- `app/sources/live_meta.py` using `httpx` (injectable transport), honest UA, no cookies/auth, timeout, no retry on 4xx.
- Parse `og:title`, `og:description`, `og:image` with stdlib `html.parser`.
- Detect login wall (`/login`, `checkpoint`, login form markers), CAPTCHA markers → LOGIN_REQUIRED; 404/410/"content isn't available" → NOT_FOUND; network errors → UNREACHABLE.
- Only active when `--live` / `LIVE_FETCH_ENABLED=true`.

Acceptance Criteria:
- [x] Mocked public page → PUBLIC/PARTIAL RawProfile with name/description/image URL and source `live_meta`.
- [x] Mocked login redirect and login HTML → LOGIN_REQUIRED + TECHNICAL LIMITATION note.
- [x] Mocked 404 → NOT_FOUND; mocked timeout → UNREACHABLE.
- [x] Disabled by default (no request made).

Expected Files:
- app/sources/live_meta.py, tests/test_sources_live_meta.py

Test:
- `pytest tests/test_sources_live_meta.py`

Completed:
- `LivePublicMetaSource(enabled, timeout_seconds, transport)`: returns None when disabled (no request).
- One GET, honest UA `FacebookProfilerAgent/0.1 (+TES-3808 test)`, no cookies/auth, `follow_redirects=False`,
  no retries, body capped at 2 MB.
- Classification order: 404/410 → NOT_FOUND; 3xx to login/checkpoint/captcha/recover → LOGIN_REQUIRED;
  other 3xx → UNREACHABLE (not followed); other non-200 (403/429/5xx) → UNREACHABLE (not retried);
  "content isn't available" body → NOT_FOUND; meaningful og:title → PUBLIC (with description) / PARTIAL (name only);
  login-form/captcha markers → LOGIN_REQUIRED; nothing → NO_ACCESSIBLE_DATA; timeout/network error → UNREACHABLE.
- og:title " | Facebook" suffix stripped; generic titles ("Log into Facebook", …) ignored; Facebook's logged-out
  boilerplate og:description ("… is on Facebook. Join Facebook to connect …") dropped, never used as bio.
- Every result carries a scope note; failures carry `TECHNICAL LIMITATION:` / `NOT_FOUND:` / `UNREACHABLE:` notes.

Files Changed:
- app/sources/live_meta.py (new), tests/test_sources_live_meta.py (new)

Tests:
- `python -m pytest -q` → 114 passed (18 new, all via `httpx.MockTransport`; no real network).
- Covered: public page; name-only/boilerplate → PARTIAL; login redirect; checkpoint redirect; login HTML;
  other redirect not followed; 404/410; "content isn't available"; timeout; connection error; 403/429/500 without
  retry; page without meta; request headers (single GET, honest UA, no cookie/authorization); disabled → zero requests.

Result:
PASS

Notes:
- Decision D-1 approved (opt-in), so the task was implemented rather than skipped.
- Not verified against the real facebook.com in this task (acceptance is mock-based); a real `--live` attempt is
  planned in TASK-018 to document the actual behaviour.
- `--live` / `LIVE_FETCH_ENABLED` wiring happens in TASK-014/015.

---

## TASK-007 — Fact ledger + sufficiency gate

Status: DONE
Priority: HIGH
Dependencies: TASK-006
Requirements: FR-006, FR-009, C-003

Goal:
Normalize RawProfile into an ID'd fact ledger and decide whether SUCCESS is allowed.

Scope:
- `app/ledger.py`: `build_ledger(raw) -> FactLedger` (IDs F1..Fn, categories, sources, UNKNOWN fields list); `alt_text` → visual fact candidate.
- `evaluate_sufficiency(access_state, ledger, settings) -> GateResult(ok, reason_code, note)`.

Acceptance Criteria:
- [x] Rich fixture → ≥ 4 FACT entries with correct sources.
- [x] Missing bio → `bio` in unknown_fields, no fabricated bio fact.
- [x] Name-only profile → gate fails with `INSUFFICIENT_DATA`.
- [x] PRIVATE / NOT_FOUND / LOGIN_REQUIRED → gate fails with matching code.

Expected Files:
- app/ledger.py, tests/test_ledger.py

Test:
- `pytest tests/test_ledger.py`

Completed:
- `build_ledger(raw | None) -> FactLedger`: verbatim statements, sequential ids F1..Fn, source
  `<collection_method>:<field path>` (posts carry `@date`), case-insensitive de-duplication; missing fields listed in
  `unknown_fields` (12 tracked fields); image `alt_text` → `visual_observation` fact; `public_info.links` deliberately
  excluded (URLs must never reach messages); `None` → empty ledger, all fields unknown.
- `evaluate_sufficiency(access_state, ledger, settings) -> GateResult(ok, reason_code, note)`: non-readable states map
  to INVALID_INPUT / NO_ACCESSIBLE_DATA / LOGIN_REQUIRED / PRIVATE_PROFILE / NOT_FOUND / UNREACHABLE with the
  error-matrix prefixes (architecture.md §6); readable states require a name and ≥ `MIN_GROUNDING_FACTS` usable facts,
  else INSUFFICIENT_DATA.
- `FactLedger.usable_facts()` now also excludes pronouns / gender / birth_year (demographics only feed
  `estimated_demographics`, never message topics).

Files Changed:
- app/ledger.py (new), tests/test_ledger.py (new), app/models.py (edit: `NON_GROUNDING_CATEGORIES`, `usable_facts`)

Tests:
- `python -m pytest -q` → 135 passed (21 new).
- Manual: rich fixture → 12 facts (F1 name … F12 visual_observation), unknown = hometown, pronouns, gender,
  birth_year; gate ok.

Result:
PASS

Notes:
- Gate notes are canonical texts; the pipeline (TASK-014) may append source-specific limitation details.

---

## TASK-008 — LLM adapter (Anthropic + Fake)

Status: DONE
Priority: HIGH
Dependencies: TASK-007
Requirements: FR-015, NFR-005, NFR-006, C-010

Goal:
Provider-isolated LLM interface with a real Claude adapter and a scripted fake for tests.

Scope:
- `app/llm/base.py`: `LLMClient` protocol, `LLMError`, `VisionResult`.
- `app/llm/anthropic_client.py`: official `anthropic` SDK, model from settings (`claude-opus-5-5` default), structured output parsing into Pydantic models, image input (base64), timeout, `stop_reason` checks (`refusal`, `max_tokens`) → LLMError.
- `app/llm/fake.py`: returns queued responses / raises queued errors.
- Factory `get_llm_client(settings, mode)` → None in deterministic mode / no key in auto mode.

Acceptance Criteria:
- [x] Only `anthropic_client.py` imports `anthropic`.
- [x] Fake client drives success, invalid-schema and error paths in tests.
- [x] Factory returns None without key in `auto`; raises configured error in `llm` mode without key.
- [ ] (Manual, if key available) one real structured call succeeds — otherwise noted as not verified.
  → NOT VERIFIED: no `ANTHROPIC_API_KEY` in this environment. Criterion is conditional; gap recorded and re-checked in TASK-018.

Expected Files:
- app/llm/__init__.py, app/llm/base.py, app/llm/anthropic_client.py, app/llm/fake.py, tests/test_llm_adapter.py

Test:
- `pytest tests/test_llm_adapter.py`

Completed:
- app/llm/base.py: `LLMClient` protocol (`generate_structured`, `describe_image`), `LLMError(kind, detail)`
  (no_credentials, refusal, max_tokens, invalid_output, timeout, rate_limited, auth, api_error, unsupported_input),
  `VisionResult` / `VisionObservation` (≤ 5 observations, confidence 0..1).
- app/llm/anthropic_client.py: `client.beta.messages.create` with `output_config.format` = JSON schema from
  `anthropic.transform_schema(TypeAdapter(model).json_schema())`; checks `stop_reason` (refusal / max_tokens) BEFORE
  validating text with Pydantic; base64 image blocks (jpeg/png/gif/webp); SDK exceptions mapped most-specific-first;
  `fallbacks: "default"` + beta `server-side-fallback-2026-07-01` + `effort: medium` only for models that accept them
  (opus-5-5, opus-5, fable-5-1, sonnet-5-5); no `thinking`/sampling params (Opus 5.5 rejects disabling thinking);
  timeout from settings, SDK `max_retries=1`, `max_tokens=16000`.
- app/llm/fake.py: queue-driven fake (dict / JSON string / model / exception), records calls; schema mismatch → `invalid_output`.
- app/llm/__init__.py: `get_llm_client(settings, mode)` — deterministic → None; auto without key → None;
  llm without key → `LLMError(no_credentials)`; adapter imported lazily.

Files Changed:
- app/llm/__init__.py, app/llm/base.py, app/llm/anthropic_client.py, app/llm/fake.py (new)
- tests/test_llm_adapter.py (new)

Tests:
- `python -m pytest -q` → 162 passed (27 new).
- Covered: only anthropic_client.py imports the SDK (source scan); factory 4 cases; fake success / invalid schema /
  queued error / exhaustion / vision; adapter request shape (model, system, schema with additionalProperties=false,
  fallbacks/betas/effort), non-fallback model omits them, image block, unsupported image type (no API call),
  refusal / max_tokens / non-JSON / schema mismatch / empty text, 6 SDK exception mappings.

Result:
PASS (automated). Real API call NOT VERIFIED (no key available).

Notes:
- SDK usage verified against the claude-api skill docs and the installed SDK source (anthropic 1.11.0):
  `beta.messages.create` accepts `fallbacks` (`Literal["default"]` allowed), `betas`, `output_config`.
  `messages.parse` was not used because it validates JSON inside the call, hiding refusal/max_tokens stop reasons.
- `fallbacks: "default"` is enabled by default per the skill guidance; remove `FALLBACK_MODELS` entries to opt out.
- `--mode auto` treats only `ANTHROPIC_API_KEY` as credentials (see TASK-002 note).

---

## TASK-009 — Visual context extraction

Status: DONE
Priority: MEDIUM
Dependencies: TASK-008
Requirements: FR-007, C-007

Goal:
Turn an available public image into validated, observation-only visual facts.

Scope:
- `app/vision.py`: choose image (provided local path > provided URL > og:image); use `alt_text` without LLM when present; otherwise `LLMClient.describe_image`.
- Validate observations: forbidden sensitive attributes, confidence threshold, max 5, "appears to show" phrasing.
- Produce `visual_context` string and visual facts; `NOT_AVAILABLE: <reason>` on any failure/no image.

Acceptance Criteria:
- [x] No image → `NOT_AVAILABLE: no public image provided`.
- [x] Fake vision output with "mother of two" / ethnicity term → observation rejected.
- [x] Valid fake observations → visual facts in ledger with `source=vision:avatar`.

Expected Files:
- app/vision.py, tests/test_vision.py, fixtures/images/ (small synthetic image, if needed)

Test:
- `pytest tests/test_vision.py`

Completed:
- app/vision.py `extract_visual_context(raw, ledger, llm, base_dir=, transport=) -> VisualContextResult(visual_context, ledger, fact_ids, notes)`:
  - No image → `NOT_AVAILABLE: no public image provided`.
  - Provided `alt_text` → used without any AI call (`PROVIDED IMAGE DESCRIPTION: …`, ledger FACT); screened for
    sensitive attributes, offending entries removed from the ledger.
  - Otherwise one image (local path first, then provided/og URL) → `LLMClient.describe_image` with observation-only
    instructions; each observation must have confidence ≥ 0.6, no sensitive term, "appears to show"/"có vẻ" phrasing;
    accepted ones appended as `visual_observation` entries, `source=vision:<kind>`, status INFERENCE with confidence;
    `visual_context = AI VISUAL OBSERVATION (<kind> image, model-generated, unverified): …`.
  - Deterministic mode / LLM error / unusable image / all rejected / unreadable or unsupported file / URL non-200 or
    non-image → `NOT_AVAILABLE: <reason>`. Image URL fetch: one GET, honest UA, no cookies, no redirects, 5 MB cap.
- app/lexicons.py: `SENSITIVE_TERMS` (vi + en: ethnicity, religion, health/body, orientation, politics,
  family/relationship, appearance-based gender/age) + `find_sensitive()` with Unicode word boundaries (reused in TASK-011).
- app/ledger.py: `append_fact` (next free id, existing ids unchanged), `without_facts`.

Files Changed:
- app/vision.py, app/lexicons.py, tests/test_vision.py (new)
- app/ledger.py (edit: append_fact, without_facts), tests/test_ledger.py (edit: +1 test)
- architecture.md §5.1 (synced: INFERENCE status for model observations)

Tests:
- `python -m pytest -q` → 184 passed (22 new).
- Covered: no image; fixture alt text used with zero LLM calls; sensitive alt text removed; valid observations →
  INFERENCE entries with `source=vision:avatar` and confidences, excluded from usable_facts; 6 sensitive cases
  ("mother of two", ethnicity, "woman in her 30s", pregnant, hijab, Vietnamese "phụ nữ") rejected while a clean one is
  kept; low confidence & unhedged rejected; unusable image; >5 observations; LLM error; deterministic mode;
  missing/unsupported local file; URL download (1 request, no cookie); URL 403 / non-image; lexicon word boundaries.

Result:
PASS

Notes:
- Design choice (stricter than the Phase 0 text): AI vision output is INFERENCE, not FACT, because it is
  model-generated and unverifiable; it informs `visual_context` only. Provided alt text remains FACT.
- No fixtures/images file was needed (tests write a tiny PNG to a temp dir; LLM is faked).
- Real vision call not verified (no API key) — same gap as TASK-008.

---

## TASK-010 — Profile intelligence

Status: DONE
Priority: HIGH
Dependencies: TASK-009
Requirements: FR-008, C-003, C-007

Goal:
Fill `estimated_demographics` honestly.

Scope:
- `app/intel.py`: gender from explicit pronouns/declared field only; age range from explicit birth year only (bucketed, labeled `derived from stated birth year`); otherwise `UNKNOWN`.
- `apparent_lifestyle`: deterministic `INFERENCE: ... (based on F#, F#)` from interest/work/post facts, or `UNKNOWN`; may be replaced by validated LLM value in TASK-013.

Acceptance Criteria:
- [x] Fixture without explicit gender/age → both `UNKNOWN`.
- [x] Fixture with pronouns + birth year → values derived and labeled.
- [x] Lifestyle is `UNKNOWN` or starts with `INFERENCE:` and cites existing fact IDs.

Expected Files:
- app/intel.py, tests/test_intel.py

Test:
- `pytest tests/test_intel.py`

Completed:
- app/intel.py `build_intelligence(ledger, reference_year) -> Intelligence` (customer_name, gender,
  estimated_age_range, apparent_lifestyle + cited fact ids for each):
  - gender: self-declared gender field (vi/en values normalised to Female/Male, others verbatim) →
    `"<label> (self-declared gender field [F#])"`; else pronouns reported verbatim
    `"Self-declared pronouns: she/her [F#] (gender not stated)"`; else `UNKNOWN`.
  - age: stated birth year only → `"30–31 (derived from stated birth year 1995 [F#], as of 2026)"`
    (two-year range because the birthday is unknown); implausible ages (<13 / >110) → `UNKNOWN`.
  - lifestyle: `"INFERENCE: day-to-day life appears to involve stated interests: …, stated work: … (based on F…)"`
    from ≤3 interests + ≤1 work fact, else bio, else `UNKNOWN`.
  - Only FACT entries are used: names and model-generated visual observations never feed demographics.

Files Changed:
- app/intel.py (new), tests/test_intel.py (new)

Tests:
- `python -m pytest -q` → 196 passed (12 new).
- Manual (rich fixture): gender UNKNOWN, age UNKNOWN, lifestyle `INFERENCE: … (based on F5, F6, F7, F3)`.

Result:
PASS

Notes:
- Decision D-3 applied. Pronouns are deliberately not mapped to a gender.
- Age is a 2-value range (e.g. 30–31) instead of a wide bucket: more precise and still purely arithmetic.
- TASK-013 may replace `apparent_lifestyle` with a validated LLM value citing fact ids.

---

## TASK-011 — Guardrail validators

Status: DONE
Priority: HIGH
Dependencies: TASK-010
Requirements: FR-010, FR-011, FR-012, NFR-002, C-005, C-007

Goal:
Deterministic validators that every generated draft must pass.

Scope:
- `app/guardrails.py`: `EngagementDraft` model (angle, messages with kind/fact_ids, hook, lifestyle).
- Validators: fact-ID existence & citation rules; count 5..10; zero-sales lexicon (vi/en) + currency/%/URL/phone detectors; presumption patterns for hook; sensitive-attribute lexicon; entity/number overlap heuristic for grounded items; neutral messages must not assert facts about the person.
- Returns list of `Violation(code, location, detail)`.

Acceptance Criteria:
- [x] Clean draft → no violations.
- [x] Each violation type has ≥ 1 failing test (unknown ID, sales word vi, sales word en, price "199k", URL, phone, presumption, sensitive term, count 4 and 11).
- [x] No false positive on the rich fixture's legitimate vocabulary (e.g. "cà phê", "chạy bộ").

Expected Files:
- app/guardrails.py, tests/test_guardrails.py

Test:
- `pytest tests/test_guardrails.py`

Completed:
- app/guardrails.py: draft models `EngagementDraft` / `DraftMessage` / `CitedText` (strict; reused as the LLM
  output schema in TASK-013), `Violation(code, location, detail)`, `check_text`, `check_entities`, `validate_draft`.
- Violation codes: UNKNOWN_FACT_ID, NON_FACT_CITATION (INFERENCE e.g. AI vision), DEMOGRAPHIC_CITATION,
  MISSING_CITATION (grounded message / angle / hook / lifestyle without a usable fact), NEUTRAL_CITES_FACTS,
  NEUTRAL_CLAIM, MESSAGE_COUNT, TOO_FEW_GROUNDED (≥ ⌈n/2⌉ when ≥ 3 usable facts), DUPLICATE_MESSAGE, TOO_LONG,
  SALES_TERM, PRICE, URL, PHONE, EMAIL, HASHTAG, PRESUMPTION, SENSITIVE_TERM, UNGROUNDED_NUMBER,
  UNGROUNDED_ENTITY, LIFESTYLE_LABEL.
- Sales/sensitive terms are tolerated only when they appear verbatim in a cited fact (e.g. a bio "thiết kế sản
  phẩm"); prices, URLs, phones, e-mails, hashtags never. Presumption check applies to every text, not only the hook.
- app/lexicons.py: + `SALES_TERMS` (vi/en), `PRICE_PATTERN` (k/đ/₫/vnd/triệu/tr/%/$…; "10km" not a price),
  `URL_PATTERN`, `PHONE_PATTERN` (VN formats), `EMAIL_PATTERN`, `HASHTAG_PATTERN`, `PRESUMPTION_PATTERNS` (vi/en).

Files Changed:
- app/guardrails.py (new), tests/test_guardrails.py (new), app/lexicons.py (edit)
- architecture.md §5.2 validation row (synced)

Tests:
- `python -m pytest -q` → 235 passed (39 new).
- Covered: clean 10-message draft → 0 violations; intel lifestyle passes; no false positives on any rich-fixture
  fact ("cà phê", "chạy bộ", "sourdough", "Hồ Tây"…); unknown id; missing citation (message, hook, angle);
  INFERENCE citation; demographic citation; neutral citing facts; neutral claim; ungrounded number + entity
  ("21km ở Đà Lạt"); too few grounded; duplicate; count 4 and 11; lifestyle label; 14 sales/contact cases
  (vi + en words, "199k", "1.500.000đ", "20%", 2 URLs, 2 phones, e-mail, hashtag); 4 presumption hooks;
  3 sensitive texts; self-declared exceptions; too long.
- Manual: printed violations are specific (e.g. `[PRICE] messages[9]: '199k' is not allowed …`).

Result:
PASS

Notes:
- Known limitation (plan.md §5.4): lexicon/heuristic checks can miss paraphrased soft-selling or claims; the
  entity heuristic only covers numbers and capitalised words. Documented for the README (TASK-019).

---

## TASK-012 — Deterministic generator

Status: DONE
Priority: HIGH
Dependencies: TASK-011
Requirements: FR-010, FR-011, FR-012, FR-015, NFR-004

Goal:
Offline, always-safe generation of angle, 5–10 messages and evening hook from facts.

Scope:
- `app/generation/deterministic.py`: Vietnamese templates per fact category; neutral templates (greeting, open questions) without claims; hook template referencing one cited fact without presuming current state.
- Message count: target from settings, reduced (never < 5) rather than padded with claims.

Acceptance Criteria:
- [x] Rich fixture → 10 messages; minimal SUCCESS-eligible fixture (2 facts) → 5–10 messages.
- [x] Output passes all guardrail validators.
- [x] Deterministic: same input → same output.

Expected Files:
- app/generation/__init__.py, app/generation/deterministic.py, tests/test_generation_deterministic.py

Test:
- `pytest tests/test_generation_deterministic.py`

Completed:
- app/generation/deterministic.py `generate_deterministic(ledger, target_count) -> EngagementDraft`:
  - Vietnamese templates per category (post ×3 variants, interest ×3, bio, work, education, current city,
    hometown, provided image description, other), rotated within a category; neutral greeting (cites name only),
    4 open questions, closing — none assert anything about the customer.
  - Facts ordered post → interest → bio → work → education → location → image → other; each rendered candidate
    is checked with `check_text` + `check_entities` and dropped if it fails (prices/links/phones never quoted);
    quotes clipped at a word boundary to 120 chars.
  - The strongest fact grounds the evening hook ("Chào buổi tối! Mình chợt nhớ tới … Khi nào rảnh, bạn kể mình nghe
    thêm nhé?") and is not repeated in the sequence when ≥ 4 candidates exist.
  - Count = min(target, available grounded + 6 neutral, 2 × grounded when ≥ 3 usable facts), never < 5;
    sequences ≥ 8 include greeting + open question + closing; a neutral question after every 3 grounded.
  - Raises ValueError when nothing usable / no hook / too few facts safe to quote (pipeline → PARTIAL, TASK-014).
- app/guardrails.py: PRESUMPTION now tolerated when the phrase is verbatim in a cited fact (the customer's own words),
  consistent with the sales/sensitive exceptions.

Files Changed:
- app/generation/__init__.py, app/generation/deterministic.py, tests/test_generation_deterministic.py (new)
- app/guardrails.py (edit: presumption exception)

Tests:
- `python -m pytest -q` → 254 passed (19 new).
- Covered: rich fixture → 10 messages, 0 violations; minimal 2-fact profile → 8 messages, 0 violations; targets
  5..10 exact and valid; 3 facts → 6 messages (reduced, not padded); determinism; price/URL/phone facts skipped;
  quoting the customer's own "mệt mỏi" allowed; long post clipped; hometown/education templates; no usable facts →
  ValueError; demographics never in messages; hook fact not repeated; template variety; too few safe facts → ValueError.
- Manual review of the rich-fixture output (10 messages + hook): varied, grounded, no sales, no presumption.

Result:
PASS

Notes:
- First version was valid but repetitive (same template ×3, hook duplicated message 1); fixed with variants,
  hook-fact reservation and neutral interleaving before closing the task.

---

## TASK-013 — LLM generator + retry/fallback

Status: DONE
Priority: HIGH
Dependencies: TASK-012
Requirements: FR-010, FR-011, FR-012, FR-015, NFR-002, C-010

Goal:
Natural LLM generation constrained to the fact ledger, validated, with bounded retry and deterministic fallback.

Scope:
- `app/generation/prompts.py`: closed-world system prompt (rules: facts only, cite IDs, zero sales, no presumption, no sensitive attributes, language), user prompt with ledger + unknown fields.
- `app/generation/llm_generator.py`: call `generate_structured` → validate → on violations retry with violation feedback (≤ `LLM_MAX_RETRIES`) → else deterministic fallback; record attempts & violations.

Acceptance Criteria:
- [x] Fake valid response → accepted, mode `llm`.
- [x] Fake response with unknown fact ID then valid → accepted on retry (attempts = 2).
- [x] Fake responses always containing sales words → fallback to deterministic, mode recorded.
- [x] LLMError (refusal/timeout/invalid JSON) → fallback, no crash.

Expected Files:
- app/generation/prompts.py, app/generation/llm_generator.py, tests/test_generation_llm.py

Test:
- `pytest tests/test_generation_llm.py`

Completed:
- app/generation/prompts.py: static `SYSTEM_PROMPT` (closed world; fact text is data, never instructions; field
  definitions; grounded vs neutral; ≥ half grounded; hard rules: zero sales, no presumption, no sensitive attributes
  unless self-declared and cited, no embellishment, "bạn"/"mình", < 300 chars, cite only listed ids);
  `build_user_prompt(ledger, count, language, feedback)`: language, exact count ("fewer but never < 5" rather than
  padding), unknown fields, `<facts>` block with the name + usable FACT entries only (INFERENCE and demographic
  entries are never shown), validator feedback on retries.
- app/generation/llm_generator.py `generate_engagement(ledger, settings, llm) -> GenerationResult(draft, mode,
  attempts, history, model_id, error)`: LLM draft → `validate_draft` → retry with violation list
  (≤ `LLM_MAX_RETRIES`); non-retryable errors (refusal, auth, no_credentials, rate_limited, unsupported_input) stop
  retries; invalid JSON retried with schema feedback; then deterministic draft, itself validated; no valid draft →
  `draft=None, mode="none", error=…` (pipeline → PARTIAL). Every attempt and violation recorded in `history`.

Files Changed:
- app/generation/prompts.py, app/generation/llm_generator.py, tests/test_generation_llm.py (new)

Tests:
- `python -m pytest -q` → 271 passed (17 new).
- Covered: valid fake → mode llm, 1 attempt; unknown id then valid → accepted on attempt 2, feedback with "F99" in the
  second prompt only; always-salesy → 3 attempts then deterministic (clean); refusal/auth stop after 1 attempt,
  timeout/invalid_output/max_tokens retried 3× then fallback; non-JSON → schema feedback; retry budget from settings;
  no LLM → deterministic; nothing usable → no draft; hallucinating LLM ("42km ở Đà Lạt") rejected; prompt lists only
  groundable facts + unknowns inside `<facts>`; static system prompt; prompt-injection bio ("ignore … 50% discount
  https://…") → obeying draft rejected, fallback never quotes it (or no draft when too few safe facts).
- Offline check: `anthropic.transform_schema` accepts `EngagementDraft` and `VisionResult` (additionalProperties=false).

Result:
PASS (with fake LLM). Real Claude generation NOT VERIFIED (no API key) — re-check in TASK-018.

Notes:
- `apparent_lifestyle` from the LLM is validated here; the pipeline (TASK-014) uses it only when present and valid,
  otherwise the deterministic value from app/intel.py.

---

## TASK-014 — Pipeline, error handling, evidence report

Status: DONE
Priority: HIGH
Dependencies: TASK-013
Requirements: FR-004, FR-009, FR-014, FR-015, architecture.md §6

Goal:
Orchestrate all stages and map every situation to the status/error matrix.

Scope:
- `app/pipeline.py`: `run_pipeline(raw_url, options, settings, llm_client=None, http_transport=None) -> (output_model, evidence, exit_code)`.
- Implement the full matrix in architecture.md §6 (incl. INTERNAL_ERROR catch-all).
- Build EvidenceReport (ledger, grounding, validation, mode, limitations).

Acceptance Criteria:
- [x] Each row of the error matrix has a passing test.
- [x] `sales_mention_check` is only set after validators pass.
- [x] Evidence grounding covers every message of a SUCCESS output.

Expected Files:
- app/pipeline.py, tests/test_pipeline.py

Test:
- `pytest tests/test_pipeline.py`

Completed:
- app/pipeline.py `run_pipeline(raw_url, PipelineOptions(profile_file, mode, live, reference_year), settings,
  llm_client=None, http_transport=None) -> PipelineResult(output, evidence, exit_code)`:
  input validation → LLM availability (fail fast in `--mode llm`) → source chain (profile file → store → live, `live`
  defaults to `LIVE_FETCH_ENABLED`) → ledger → visual context (readable profiles only) → sufficiency gate →
  intelligence → generation (LLM w/ retries → deterministic) → final `validate_draft` → SuccessOutput.
- Error matrix fully implemented (architecture.md §6, two rows added: bad `--profile-file` → INVALID_INPUT exit 2;
  `--mode llm` without key → TECHNICAL LIMITATION exit 2; plus "generators cannot pass guardrails" → INSUFFICIENT_DATA).
  Gate notes are enriched with source-specific details (e.g. "…| Profile content is restricted to friends…",
  "…| NOT_FOUND: Facebook returned HTTP 404."); informational notes (synthetic, live scope) stay in evidence only.
- `ZERO_SALES_CONFIRMED` is set only in `_success`, after the final `validate_draft` returns no violations; a failing
  final check raises → INTERNAL_ERROR (exit 1), never a SUCCESS.
- EvidenceReport on every path: access state, sources, synthetic flag, collected_at, generation mode, model id,
  full ledger (incl. vision INFERENCE entries), unknown fields, grounding (angle, lifestyle, every message, hook),
  validation (passed, attempts incl. deterministic, full LLM history), technical limitations (+ store load errors,
  vision notes).
- LLM `apparent_lifestyle` used only when the LLM draft was accepted (already validated); otherwise app/intel.py value.
- Earlier hand-offs resolved: TASK-004 (exit 2 via `InputError.error_note`), TASK-005 (SourceError → INVALID_INPUT),
  TASK-006 (`live` wiring), TASK-007 (gate note enrichment), TASK-012 (ValueError → INSUFFICIENT_DATA),
  TASK-013 (lifestyle selection).

Files Changed:
- app/pipeline.py (new), tests/test_pipeline.py (new), architecture.md §6 (3 rows added)

Tests:
- `python -m pytest -q` → 295 passed (24 new).
- Matrix rows: missing URL (None/""/blank, exit 2); non-profile URL ×3 (exit 2); no data (TECHNICAL LIMITATION);
  live login wall; private fixture (name in file not leaked); dead link via live 404 and via provided data;
  unreachable (timeout); insufficient data; no image → SUCCESS with `NOT_AVAILABLE`; LLM failure → SUCCESS
  deterministic (attempts 4); unexpected exception → INTERNAL_ERROR exit 1; `--mode llm` without key; malformed /
  mismatched profile file.
- Success: rich fixture (canonicalised URL, demographics UNKNOWN, lifestyle INFERENCE, 10 messages, evidence
  grounding covers indices 0..9, all cited ids exist); LLM success with validated lifestyle; deterministic mode ignores
  an injected LLM; ZERO_SALES never emitted when the final validation fails; live public page end-to-end → honest
  INSUFFICIENT_DATA.
- Every test output re-parsed with `parse_output` after a JSON round-trip.

Result:
PASS

Notes:
- Vision runs before the gate (architecture order); its observations are INFERENCE so they never change the gate.

---

## TASK-015 — CLI + output writer

Status: DONE
Priority: HIGH
Dependencies: TASK-014
Requirements: FR-001, FR-013, NFR-001, NFR-008, NFR-010

Goal:
`python main.py --url ...` prints one JSON document and writes output.json / evidence.json.

Scope:
- `app/cli.py` (argparse, flags from architecture.md §7.1, UTF-8 stdout reconfigure, logging to stderr, exit codes; argparse errors still emit JSON).
- `app/output.py` (serialize with `ensure_ascii=False, indent=2`, write files UTF-8).
- `main.py` thin entry point.

Acceptance Criteria:
- [x] `python main.py --url "https://www.facebook.com/fixture.minh.anh"` → exit 0, stdout parses, equals output.json.
- [x] Missing `--url` → exit 2, stdout valid JSON with `INVALID_INPUT:`.
- [x] `--verbose` logs appear on stderr only.
- [x] Vietnamese text intact on Windows console and in files.

Expected Files:
- main.py, app/cli.py, app/output.py, tests/test_cli.py

Test:
- `pytest tests/test_cli.py` + manual run

Completed:
- app/cli.py `run(argv) -> exit code`: argparse with all flags of architecture.md §7.1 (`--url`, `--profile-file`,
  `--output`, `--evidence`, `--mode`, `--live`, `--messages`, `--verbose`); parser errors (unknown flag, bad choice)
  and configuration errors (e.g. `--messages 4`) are emitted as PARTIAL_OR_PRIVATE JSON with `INVALID_INPUT:` and
  exit 2; stdout/stderr reconfigured to UTF-8; logging → stderr (INFO with `--verbose`, else WARNING); exactly one
  JSON document written to stdout; same text written to `--output`; evidence to `--evidence` (parent dirs created);
  file write failure → JSON still printed, error on stderr, exit 1.
- app/output.py: `serialize_output` / `serialize_evidence` (`ensure_ascii=False, indent=2`), `write_text` (UTF-8).
- main.py: thin entry point (`sys.exit(run())`); works from any cwd.

Files Changed:
- main.py, app/cli.py, app/output.py, tests/test_cli.py (new)
- output.json, evidence.json (generated in repo root by the manual run; regenerated in TASK-018)

Tests:
- `python -m pytest -q` → 307 passed (12 new; CLI tests run main.py as a subprocess with no API key and no
  PYTHONIOENCODING, decoding stdout strictly as UTF-8).
- Covered: rich fixture (exit 0, stdout == output.json, Vietnamese not escaped, evidence written, empty stderr);
  missing --url (exit 2 JSON); unknown flag; invalid --mode; --verbose logs on stderr only; --messages 5/7;
  --messages 4 → exit 2; custom --output/--evidence + --profile-file; private → exit 0 PARTIAL; --mode llm without
  key → exit 2; unwritable output → JSON on stdout, exit 1.
- Manual (PowerShell, Windows 11): `python main.py --url "https://www.facebook.com/fixture.minh.anh"` → exit 0;
  Vietnamese text and emoji render correctly; output.json parses.

Result:
PASS

Notes:
- `--help` prints argparse help text (not JSON) by design; every actual run prints JSON.
- Manual run exposed a cosmetic bug in TASK-012 templates → recorded as BUG-001 (not fixed silently here).

---

## BUG-001 — Double punctuation after quoted fact text

Status: DONE
Priority: LOW
Related Task: TASK-012
Dependencies: None

Problem:
Deterministic templates append "." after a closing quote even when the quoted fact already ends with sentence
punctuation, e.g. `… vừa ra lá mới, mừng ghê.”. Chuyện đó…` and the hook `… mệt nhưng vui!”. Khi nào rảnh…`.
Found during the TASK-015 manual CLI run.

Expected:
No extra "." when the quoted text already ends with `.`, `!`, `?` or `…` (e.g. `mừng ghê.” Chuyện đó…`).

Fix:
In app/generation/deterministic.py, render quotes through a helper that omits the template's trailing period when the
quote ends with sentence punctuation. Add a regression test; keep all guardrail tests passing.

Acceptance Criteria:
- [x] No `”.` sequence follows a quote ending in . ! ? … in any generated text for the repo fixtures.
- [x] Full test suite passes.

Completed:
- app/generation/deterministic.py: `_tidy()` removes the template period after a quote ending in . ! ? …
  (`ghê.”.` → `ghê.”`); message and hook rendering go through it (`_render_message` / `_render_hook` → `_message_for`
  / `_hook_for`). Plain quotes keep their period (`sourdough”.`).
- app/guardrails.py: the sentence splitter also ends a sentence after a closing quote/bracket preceded by end
  punctuation. Without it, the capitalised word after `ghê.”` was treated as mid-sentence → UNGROUNDED_ENTITY → the
  candidate was dropped (caught by 2 existing tests during the fix).
- README "Known limitations": BUG-001 mention removed. output.json, evidence.json, test_results.json regenerated.

Files Changed:
- app/generation/deterministic.py, app/guardrails.py, tests/test_generation_deterministic.py (+2 regression tests)
- README.md, output.json, evidence.json, test_results.json (regenerated)

Tests:
- First attempt: 2 existing tests failed (long-post clipping, template variety) → root cause above → fixed.
- `python -m pytest -q` → 346 passed (2 new: no `[.!?…]”.` in any message/hook/angle for all eligible fixtures; `_tidy`
  unit cases).
- `python scripts/run_test_profiles.py` → exit 0 (6 PASS, 1 NOT_RUN); `grep '[.!?…]”\.'` in output.json and
  test_results.json → 0 matches.

Result:
PASS

Notes:
- Regenerating test_results.json made one more unauthenticated request to facebook.com/facebook (LOGIN_REQUIRED).

---

## TASK-016 — Full fixture set

Status: DONE
Priority: MEDIUM
Dependencies: TASK-015
Requirements: §24 test matrix, C-009

Goal:
Synthetic fixtures covering every data-availability case.

Scope:
- Add: partial profile (name + 2 facts), name-only (insufficient), dead link (NOT_FOUND), no-image rich profile, profile with explicit pronouns/birth year, profile.php?id= URL variant.
- All `"synthetic": true`, fictional names, no real people.

Acceptance Criteria:
- [x] ≥ 7 fixtures total, each loads and maps to its intended status.
- [x] Fixture index documented in `fixtures/README.md`.

Expected Files:
- fixtures/profiles/*.json, fixtures/README.md

Test:
- `pytest tests/test_sources_provided.py tests/test_ledger.py`

Completed:
- 6 new synthetic fixtures (8 total): partial_thu_ha (PARTIAL, name + 2 facts → SUCCESS, 8 messages), name_only
  (→ INSUFFICIENT_DATA), dead_link (NOT_FOUND), no_image_quoc_bao (rich, no image → SUCCESS with
  `NOT_AVAILABLE: no public image provided`), declared_khanh_linh (pronouns + gender + birth year → derived and
  labelled demographics), profile_id_variant (`profile.php?id=` URL → SUCCESS).
- fixtures/README.md: purpose (synthetic only), lookup mechanism, index table (file, URL, scenario, expected result),
  format notes.
- tests/test_fixtures.py: every fixture is synthetic, indexed in the README, loads without store errors, and maps
  to its documented access state / status / note prefix through the real pipeline.

Files Changed:
- fixtures/profiles/{partial_thu_ha,name_only,dead_link,no_image_quoc_bao,declared_khanh_linh,profile_id_variant}.json (new)
- fixtures/README.md (new), tests/test_fixtures.py (new)

Tests:
- `pytest tests/test_fixtures.py tests/test_sources_provided.py tests/test_ledger.py` → 48 passed.
- `python -m pytest -q` → 319 passed (12 new).
- Manual: message counts thu.ha 8, quoc.bao 10, profile.php 10 (match README).

Result:
PASS

Notes:
- Numeric profile id 100000000000042 is a placeholder; no network access happens for fixtures.
- BUG-001 visible in the quoc.bao hook (`xứng đáng.”.`) — still tracked separately.

---

## TASK-017 — Integration tests

Status: DONE
Priority: HIGH
Dependencies: TASK-016
Requirements: §24 test matrix, NFR-001, NFR-002, NFR-006

Goal:
End-to-end CLI tests across the full matrix, offline.

Scope:
- `tests/test_integration.py`: subprocess runs per fixture; assert stdout JSON == output.json, schema validity, exit codes, zero-sales, 5..10 messages, demographics honesty, evidence presence.
- LLM path via injected fake client (in-process pipeline test) incl. hallucinating fake → rejected.

Acceptance Criteria:
- [x] Matrix covered: valid/invalid/missing URL; public/partial/private/dead/no-image; valid/invalid AI output; hallucination prevention; 5 & 10 messages; ZERO_SALES; stdout + output.json.
- [x] Full `pytest` passes offline with no API key.

Expected Files:
- tests/test_integration.py

Test:
- `python -m pytest -q`

Completed:
- tests/test_integration.py organised by the brief's §24 matrix:
  - Input: valid URL; invalid ×3 (groups path, foreign host, non-URL) → exit 2; missing URL → exit 2.
  - Data: public, public-no-image, self-declared, profile.php id, PARTIAL → SUCCESS; private / dead / name-only →
    PARTIAL_OR_PRIVATE with PRIVATE_PROFILE / NOT_FOUND / INSUFFICIENT_DATA; unknown profile → TECHNICAL LIMITATION.
  - AI (in-process pipeline + fake LLM): valid structured output used (mode llm); invalid output ×3 forms → valid
    deterministic SUCCESS; hallucination ("marathon Đà Lạt 42km", "đi làm về") rejected and never emitted
    (UNGROUNDED_ENTITY / UNGROUNDED_NUMBER / PRESUMPTION recorded); missing info stays UNKNOWN and unknown fields are
    passed to the prompt; LLM sales copy never reaches output.
  - Rapport: `--messages 5` and `10`; zero-sales invariants over every SUCCESS fixture.
  - Output: single JSON document on stdout, schema-valid, exact top-level key set, equal to output.json,
    Vietnamese stored unescaped.
- Independent invariant checker (`assert_success_invariants`): no price/URL/phone/e-mail/hashtag; commercial terms and
  presumption phrases only if present in the cited facts; demographics UNKNOWN or labelled self-declared/derived;
  lifestyle UNKNOWN or INFERENCE; grounding covers every message; all citations are FACT entries.
- tests/conftest.py: autouse network guard (socket connect / create_connection raise) proving the suite is offline.

Files Changed:
- tests/test_integration.py (new), tests/conftest.py (new)

Tests:
- `python -m pytest -q` → 344 passed (25 new) with the network guard active and no ANTHROPIC_* variables
  (CLI subprocesses run with ANTHROPIC_*/LLM_*/PYTHONIOENCODING stripped).
- Guard self-check (scratchpad): a test opening a socket to example.com is blocked by the guard.

Result:
PASS

Notes:
- The subprocess CLI runs cannot be network-guarded by the fixture, but they only use local fixtures (live off).

---

## TASK-018 — Three-profile test run → test_results.json

Status: DONE
Priority: HIGH
Dependencies: TASK-017
Requirements: FR-016, brief §25

Goal:
Required final run on ≥ 3 representative profiles, recorded.

Scope:
- `scripts/run_test_profiles.py`: runs ≥ 3 inputs (public-rich, partial, private/dead; plus LLM mode if key available; plus `--live` attempt on a URL to document the real-world limitation), writes `test_results.json` with input, status, mode, validation result, duration, limitation notes.
- Commit `output.json` + `evidence.json` produced from the public-rich synthetic fixture.

Acceptance Criteria:
- [x] test_results.json has ≥ 3 entries and states clearly that inputs are synthetic fixtures (TECHNICAL LIMITATION).
- [x] Every entry's output passes schema validation.

Expected Files:
- scripts/run_test_profiles.py, test_results.json, output.json, evidence.json

Test:
- `python scripts/run_test_profiles.py` then `python -c "import json; json.load(open('test_results.json', encoding='utf-8'))"`

Completed:
- scripts/run_test_profiles.py: runs 7 cases through the real CLI (subprocess), per-case files in git-ignored
  `runs/test_run/<case>/`, checks per case (single JSON on stdout, stdout == output.json, schema valid, and for
  SUCCESS: ZERO_SALES_CONFIRMED, 5–10 messages, grounding recorded for every message), writes `test_results.json`
  (environment, `data_note` TECHNICAL LIMITATION, summary, per-case details incl. full output) and copies the
  public-rich output/evidence to the repo root.
- Results (2026-10-06): public_rich PASS (SUCCESS, 10 msgs), partial_access PASS (SUCCESS, 8 msgs), public_no_image
  PASS (SUCCESS), private_profile PASS (PRIVATE_PROFILE), dead_link PASS (NOT_FOUND), llm_mode_public_rich NOT_RUN
  (no ANTHROPIC_API_KEY), live_facebook_attempt PASS (PARTIAL_OR_PRIVATE / LOGIN_REQUIRED).
- Real-world finding: one unauthenticated GET to https://www.facebook.com/facebook (Meta's own page, chosen to avoid
  any private individual) returned a login/checkpoint page in 1.7 s → confirms the Phase 0 TECHNICAL LIMITATION; the
  agent reported it and stopped (no retry, no bypass).

Files Changed:
- scripts/run_test_profiles.py (new; scripts/.gitkeep removed)
- test_results.json (new), output.json + evidence.json (regenerated from public_rich)

Tests:
- `python scripts/run_test_profiles.py` → exit 0; summary 7 cases: 6 PASS, 0 FAIL, 1 NOT_RUN.
- `python -c "import json; json.load(open('test_results.json', encoding='utf-8'))"` → OK.
- Every embedded output re-validated with `parse_output` → OK; `runs/` confirmed git-ignored.
- `python -m pytest -q` → 344 passed.

Result:
PASS

Notes:
- Still NOT VERIFIED: real Claude calls (TASK-008 / TASK-009 / TASK-013 gaps). To verify: put ANTHROPIC_API_KEY in .env and
  rerun `python scripts/run_test_profiles.py` — the llm_mode case will then run and be recorded.
- No real personal profiles were used; the brief allows 3 representative fixtures when direct access is not feasible.

---

## TASK-019 — README

Status: DONE
Priority: HIGH
Dependencies: TASK-018
Requirements: NFR-003, brief §26

Goal:
Reviewer can clone → install → run one command → get result.

Scope:
- Sections: requirements, installation, env vars, configuration, run command, example input, example output, error handling, architecture overview, known limitations (Facebook access, lexicon limits, synthetic test data).

Acceptance Criteria:
- [x] Every command in README executed and works as written.
- [x] Known limitations include the TECHNICAL LIMITATION on Facebook access.

Expected Files:
- README.md

Test:
- Manual: follow README in a fresh venv.

Completed:
- README.md rewritten (was the Phase 0 placeholder): overview + one-command quick start + up-front TECHNICAL
  LIMITATION box; 1 Requirements; 2 Installation (venv activation per shell, Windows notes: long paths, PowerShell
  execution policy); 3 Environment variables (all 9, defaults); 4 CLI options; 5 Run (fixture examples,
  `--profile-file`, pytest, final test run); 6 Example input; 7 Example output (SUCCESS abridged, PARTIAL, evidence
  description); 8 Error handling (full matrix with prefixes and exit codes); 9 Architecture overview (+ source map);
  10 Known limitations (Facebook access, synthetic test data, Claude path not verified live, rule-based guardrails,
  template naturalness / BUG-001, no scheduler/sending, demographics often UNKNOWN).

Files Changed:
- README.md

Tests:
- Fresh copy of the working tree (no .venv/runs/caches) + new venv: `pip install -r requirements.txt` → OK;
  README commands run as written with no API key / no PYTHONIOENCODING:
  fixture.minh.anh → exit 0 SUCCESS (10); fixture.thu.ha → exit 0 SUCCESS (8); fixture.private.user → exit 0
  PRIVATE_PROFILE; `--profile-file … --output runs/thu_ha/…` → exit 0, files created; `python -m pytest -q` →
  344 passed; `python scripts/run_test_profiles.py` → exit 0 (6 PASS, 1 NOT_RUN).
- Activation verified: Git Bash `source .venv/Scripts/activate`; PowerShell `.venv\Scripts\Activate.ps1` (policy Bypass in
  this shell) and direct `.venv\Scripts\python.exe main.py …` → exit 0.
- Verification copy removed afterwards (runs/cc).

Result:
PASS

Notes:
- Finding: in a deeply nested directory (the scratchpad) `pip install` failed with the Windows 260-char path limit
  (anthropic SDK file names ≈ 86 chars) → documented under "Windows notes"; the repo path itself is fine.
- `git clone <repository-url>` could not be exercised (no remote configured); the rest of the flow was.
- Re-running scripts/run_test_profiles.py made one more unauthenticated request to facebook.com/facebook
  (result again LOGIN_REQUIRED).
- README example output must be refreshed if BUG-001 changes the template text (TASK-020 checklist).

---

## TASK-020 — Final review & cleanup

Status: DONE
Priority: MEDIUM
Dependencies: TASK-019
Requirements: brief §29 checklist

Goal:
Verify the final checklist and leave the repo clean.

Scope:
- Run full test suite; fresh-venv install + one-command run.
- Secret scan (no keys), no stray files, no real personal data, task.md counts accurate.

Acceptance Criteria:
- [x] All items in brief §29 checklist ticked with evidence.
- [x] task.md: TODO 0, IN_PROGRESS 0, BLOCKED 0 (SKIPPED only with justification).

Expected Files:
- (edits only)

Test:
- `python -m pytest -q`; manual run.

Completed:
- Documentation vs implementation: every "Expected Files" entry of every DONE task exists (only
  `fixtures/images/` absent — optional "(if needed)", TASK-009 notes it was not needed). No mismatch.
- Cleanup: 4 unused imports removed from tests (found with a temporary `pyflakes`, uninstalled afterwards; not a
  project dependency); `compileall` OK; doc headers DRAFT → APPROVED; architecture.md module tree + `lexicons.py`.
- Secret / privacy scan over all files that would be committed: no real keys (only the obviously fake test strings
  `sk-ant-test-not-real…`), no `.env`, no e-mail addresses or phone numbers (one regex hit = placeholder
  `profile.php?id=`), no local paths in artifacts, user e-mail not present. Fixtures are synthetic; the only live
  request targeted Meta's own page.
- Fresh environment (copy of the working tree, new venv): `pip install -r requirements.txt` → OK;
  `python main.py --url "https://www.facebook.com/fixture.minh.anh"` → exit 0, stdout == output.json, SUCCESS,
  10 messages, ZERO_SALES_CONFIRMED; `python -m pytest -q` → 346 passed. Copy removed afterwards.

Brief §29 checklist (evidence):
- [x] requirements.md complete — 16 FR / 11 NFR / 10 C, acceptance criteria, traceability.
- [x] architecture.md complete — pipeline, modules, data model, AI design, error matrix (13 rows), interfaces.
- [x] plan.md complete — MVP, ADRs, order, testing, runability, decisions (approved).
- [x] task.md updated — every task has Completed / Files / Tests / Result.
- [x] No TODO task left — TODO 0.
- [x] No IN_PROGRESS task unresolved — IN_PROGRESS 0.
- [x] No BLOCKED task hidden — BLOCKED 0.
- [x] CLI works — fresh-venv run exit 0; tests/test_cli.py (12), tests/test_integration.py (25).
- [x] Strict JSON works — exact schema models with extra="forbid"; single JSON on stdout for every path incl. usage errors.
- [x] output.json works — identical to stdout (CLI + integration tests, fresh-venv check).
- [x] Zero hallucination handled — fact ledger + mandatory citations + guardrails; hallucinating fake LLM rejected
  (UNGROUNDED_ENTITY / NUMBER / PRESUMPTION); demographics only self-declared; vision = INFERENCE.
- [x] Private/dead link handled — PRIVATE_PROFILE / NOT_FOUND (fixtures, live 404), test_results.json cases.
- [x] Zero-sales rule validated — lexicons + price/URL/phone/e-mail/hashtag detectors; independent invariant checker;
  ZERO_SALES_CONFIRMED only after final validation.
- [x] Evening hook works — grounded, presumption-checked, `trigger_time: "20:00"` in every SUCCESS output.
- [x] 3 test runs completed — test_results.json: 6 PASS (5 representative fixtures + real Facebook attempt), 1 NOT_RUN (LLM, no key).
- [x] test_results.json exists — with TECHNICAL LIMITATION data note.
- [x] README works — every command re-run in a fresh copy (TASK-019) and the main command again here.
- [x] .env.example exists — all 9 variables, empty key.
- [x] No secrets committed — scan above (nothing has been committed yet; no secret in any file to be committed).
- [x] No unnecessary files — .venv, runs/, caches git-ignored; files to commit = app, tests, fixtures, scripts, docs,
  artifacts, config.
- [x] No unrelated modifications — only .gitignore (+`runs/`) and README.md changed among pre-existing files.

Files Changed:
- tests/test_generation_deterministic.py, tests/test_guardrails.py, tests/test_llm_adapter.py (unused imports)
- requirements.md, architecture.md, plan.md (status headers; architecture module tree), task.md

Tests:
- `python -m pytest -q` → 346 passed (repo and fresh venv); pyflakes clean; compileall OK.

Result:
PASS

Notes:
- Open, documented gap (not a task): real Claude calls (generation + vision) were never executed because no
  ANTHROPIC_API_KEY was available. Covered by fake-client tests and SDK-shape checks; to verify, add the key to .env and
  run `python scripts/run_test_profiles.py` (case llm_mode_public_rich).
- Nothing has been committed to git; committing is left to the user.
