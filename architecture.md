# Architecture — Facebook Profiler Agent (TES-3808)

> Status: **APPROVED** 2026-10-06 (Phase 0) · kept in sync with the implementation (see task.md notes for changes)
> Related docs: [requirements.md](requirements.md) · [plan.md](plan.md) · [task.md](task.md)

---

## 1. First Principles: Problem → Capability → Mechanism → Technology

| Problem | Required capability | Mechanism | Technology |
|---|---|---|---|
| Get profile data without breaking rules | Read only legitimately accessible data, detect when access is denied | Pluggable data sources: provided JSON (primary), single public-meta GET (opt-in) | `pathlib`/`json`, `httpx`, stdlib `html.parser` |
| Keep facts separate from guesses | Typed evidence with provenance and epistemic status | Fact Ledger (`F1..Fn`, category, source, FACT/INFERENCE/UNKNOWN) | Pydantic v2 models |
| Decide SUCCESS vs PARTIAL honestly | Rule-based sufficiency gate | Deterministic thresholds on ledger | Plain Python |
| Describe a public image | Understand image content | Multimodal model, constrained prompt, observation-only schema | Claude (vision) via adapter |
| Write warm, natural, grounded Vietnamese messages | Natural language generation conditioned on facts | LLM with structured output citing fact IDs; template fallback | Claude structured output via adapter; deterministic templates |
| Never emit sales / invented claims | Verifiable output rules | Deterministic validators (schema, grounding IDs, lexicons, presumption patterns) + bounded retry + fallback | Pydantic + regex lexicons |
| Strict machine-readable output | Exact schema, stdout/file parity | Output models with `extra="forbid"`, single serializer | Pydantic + `json` |

**Where AI is NOT used (deterministic on purpose):** URL validation, data loading, access-state detection,
fact-ledger construction, demographic fields (explicit data only), SUCCESS/PARTIAL decision, zero-sales check,
grounding check, JSON serialization.

---

## 2. High-level Pipeline

```text
CLI (main.py / app.cli)
 │  parse args, force UTF-8, logs → stderr
 ▼
Input Validation (app.input)            ── invalid ─────────────────────────┐
 │  canonical URL                                                           │
 ▼                                                                          │
Profile Data Acquisition (app.sources)                                      │
 │  ProfileSource adapters: ProvidedFileSource → FixtureStoreSource →       │
 │  LivePublicMetaSource (opt-in)  ⇒  RawProfile + AccessState              │
 ▼                                                                          │
Data Normalization (app.ledger)                                             │
 │  RawProfile ⇒ FactLedger (FACT / INFERENCE / UNKNOWN, with sources)      │
 ▼                                                                          │
Visual Context Analysis (app.vision)  [optional, LLM adapter]               │
 │  image ⇒ observations ⇒ appended to ledger as visual facts               │
 ▼                                                                          │
Sufficiency Gate (app.ledger.gate)     ── insufficient / private / dead ────┤
 ▼                                                                          │
Profile Intelligence (app.intel)                                            │
 │  demographics (explicit-only rules), lifestyle (cited inference)         │
 ▼                                                                          │
Engagement Generation (app.generation)                                      │
 │  LLM generator (structured, cites fact IDs)  or  Deterministic generator │
 │  ⇒ empathy angle + 5–10 rapport messages + 20:00 hook                    │
 ▼                                                                          │
Guardrail Validation (app.guardrails)                                       │
 │  schema · grounding · zero-sales · presumption · sensitive-attribute     │
 │  fail → retry LLM (≤2, with violations as feedback) → deterministic      │
 ▼                                                                          │
Output Assembly & Validation (app.output)  ◄────────────────────────────────┘
 │  SuccessOutput | PartialOutput (strict schema)  +  EvidenceReport
 ▼
stdout (one JSON doc)  +  output.json  +  evidence.json
```

---

## 3. Module Layout

