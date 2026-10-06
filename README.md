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
- No API key needed for the default run. An LLM key is **optional** and enables AI message writing and image
  description. Two providers are supported:
  - **Gemini.** Get a free key at https://aistudio.google.com/apikey; no billing is needed for the free tier.
  - **Claude.** Needs an Anthropic API key with billing enabled.

  To use Gemini, put the key in `.env`: `GEMINI_API_KEY=...`.

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
| `LLM_PROVIDER` | `auto` | `auto` uses Claude if `ANTHROPIC_API_KEY` is set, else Gemini if `GEMINI_API_KEY` is set. Set `anthropic` or `gemini` to force one provider. Without a key, the deterministic template generator is used. |
| `GEMINI_API_KEY` | *(unset)* | Google AI Studio key (free tier available). |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model id. |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-3.5-flash-lite` | Models tried in order when the primary is overloaded (503), out of quota (429), missing or timing out. `evidence.json` records the model that answered. |
| `ANTHROPIC_API_KEY` | *(unset)* | Anthropic key (requires billing). |
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

### Running on real profiles (with consent)

The brief asks for runs on at least 3 real Facebook profiles. The agent does not scrape Facebook, so real data is
entered by a person who has the profile owner's consent, for example your own profile or a friend who agrees. Only
copy what is publicly visible.

1. Create a fill-in file for each profile. Files are written to `runs/real/`, which is git-ignored:

   ```bash
   python scripts/new_profile.py --url "https://www.facebook.com/<username>"
   ```

2. Fill in `display_name`, `bio`, `public_info`, the latest public posts, and the profile picture. For the picture,
   write a short `alt_text` description, or set `path` to a saved image so the vision model describes it. The script
   prints these instructions.
3. Run them all at once:

   ```bash
   python scripts/run_test_profiles.py --profiles-dir runs/real
   ```

   Results go to `runs/test_results_real.json`, and each profile's output goes to `runs/real_run/<name>/`. The
   committed `test_results.json`, `output.json` and `evidence.json` are never touched in this mode. Publish real
   results only with the owners' consent. On the Gemini free tier, Google may use the data to improve its products.

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

`SUCCESS` in template mode (no API key), abridged. With a Gemini or Claude key, the messages are written by the model
and checked by the same guardrails. The committed [`output.json`](output.json) and the `test_results.json` cases come
from such an LLM run.



```json
{
  "status": "SUCCESS",
  "facebook_url": "https://www.facebook.com/fixture.minh.anh",
  "profile_data": {
    "customer_name": "Nguyễn Minh Anh",
    "visual_context": "MÔ TẢ ẢNH (từ dữ liệu được cung cấp): Ảnh đại diện có vẻ cho thấy một người mặc đồ chạy bộ, đeo số áo, đứng cạnh vạch đích.",
    "estimated_demographics": {
      "gender": "UNKNOWN",
      "estimated_age_range": "UNKNOWN",
      "apparent_lifestyle": "INFERENCE: đời sống thường ngày có vẻ gắn với sở thích: chạy bộ, làm bánh, cây cảnh trong nhà; công việc: Thiết kế đồ họa tại Studio Lá Xanh (dựa trên F5, F6, F7, F3)"
    }
  },
  "ethical_rapport": {
    "core_empathy_angle": "Trân trọng những niềm vui và nỗ lực mà bạn ấy tự chia sẻ: …",
    "dialogue_sequence_10": [
      "Chào Nguyễn Minh Anh! Mình vừa ghé thăm trang cá nhân của bạn, ấn tượng đầu tiên là tấm ảnh đại diện nhìn thật dễ mến.",
      "Đọc bài viết “Mẻ sourdough thứ 3, cuối cùng vỏ bánh cũng giòn 🥖” của bạn, mình thấy thật gần gũi. Lúc ấy bạn cảm thấy thế nào?",
      "Mình thấy bạn có niềm yêu thích với chạy bộ, nghe thôi đã thấy thật thú vị. Điều gì khiến bạn gắn bó với chạy bộ vậy?",
      "Dạo này có điều gì nhỏ nhỏ khiến bạn mỉm cười không?",
      "…",
      "Trò chuyện cùng bạn thật sự là niềm vui của mình. Chúc bạn một ngày thật nhẹ nhàng và nhiều niềm vui nhé!"
    ],
    "sales_mention_check": "ZERO_SALES_CONFIRMED"
  },
  "evening_cadence_20pm": {
    "trigger_time": "20:00",
    "evening_hook_message": "Buổi tối an lành nhé bạn! Mình chợt nhớ tới điều bạn từng chia sẻ: “Hoàn thành 10km đầu tiên quanh Hồ Tây sáng nay, mệt nhưng vui!” Khi nào thư thả, bạn kể mình nghe thêm nhé, mình luôn sẵn lòng lắng nghe."
  }
}
```

Gender and age are `UNKNOWN` here because this profile does not declare them and the fixture has no image file for
the vision model. With an API key and a profile picture, the agent adds a perceived estimate that is clearly
labelled, for example `INFERENCE: Nữ (ước lượng từ ảnh đại diện, độ tin cậy 0.85) [F13]` or
`INFERENCE: 25–35 tuổi (ước lượng từ ảnh đại diện, độ tin cậy 0.70) [F14]`. Self-declared values read like
`Nữ (tự khai báo trên trang cá nhân [F8])` and `29–30 tuổi (tính từ năm sinh tự khai báo 1996 [F9], tại năm 2026)`.
Self-declared data always wins, and the agent never guesses demographics from names.

`PARTIAL_OR_PRIVATE` (private profile):

```json
{
  "status": "PARTIAL_OR_PRIVATE",
  "facebook_url": "https://www.facebook.com/fixture.private.user",
  "error_note": "PRIVATE_PROFILE: Trang cá nhân bị khóa riêng tư, không có nội dung công khai để phân tích. | Nội dung trang cá nhân chỉ hiển thị với bạn bè; ngoài tên hiển thị không có gì công khai."
}
```

`evidence.json` (not part of the strict schema) records the access state, data source, synthetic flag, the full
fact ledger (`F1…Fn` with sources and FACT/INFERENCE status), the facts cited by each message, the angle, the
lifestyle and the hook, every LLM attempt and validator violation, and the technical limitations.

## 8. Error handling

Every human-readable text is Vietnamese, matching the brief. It is preceded by a fixed English code (`INVALID_INPUT:`,
`PRIVATE_PROFILE:`, `NOT_FOUND:`, `NO_IMAGE:`, `INSUFFICIENT_DATA:`, `UNREACHABLE:`, `INTERNAL_ERROR:`,
`TECHNICAL LIMITATION:`, plus `NOT_AVAILABLE:`, `INFERENCE:`, `UNKNOWN` inside fields) so other systems can branch on it.

stdout always contains exactly one valid JSON document, and `output.json` is always written.

| Situation | `status` | `error_note` starts with | Exit code |
|---|---|---|---|
| Missing / invalid URL, unknown option, bad `--messages` | `PARTIAL_OR_PRIVATE` | `INVALID_INPUT:` | 2 |
| Malformed `--profile-file`, or the file is for another URL | `PARTIAL_OR_PRIVATE` | `INVALID_INPUT:` | 2 |
| `--mode llm` without an LLM key (`ANTHROPIC_API_KEY` / `GEMINI_API_KEY`) | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 2 |
| No accessible data (no file, not in store, `--live` off) | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 0 |
| `--live` hits a login wall / checkpoint | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 0 |
| Private profile | `PARTIAL_OR_PRIVATE` | `PRIVATE_PROFILE:` | 0 |
| Dead link (404 / "content isn't available") | `PARTIAL_OR_PRIVATE` | `NOT_FOUND:` | 0 |
| Network error / timeout / 403 / 429 / 5xx | `PARTIAL_OR_PRIVATE` | `UNREACHABLE:` | 0 |
| Fewer than 2 real facts besides the name, or no grounded draft possible | `PARTIAL_OR_PRIVATE` | `INSUFFICIENT_DATA:` | 0 |
| No public image could be collected or read (brief §4) | `PARTIAL_OR_PRIVATE` | `NO_IMAGE:` | 0 |
| LLM refuses / times out / keeps violating rules | `SUCCESS` via the template generator (recorded in evidence) | — | 0 |
| Unexpected internal error | `PARTIAL_OR_PRIVATE` | `INTERNAL_ERROR:` | 1 |

## 9. Architecture overview

```text
CLI ─► input validation ─► data sources (profile file → profile store → opt-in live meta)
    ─► fact ledger (F1..Fn: FACT with source; missing fields → UNKNOWN)
    ─► visual context (provided alt text, or Claude vision → INFERENCE observations)
    ─► sufficiency gate (SUCCESS only with a name + ≥ 2 real facts + a readable public image)
    ─► demographics (self-declared, else labelled INFERENCE from the profile picture) + lifestyle (labelled INFERENCE)
    ─► engagement generation: Claude or Gemini (structured JSON output, must cite fact ids)
          └─ deterministic guardrails ─ violations → retry with feedback (≤ 2) → template generator
    ─► final guardrail check ─► strict JSON (stdout + output.json) + evidence.json
