# Facebook Profiler Agent — TES-3808

CLI agent for customer care (CSKH). Given a Facebook profile URL and the profile data that can be legitimately
accessed, it:

1. builds a **fact-grounded customer profile**: every statement is a `FACT` (with its source), a labelled
   `INFERENCE`, or `UNKNOWN`;
2. writes **5–10 empathy rapport messages** in Vietnamese with **zero sales** content;
3. writes one **20:00 evening hook** grounded in a real fact.

The result is strict JSON, printed to stdout and written to `output.json`. A separate `evidence.json` lists the
fact behind every message.

```bash
pip install -r requirements.txt
python main.py --url "https://www.facebook.com/fixture.minh.anh"
```

> **Read first — technical limitation.** Facebook shows almost no profile content without logging in. This agent
> never logs in and never bypasses CAPTCHAs, privacy settings or anti-bot measures. A real test against
> facebook.com returned a login page (see `test_results.json`, case `live_facebook_attempt`). Profile data is
> therefore supplied as JSON (`--profile-file`, or the local profile store). The repository ships **synthetic**
> fixture personas for testing; no real person's data is included.

---

## 1. Requirements

- Python **3.11+** (developed and tested on 3.12.10, Windows 11)
- No API key needed for the default run. An Anthropic API key is **optional** and enables Claude for message
  writing and image description.

## 2. Installation

```bash
git clone <repository-url>
cd AI-PROFILER---CSKH
python -m venv .venv
```

Activate the virtual environment:

| Shell | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows cmd | `.venv\Scripts\activate.bat` |
| Git Bash | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

Then install the dependencies:

```bash
pip install -r requirements.txt
```

**Windows notes**

- **Long paths.** Clone into a short path such as `C:\src\AI-PROFILER---CSKH`. The `anthropic` SDK contains file
  names of about 90 characters, so a deeply nested clone can make `pip install` fail with
  `OSError ... Long Path support`. Alternatively, enable long paths in Windows.
- **PowerShell execution policy.** If `Activate.ps1` is blocked, either run
  `Set-ExecutionPolicy -Scope Process Bypass` first, or skip activation and call the interpreter directly:
  `.venv\Scripts\python.exe main.py --url "…"`.

## 3. Environment variables

Every variable is optional, so the agent runs without a `.env` file. To change settings, copy `.env.example` to
`.env` and edit it.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(unset)* | Enables Claude in `--mode auto`. Without it, the deterministic template generator is used. |
| `LLM_MODEL` | `claude-opus-5-5` | Claude model id. |
| `LLM_TIMEOUT_SECONDS` | `60` | Timeout per LLM call. |
| `LLM_MAX_RETRIES` | `2` | Retries with validator feedback before falling back to templates. |
| `OUTPUT_LANGUAGE` | `vi` | Language of generated messages. |
| `DEFAULT_MESSAGE_COUNT` | `10` | Target number of rapport messages (5–10). |
| `LIVE_FETCH_ENABLED` | `false` | Same as `--live` (see below). |
| `PROFILE_STORE_DIR` | `fixtures/profiles` | Directory of provided profile JSON files, matched by URL. |
| `MIN_GROUNDING_FACTS` | `2` | Minimum number of real facts besides the name required for `SUCCESS`. |

The API key is never logged or printed.

## 4. Configuration and CLI options

```text
python main.py --url URL [--profile-file FILE] [--output output.json] [--evidence evidence.json]
               [--mode auto|llm|deterministic] [--live] [--messages 5..10] [--verbose]
```

| Option | Meaning |
|---|---|
| `--url` | Facebook profile URL. Accepted forms: `facebook.com/<username>`, `m.`/`mbasic.`/`web.` hosts, `profile.php?id=<digits>`, `/people/<name>/<id>`. Tracking parameters are removed. |
| `--profile-file` | JSON file with legitimately obtained profile data for this URL (format: `fixtures/README.md`). The file's `facebook_url` must match `--url`. |
| `--mode` | `auto` (default): Claude if a key is set, otherwise templates. `llm`: requires a key. `deterministic`: templates only, no LLM calls. |
| `--live` | Opt-in. Sends **one** unauthenticated request with an honest User-Agent and reads only public `og:*` meta tags. Never logs in or retries. A login page is reported as a limitation. |
| `--messages` | Target number of rapport messages, 5–10. |
| `--verbose` | Writes pipeline-stage logs to **stderr**. stdout always contains only the JSON. |

## 5. Run

```bash
python main.py --url "https://www.facebook.com/fixture.minh.anh"
```

Other ready-made examples (all synthetic, listed in [`fixtures/README.md`](fixtures/README.md)):

```bash
python main.py --url "https://www.facebook.com/fixture.thu.ha"
```

```bash
python main.py --url "https://www.facebook.com/fixture.private.user"
```

To use your own legitimately obtained profile data:

```bash
python main.py --url "https://www.facebook.com/fixture.thu.ha" --profile-file fixtures/profiles/partial_thu_ha.json --output runs/thu_ha/output.json --evidence runs/thu_ha/evidence.json
```