```text
facebook-profiler-agent/  (repo root)
├── main.py                     # thin entry: from app.cli import run; sys.exit(run())
├── app/
│   ├── __init__.py
│   ├── cli.py                  # argparse, UTF-8 stdout, exit codes, logging setup
│   ├── config.py               # Settings from env/.env (pydantic model, no SDK import)
│   ├── input.py                # URL validation + canonicalization
│   ├── models.py               # Domain models: RawProfile, AccessState, Fact, FactLedger, ...
│   ├── schema.py               # Output models (exact brief schema) + EvidenceReport
│   ├── sources/
│   │   ├── base.py             # ProfileSource protocol, AcquisitionResult
│   │   ├── provided.py         # --profile-file and fixture store lookup
│   │   └── live_meta.py        # opt-in single GET, og:* parsing, login-wall detection
│   ├── ledger.py               # normalization → FactLedger; sufficiency gate
│   ├── llm/
│   │   ├── base.py             # LLMClient protocol: generate_structured(), describe_image()
│   │   ├── anthropic_client.py # Claude adapter (only module importing `anthropic`)
│   │   └── fake.py             # scripted fake for tests
│   ├── vision.py               # visual context extraction (uses LLMClient)
│   ├── intel.py                # demographics + lifestyle rules
│   ├── generation/
│   │   ├── prompts.py          # system/user prompt builders
│   │   ├── llm_generator.py    # structured LLM generation + retry loop
│   │   └── deterministic.py    # template-based generator (offline fallback)
│   ├── guardrails.py           # validators: grounding, zero-sales, presumption, sensitive
│   ├── lexicons.py             # vi/en word lists + price/URL/phone/presumption patterns
│   ├── pipeline.py             # orchestration + error handling → (output, evidence)
│   └── output.py               # serialization, stdout/file writing
├── fixtures/
│   └── profiles/*.json         # synthetic personas (public, partial, private, dead, no-image)
├── tests/                      # unit + integration (offline)
├── scripts/run_test_profiles.py# 3+ profile run → test_results.json
├── requirements.txt
├── .env.example
├── README.md · requirements.md · architecture.md · plan.md · task.md
├── output.json · evidence.json · test_results.json   # produced from synthetic fixtures
└── runs/                       # git-ignored: outputs of runs on real URLs
```

Dependency direction: `cli → pipeline → (sources, ledger, vision, intel, generation, guardrails, output) → models/schema`.
Only `app/llm/anthropic_client.py` imports the `anthropic` SDK; only `app/sources/live_meta.py` does network I/O to Facebook.

```text
External Service (Claude API, facebook.com)
        ↓
Adapter (llm/anthropic_client.py, sources/live_meta.py)
        ↓
Protocol (llm/base.py LLMClient, sources/base.py ProfileSource)
        ↓
Application (pipeline, generation, vision)
```

---

## 4. Data Model

### 4.1 Input profile data (provided JSON / fixture format)

```json
{
  "facebook_url": "https://www.facebook.com/fixture.minh.anh",
  "synthetic": true,
  "access": { "state": "PUBLIC", "note": "" },
  "collected_at": "2026-10-06T09:00:00+07:00",
  "collection_method": "manual_export | fixture | live_meta",
  "display_name": "Minh Anh",
  "bio": "Yêu cà phê sáng, chạy bộ cuối tuần ...",
  "public_info": {
    "work": ["..."], "education": ["..."], "interests": ["..."], "current_city": "...", "hometown": null,
    "pronouns": null, "gender": null, "birth_year": null, "links": []
  },
  "public_posts": [ { "date": "2026-09-28", "text": "..." } ],
  "images": [ { "kind": "avatar", "path": "fixtures/images/minh_anh.jpg", "url": null, "alt_text": "..." } ]
}
```

Every field is optional except `facebook_url`; `null`/missing/blank → `UNKNOWN` in the ledger. Unknown keys are
rejected (typos must not be silently ignored). `public_info.gender` means the gender exactly as displayed in the
profile's public About section (self-declared), never a guess.
`access.state` lets fixtures represent PRIVATE / NOT_FOUND cases without network.

### 4.2 Domain models (`app/models.py`)

```text
AccessState   = PUBLIC | PARTIAL | PRIVATE | LOGIN_REQUIRED | NOT_FOUND | UNREACHABLE | INVALID_INPUT | NO_ACCESSIBLE_DATA
EpistemicStatus = FACT | INFERENCE | UNKNOWN

AcquisitionResult { canonical_url, access_state, raw: RawProfile | None, source_name, synthetic: bool, limitations: [str] }
  # raw is only set for PUBLIC/PARTIAL; a profile file whose facebook_url != --url is rejected (SourceError)

Fact {
  id: "F1",
  category: name | bio | work | education | location | interest | post | visual_observation | pronouns | gender | birth_year | other,
  statement: str,              # verbatim or minimally normalized text
  source: str,                 # e.g. "profile_file:bio", "og:description", "vision:avatar"
  epistemic_status: FACT | INFERENCE,   # UNKNOWN items are kept in unknown_fields, never as entries
  confidence: float | None     # only for visual observations / inferences
}

FactLedger { facts: [Fact], unknown_fields: [str] }
  .usable_facts()  → FACT items excluding name
```

### 4.3 Output models (`app/schema.py`) — exact brief schema, `extra="forbid"`

```text
SuccessOutput {
  status: "SUCCESS", facebook_url,
  profile_data { customer_name, visual_context,
                 estimated_demographics { gender, estimated_age_range, apparent_lifestyle } },
  ethical_rapport { core_empathy_angle, dialogue_sequence_10: [str] (5..10), sales_mention_check: "ZERO_SALES_CONFIRMED" },
  evening_cadence_20pm { trigger_time: "20:00", evening_hook_message }
}

PartialOutput { status: "PARTIAL_OR_PRIVATE", facebook_url, error_note }
```