```

- **Zero hallucination by construction.** Generators may only cite ledger ids. The validator rejects:
  - unknown ids, INFERENCE ids and demographic ids;
  - numbers and names that are not in the cited facts;
  - presumptions such as "you must be tired after work";
  - sensitive-attribute terms;
  - neutral messages that make claims about the customer.
- **No brand, no product talk.** The brand **Dr.Bee** is rejected in any spelling (`Dr. Bee`, `DrBee`, `dr bee`,
  `Bác sĩ Bee`…), and so is its product domain: hair and scalp problems and hair-care products (`rụng tóc`, `da đầu`,
  `dầu gội`, `serum`, `hair loss`…). This holds even when the customer's own posts mention them. Generic beauty and
  pharma words (`tóc`, `mỹ phẩm`, `dược sĩ`…) are allowed only when the customer wrote them, for example a pharmacist's
  job title. The word lists live in `app/lexicons.py`.
- **Zero sales.** The validator rejects Vietnamese and English commercial vocabulary, prices (`199k`, `1.500.000đ`,
  `20%`), URLs, phone numbers, e-mail addresses and hashtags. `ZERO_SALES_CONFIRMED` is written only after the
  final validation passes.
- **Warm, grounded tone.** The first message greets the customer and mentions the profile picture when an image
  description exists. Messages honour what the customer shares, rather than asking them to confirm facts. The evening
  hook is a gentle wish around one real fact. Family topics are allowed only when a cited fact is about family, and
  "sau giờ làm việc" only when a work fact is cited. The LLM prompt carries a style guide from the brief, and the
  template generator follows the same tone.
- **Forms of address.** The agent writes "em" and calls the customer "chị" or "anh" when gender is self-declared
  (gender field or pronouns) or confidently perceived from the profile picture. Otherwise it uses the neutral
  "bạn" / "mình". The choice and its basis are recorded in `evidence.json`. Quoted customer text is never rewritten.
- **Provider isolation.** Only `app/llm/anthropic_client.py` imports the `anthropic` SDK, and only
  `app/llm/gemini_client.py` imports `google-genai`. Both implement the same `LLMClient` protocol.
  `app/sources/live_meta.py` is the only code that contacts Facebook.
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
- **Committed test data is synthetic.** The representative runs in `test_results.json` use the fictional fixtures in
  `fixtures/profiles/`, and no real person's data is committed. For the brief's runs on 3 real profiles, use the
  consent workflow in section 5 ("Running on real profiles"). Its results stay in `runs/` unless the owners agree to
  publish them.
- **LLM verification.** The Gemini path was verified live on 2026-10-06. Structured output worked, an overloaded
  primary model fell back to the next model, the guardrails rejected a first draft, and the model fixed it on the
  retry. The Claude path is covered by offline tests only, because the Anthropic API needs billing. On the free tier,
  Gemini models are often overloaded (HTTP 503), so a run can take a minute while the agent falls back to the next
  model. Set `GEMINI_MODEL` to a less busy model to avoid the wait.
- **Privacy on the Gemini free tier.** Google's pricing page states that free-tier content may be used to improve
  Google's products. Use the free tier only with synthetic or consented test data. For real customer data, use a
  paid tier or Claude.
- **Rule-based guardrails.** Word lists and heuristics can miss paraphrased soft-selling or subtle claims, and the
  entity check only covers numbers and capitalised words. Review `evidence.json` before sending messages.
- **Template mode reads less naturally than an LLM.** Messages are fully grounded but follow a fixed set of
  Vietnamese templates. With a Gemini or Claude key, messages are written by the model and checked by the same
  guardrails.
- **Subtle presumptions can slip through.** In a live Gemini run, a hook wished the customer an evening "bên giai
  điệu ukulele quen thuộc", mildly assuming what she would do tonight. Rule-based checks catch explicit patterns
  ("chắc hẳn", "tối nay bạn…", "mệt mỏi"), not every nuance. Review messages before sending.
- **No scheduler and no sending.** `trigger_time: "20:00"` describes when the hook is meant to be sent. The agent
  never sends messages; an operator reviews and sends them.
- **Demographics are estimates at best.** Self-declared data is used first. Otherwise the vision model may give a
  perceived gender presentation and an apparent age range from the profile picture. It does so only when exactly one
  person is visible, the gender confidence is at least 0.7, and the age range is at most 15 years wide with a
  confidence of at least 0.6. Estimates are labelled `INFERENCE` and can be wrong. They are never used as message
  topics. Without an API key or a profile picture, the fields stay `UNKNOWN`.