To run the tests and the recorded final test run:

```bash
python -m pytest -q
```

```bash
python scripts/run_test_profiles.py
```

## 6. Example input

The minimal input is a URL. The profile data behind `fixture.minh.anh` is
[`fixtures/profiles/minh_anh.json`](fixtures/profiles/minh_anh.json) (excerpt):

```json
{
  "facebook_url": "https://www.facebook.com/fixture.minh.anh",
  "synthetic": true,
  "access": { "state": "PUBLIC", "note": "" },
  "display_name": "Nguyễn Minh Anh",
  "bio": "Mê cà phê sáng ☕ | Chạy bộ cuối tuần quanh Hồ Tây | Đang tập làm bánh mì sourdough",
  "public_info": { "work": ["Thiết kế đồ họa tại Studio Lá Xanh"], "interests": ["chạy bộ", "làm bánh", "cây cảnh trong nhà"], "current_city": "Hà Nội" },
  "public_posts": [{ "date": "2026-09-28", "text": "Hoàn thành 10km đầu tiên quanh Hồ Tây sáng nay, mệt nhưng vui!" }],
  "images": [{ "kind": "avatar", "alt_text": "Ảnh đại diện có vẻ cho thấy một người mặc đồ chạy bộ, đeo số áo, đứng cạnh vạch đích." }]
}
```

## 7. Example output

`SUCCESS` (deterministic mode, abridged; the full file is [`output.json`](output.json)):

```json
{
  "status": "SUCCESS",
  "facebook_url": "https://www.facebook.com/fixture.minh.anh",
  "profile_data": {
    "customer_name": "Nguyễn Minh Anh",
    "visual_context": "PROVIDED IMAGE DESCRIPTION: Ảnh đại diện có vẻ cho thấy một người mặc đồ chạy bộ, đeo số áo, đứng cạnh vạch đích.",
    "estimated_demographics": {
      "gender": "UNKNOWN",
      "estimated_age_range": "UNKNOWN",
      "apparent_lifestyle": "INFERENCE: day-to-day life appears to involve stated interests: chạy bộ; làm bánh; cây cảnh trong nhà, stated work: Thiết kế đồ họa tại Studio Lá Xanh (based on F5, F6, F7, F3)"
    }
  },
  "ethical_rapport": {
    "core_empathy_angle": "Quan tâm chân thành tới những điều bạn ấy tự chia sẻ công khai: …",
    "dialogue_sequence_10": [
      "Chào Nguyễn Minh Anh, mình rất vui được làm quen với bạn!",
      "Mình thấy bạn có nhắc đến sở thích chạy bộ. Điều gì khiến bạn gắn bó với chạy bộ vậy?",
      "Dạo này có điều gì nhỏ nhỏ khiến bạn thấy vui không?",
      "Bạn bắt đầu thích làm bánh từ khi nào vậy?",
      "…",
      "Rất vui được trò chuyện với bạn, hẹn sớm nói chuyện tiếp nhé!"
    ],
    "sales_mention_check": "ZERO_SALES_CONFIRMED"
  },
  "evening_cadence_20pm": {
    "trigger_time": "20:00",
    "evening_hook_message": "Chào buổi tối! Mình chợt nhớ tới điều bạn từng chia sẻ: “Hoàn thành 10km đầu tiên quanh Hồ Tây sáng nay, mệt nhưng vui!” …"
  }
}
```

Gender and age are `UNKNOWN` because this profile does not declare them. The agent never guesses them from names
or photos.

`PARTIAL_OR_PRIVATE` (private profile):

```json
{
  "status": "PARTIAL_OR_PRIVATE",
  "facebook_url": "https://www.facebook.com/fixture.private.user",
  "error_note": "PRIVATE_PROFILE: the profile is private; no public content is available to analyse. | Profile content is restricted to friends; nothing beyond the display name is publicly visible."
}
```

`evidence.json` (not part of the strict schema) records the access state, data source, synthetic flag, the full
fact ledger (`F1…Fn` with sources and FACT/INFERENCE status), the facts cited by each message, the angle, the
lifestyle and the hook, every LLM attempt and validator violation, and the technical limitations.

## 8. Error handling

stdout always contains exactly one valid JSON document, and `output.json` is always written.