### 4.4 Evidence report (`evidence.json`, outside the strict schema)

```text
EvidenceReport {
  facebook_url, output_status, access_state, sources_used, synthetic_data: bool, collected_at,
  generation_mode: llm | deterministic | none, model_id | null, fact_ledger: [Fact], unknown_fields,
  grounding: { core_empathy_angle: [fact_ids], apparent_lifestyle: [fact_ids],
               messages: [{index, kind: grounded|neutral, fact_ids}], evening_hook: [fact_ids] },
  validation: { passed: bool, attempts: int, violations: [str] },
  technical_limitations: [str]
}
```

---

## 5. AI Architecture

```text
Data acquisition ─► Structured profile (RawProfile) ─► Fact Ledger
                                                     │
                       public image ─► [AI-1 Vision] ─► observations ─► validator ─► visual facts
                                                     │
                                       Fact Ledger (+ visual facts)
                                                     │
                                 [AI-2 Engagement LLM, structured output]
                                                     │
                       Pydantic parse ─► Guardrail validators ─► business rules (gate, schema)
                                                     │ fail (≤2 retries with feedback)
                                                     ▼
                                     Deterministic generator (always available)
```

### 5.1 AI-1 — Visual context extraction

| Question | Answer |
|---|---|
| Why AI? | Image content cannot be described with deterministic code. |
| Input | One public image (local file or allowed URL) + constrained instructions. |
| Output | `{ observations: [{text, confidence}], image_usable: bool }` — "appears to show …" phrasing only. |
| Validation | Pydantic schema; sensitive-attribute lexicon (ethnicity, religion, health, orientation, politics, family role e.g. "mother of", "his wife"); max 5 observations. |
| If AI fails | `visual_context = "NOT_AVAILABLE: <reason>"`; pipeline continues. |
| Hallucination control | Observation-only schema; forbidden categories (`app/lexicons.py`); confidence < 0.6 dropped; must be phrased "appears to show …"; observations stored as `visual_observation` entries with `source=vision:<kind>` and status **INFERENCE** (model-generated, with confidence) — shown in `visual_context` (labelled "AI VISUAL OBSERVATION … unverified") but never used to ground messages or demographics. Provided `alt_text` stays FACT (labelled "PROVIDED IMAGE DESCRIPTION") and is screened with the same lexicon. |
| Deterministic alternative? | Partial: `alt_text` from provided data is used when present (no vision call needed). |

### 5.2 AI-2 — Engagement generation (empathy angle + rapport messages + evening hook)

One structured call generates all three to keep tone coherent; validated per section.

| Question | Answer |
|---|---|
| Why AI? | Natural, empathetic, context-specific Vietnamese phrasing is hard to template well. |
| Input | Fact ledger (FACT items with IDs only; UNKNOWN fields listed as "do not mention"), language, message count target, hard rules. |
| Output (structured) | `{ core_empathy_angle: {text, fact_ids}, messages: [{text, kind: grounded|neutral, fact_ids}], evening_hook: {text, fact_ids}, apparent_lifestyle: {text|null, fact_ids} }` |
| Validation | (1) schema parse; (2) all `fact_ids` exist, are FACT (not INFERENCE, e.g. AI vision) and not demographic (pronouns/gender/birth_year); (3) grounded items cite ≥1 id, hook & angle cite ≥1; (4) count 5–10; (5) zero-sales lexicon & structural checks (prices, currency, %, URLs, phone numbers, CTA verbs); (6) presumption patterns for the hook (e.g. "chắc bạn vừa…", "hôm nay bạn đã…"); (7) sensitive-attribute lexicon (sales/sensitive terms tolerated only if verbatim in a cited fact); (8) numbers/proper nouns in text must appear in cited facts (heuristic); (9) neutral messages cite no facts and assert nothing about the customer; ≥ ⌈n/2⌉ grounded when ≥ 3 usable facts; no duplicates; ≤ 400 chars. Implemented in `app/guardrails.py`. |
| If AI fails | Retry ≤ 2 with the violation list as feedback → deterministic generator → if even that cannot satisfy rules, PARTIAL_OR_PRIVATE with note. `ZERO_SALES_CONFIRMED` is only written after validators pass. |
| Hallucination control | Closed-world prompt ("only these facts exist"), mandatory citations, ID verification, entity-overlap heuristic, neutral messages forbidden from making claims about the person. |
| Deterministic alternative? | Yes — template generator selects facts by category and fills Vietnamese templates. Always available; used offline and as fallback. Less natural but fully grounded. |

### 5.3 Provider choice

- **Default model:** Claude Opus 5.5 (`claude-opus-5-5`) via the official `anthropic` Python SDK; supports vision and structured outputs (`client.messages.parse` / `output_config.format`). Model id configurable via `LLM_MODEL`.
- `stop_reason` (`refusal`, `max_tokens`) is checked before parsing; such cases count as a failed attempt.
- The adapter is the only provider-aware code; swapping providers = new adapter implementing `LLMClient`.

---

## 6. Status & Error Handling Matrix

| Situation | Access state | Output status | `error_note` prefix | Exit code |
|---|---|---|---|---|
| Missing `--url` | — | PARTIAL_OR_PRIVATE | `INVALID_INPUT:` | 2 |
| Non-Facebook / non-profile URL | INVALID_INPUT | PARTIAL_OR_PRIVATE | `INVALID_INPUT:` | 2 |
| `--profile-file` unreadable / malformed / for another URL | INVALID_INPUT | PARTIAL_OR_PRIVATE | `INVALID_INPUT:` | 2 |
| `--mode llm` without `ANTHROPIC_API_KEY` | — | PARTIAL_OR_PRIVATE | `TECHNICAL LIMITATION:` | 2 |
| No provided data, live disabled | NO_ACCESSIBLE_DATA | PARTIAL_OR_PRIVATE | `TECHNICAL LIMITATION:` | 0 |
| Live fetch → login wall / checkpoint | LOGIN_REQUIRED | PARTIAL_OR_PRIVATE | `TECHNICAL LIMITATION:` | 0 |
| Private profile | PRIVATE | PARTIAL_OR_PRIVATE | `PRIVATE_PROFILE:` | 0 |
| Dead link (404/410/unavailable) | NOT_FOUND | PARTIAL_OR_PRIVATE | `NOT_FOUND:` | 0 |
| Network error / timeout | UNREACHABLE | PARTIAL_OR_PRIVATE | `UNREACHABLE:` | 0 |
| Accessible but below sufficiency gate | PUBLIC/PARTIAL | PARTIAL_OR_PRIVATE | `INSUFFICIENT_DATA:` | 0 |
| Generators cannot build a draft that passes the guardrails | PUBLIC/PARTIAL | PARTIAL_OR_PRIVATE | `INSUFFICIENT_DATA:` | 0 |
| No image | — | SUCCESS (visual_context `NOT_AVAILABLE: …`) | — | 0 |
| LLM failure after retries | — | SUCCESS via deterministic (mode recorded in evidence) | — | 0 |
| Unexpected exception | — | PARTIAL_OR_PRIVATE | `INTERNAL_ERROR:` | 1 |

In every case stdout contains exactly one valid JSON document and `output.json` is written.

---

## 7. Interfaces

### 7.1 CLI

```bash
python main.py --url "https://www.facebook.com/<username>"
               [--profile-file path/to/profile.json]
               [--output output.json] [--evidence evidence.json]
               [--mode auto|llm|deterministic] [--live] [--messages 5..10] [--verbose]
```

### 7.2 Configuration (env / `.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (unset) | Enables LLM mode in `auto`. |
| `LLM_MODEL` | `claude-opus-5-5` | Model id. |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-call timeout. |
| `LLM_MAX_RETRIES` | `2` | Validation-feedback retries. |
| `OUTPUT_LANGUAGE` | `vi` | Message language. |
| `LIVE_FETCH_ENABLED` | `false` | Same as `--live`. |
| `PROFILE_STORE_DIR` | `fixtures/profiles` | Provided-data lookup directory. |
| `MIN_GROUNDING_FACTS` | `2` | Sufficiency gate threshold. |
| `DEFAULT_MESSAGE_COUNT` | `10` | Target message count (5–10). |

### 7.3 Internal protocols

```text
ProfileSource.acquire(canonical_url) -> AcquisitionResult | None   # None = "not mine, try next"
LLMClient.describe_image(image_bytes, media_type, instructions) -> VisionResult
LLMClient.generate_structured(system, user, output_model) -> output_model instance  (raises LLMError)
Generator.generate(ledger, settings, feedback=None) -> EngagementDraft
Validator.validate(draft, ledger) -> list[Violation]
```

---

## 8. Compliance Design

- Live adapter: one GET with an honest User-Agent (`FacebookProfilerAgent/0.1 (+TES-3808 test)`, no browser
  spoofing); no cookies, no auth headers, no retries on 4xx, no proxy/IP rotation.
- Login wall / checkpoint / CAPTCHA markers → stop immediately and report `LOGIN_REQUIRED`.
- Images are only read from provided local files or URLs present in provided data/public meta; no crawling.
- Real-run outputs go to `runs/` (git-ignored); repo contains synthetic data only.
- `TECHNICAL LIMITATION` text is surfaced in `error_note` and `evidence.json` — never hidden.