| Situation | `status` | `error_note` starts with | Exit code |
|---|---|---|---|
| Missing / invalid URL, unknown option, bad `--messages` | `PARTIAL_OR_PRIVATE` | `INVALID_INPUT:` | 2 |
| Malformed `--profile-file`, or the file is for another URL | `PARTIAL_OR_PRIVATE` | `INVALID_INPUT:` | 2 |
| `--mode llm` without `ANTHROPIC_API_KEY` | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 2 |
| No accessible data (no file, not in store, `--live` off) | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 0 |
| `--live` hits a login wall / checkpoint | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 0 |
| Private profile | `PARTIAL_OR_PRIVATE` | `PRIVATE_PROFILE:` | 0 |
| Dead link (404 / "content isn't available") | `PARTIAL_OR_PRIVATE` | `NOT_FOUND:` | 0 |
| Network error / timeout / 403 / 429 / 5xx | `PARTIAL_OR_PRIVATE` | `UNREACHABLE:` | 0 |
| Fewer than 2 real facts besides the name, or no grounded draft possible | `PARTIAL_OR_PRIVATE` | `INSUFFICIENT_DATA:` | 0 |
| No public image | `SUCCESS` with `visual_context: "NOT_AVAILABLE: …"` | — | 0 |
| LLM refuses / times out / keeps violating rules | `SUCCESS` via the template generator (recorded in evidence) | — | 0 |
| Unexpected internal error | `PARTIAL_OR_PRIVATE` | `INTERNAL_ERROR:` | 1 |

## 9. Architecture overview

```text
CLI ─► input validation ─► data sources (profile file → profile store → opt-in live meta)
    ─► fact ledger (F1..Fn: FACT with source; missing fields → UNKNOWN)
    ─► visual context (provided alt text, or Claude vision → INFERENCE observations)
    ─► sufficiency gate (SUCCESS only with a name + ≥ 2 real facts)
    ─► demographics (self-declared only) + lifestyle (labelled INFERENCE)
    ─► engagement generation: Claude (structured output, must cite fact ids)
          └─ deterministic guardrails ─ violations → retry with feedback (≤ 2) → template generator
    ─► final guardrail check ─► strict JSON (stdout + output.json) + evidence.json
```

- **Zero hallucination by construction.** Generators may only cite ledger ids. The validator rejects:
  - unknown ids, INFERENCE ids and demographic ids;
  - numbers and names that are not in the cited facts;
  - presumptions such as "you must be tired after work";
  - sensitive-attribute terms;
  - neutral messages that make claims about the customer.
- **Zero sales.** The validator rejects Vietnamese and English commercial vocabulary, prices (`199k`, `1.500.000đ`,
  `20%`), URLs, phone numbers, e-mail addresses and hashtags. `ZERO_SALES_CONFIRMED` is written only after the
  final validation passes.
- **Provider isolation.** Only `app/llm/anthropic_client.py` imports the `anthropic` SDK; `app/sources/live_meta.py`
  is the only code that contacts Facebook.
- **AI is used only where needed:** image description and natural message writing. URL handling, data loading,
  demographics, the SUCCESS decision and all validation are deterministic code.

Details: [requirements.md](requirements.md) · [architecture.md](architecture.md) · [plan.md](plan.md) ·
[task.md](task.md) (implementation status, single source of truth) · [fixtures/README.md](fixtures/README.md).

```text
main.py                     entry point
app/cli.py, output.py       CLI, JSON output
app/pipeline.py             orchestration + error matrix
app/input.py                URL validation
app/sources/                profile file / store / live meta adapters
app/ledger.py               fact ledger + sufficiency gate
app/vision.py               visual context
app/intel.py                demographics + lifestyle
app/generation/             prompts, LLM generator, deterministic generator
app/guardrails.py           validators;  app/lexicons.py word lists
app/llm/                    LLM protocol, Claude adapter, fake client
fixtures/profiles/          synthetic test personas
tests/                      unit + integration tests (offline)
scripts/run_test_profiles.py  final test run → test_results.json
```

## 10. Known limitations

- **TECHNICAL LIMITATION: Facebook access.** Without logging in, Facebook returns a login page for profiles; one
  real attempt in `test_results.json` returned `LOGIN_REQUIRED`. The agent does not log in, use cookies, solve
  CAPTCHAs or rotate IPs, so real profile data must be supplied via `--profile-file` (for example exported with the
  customer's consent or collected manually from what is publicly visible). `--live` can read only public `og:*`
  meta tags. These are usually unavailable, and when present they contain at most a name, a short description and
  an image URL.
- **Test data is synthetic.** The 3+ representative runs in `test_results.json` use the fictional fixtures in
  `fixtures/profiles/`. No real person's data is committed.
- **Claude path not verified live in this environment.** No API key was available during development. The LLM
  generator, retries and fallback are covered by tests with a scripted fake client, and the request shape is checked
  against the SDK. A run with a key is recorded automatically by `python scripts/run_test_profiles.py` (case
  `llm_mode_public_rich`).
- **Rule-based guardrails.** Word lists and heuristics can miss paraphrased soft-selling or subtle claims, and the
  entity check only covers numbers and capitalised words. Review `evidence.json` before sending messages.
- **Template mode reads less naturally than Claude.** Messages are fully grounded but follow a fixed set of
  Vietnamese templates.
- **No scheduler and no sending.** `trigger_time: "20:00"` describes when the hook is meant to be sent. The agent
  never sends messages; an operator reviews and sends them.
- **Demographics are often `UNKNOWN`.** By design they come only from self-declared data, never from appearance or
  names.
