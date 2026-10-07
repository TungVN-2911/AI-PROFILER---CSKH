# Facebook Profiler Agent — TES-3808

Agent dòng lệnh (CLI) hỗ trợ chăm sóc khách hàng (CSKH). Nhận URL Facebook hoặc dữ liệu profile đã trích xuất hợp lệ,
cố gắng lấy dữ liệu công khai từ Facebook (chi tiết ở [mục 10](#10-tiếp-cận-dữ-liệu-facebook-và-lộ-trình)), rồi sẽ:

1. dựng **hồ sơ khách hàng có căn cứ**: mỗi thông tin là `FACT` (kèm nguồn), `INFERENCE` (suy luận, có gắn nhãn)
   hoặc `UNKNOWN` (không biết);
2. viết **5–10 tin nhắn làm quen** bằng tiếng Việt, **không bán hàng** (zero sales);
3. viết **1 tin nhắn buổi tối gửi lúc 20:00** dựa trên một thông tin có thật.

Kết quả là một chuỗi JSON chặt chẽ, in ra màn hình (stdout) và ghi vào `output.json`. File `evidence.json` đi kèm ghi
lại mỗi tin nhắn dựa trên thông tin (fact) nào.

```bash
pip install -r requirements.txt
python main.py --url "https://www.facebook.com/fixture.minh.anh"
```

> **Đọc trước.** Khi `--url` không khớp dữ liệu có sẵn, agent thử lấy dữ liệu trực tiếp từ Facebook; cơ chế, cấu hình
> và giới hạn được mô tả ở [mục 10](#10-tiếp-cận-dữ-liệu-facebook-và-lộ-trình) *(phần thu thập dữ liệu do nhóm tự điền)*.
> Nếu Facebook không trả đủ dữ liệu công khai, dùng `--profile-file` với dữ liệu được cung cấp hợp lệ (có sự đồng ý),
> hoặc chấp nhận kết quả `PARTIAL_OR_PRIVATE`. Repo chỉ chứa persona **giả lập**; dữ liệu thật lưu dưới `runs/`
> (git-ignored).

---

## 1. Yêu cầu

- Python **3.11 trở lên** (phát triển và kiểm thử trên 3.12.10, Windows 11).
- Chạy mặc định **không cần API key**: khi đó tin nhắn được sinh bằng template. Có key thì AI sẽ viết tin nhắn và
  mô tả ảnh. Hỗ trợ hai nhà cung cấp:
  - **Gemini**: lấy key miễn phí tại https://aistudio.google.com/apikey, hạng miễn phí không cần thiết lập billing.
  - **Claude**: cần API key của Anthropic đã bật billing.

  Để dùng Gemini, ghi key vào file `.env`: `GEMINI_API_KEY=...`.

## 2. Cài đặt

```bash
git clone <repository-url>
cd AI-PROFILER---CSKH
python -m venv .venv
```

Kích hoạt môi trường ảo:

| Shell | Lệnh |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows cmd | `.venv\Scripts\activate.bat` |
| Git Bash | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

Sau đó cài thư viện:

```bash
pip install -r requirements.txt
```

**Lưu ý trên Windows**

- **Đường dẫn dài.** Hãy clone vào đường dẫn ngắn, ví dụ `C:\src\AI-PROFILER---CSKH`. SDK `anthropic` có tên file
  dài khoảng 90 ký tự, nên đặt repo quá sâu có thể làm `pip install` lỗi `OSError ... Long Path support`. Hoặc bật
  hỗ trợ đường dẫn dài trong Windows.
- **Execution policy của PowerShell.** Nếu `Activate.ps1` bị chặn, chạy trước `Set-ExecutionPolicy -Scope Process Bypass`,
  hoặc bỏ qua bước kích hoạt và gọi trực tiếp: `.venv\Scripts\python.exe main.py --url "…"`.

## 3. Biến môi trường

Mọi biến đều không bắt buộc, agent chạy được khi không có file `.env`. Muốn đổi cấu hình thì sao chép `.env.example`
thành `.env` rồi chỉnh sửa.

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto`: dùng Claude nếu có `ANTHROPIC_API_KEY`, nếu không thì dùng Gemini nếu có `GEMINI_API_KEY`. Đặt `anthropic` hoặc `gemini` để chọn cố định. Không có key thì dùng template. |
| `GEMINI_API_KEY` | *(trống)* | Key Google AI Studio (có hạng miễn phí). |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model Gemini chính. |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-3.5-flash-lite` | Các model dự phòng, thử lần lượt khi model chính quá tải (503), hết quota (429), không tồn tại hoặc quá thời gian chờ. `evidence.json` ghi model đã thực sự trả lời. |
| `ANTHROPIC_API_KEY` | *(trống)* | Key Anthropic (cần billing). |
| `LLM_MODEL` | `claude-opus-5-5` | Model Claude. |
| `LLM_TIMEOUT_SECONDS` | `60` | Thời gian chờ tối đa cho mỗi lời gọi LLM. |
| `LLM_MAX_RETRIES` | `2` | Số lần thử lại (kèm phản hồi lỗi) trước khi chuyển sang template. |
| `OUTPUT_LANGUAGE` | `vi` | Ngôn ngữ của tin nhắn. |
| `DEFAULT_MESSAGE_COUNT` | `10` | Số tin nhắn làm quen muốn sinh (5–10). |
| `LIVE_FETCH_ENABLED` | `false` | Liên quan việc thu thập dữ liệu trực tiếp từ Facebook — xem mục 10 (phần nhóm tự điền). |
| `PUBLIC_BROWSER_ENABLED` | `true` | Liên quan việc thu thập dữ liệu trực tiếp từ Facebook — xem mục 10 (phần nhóm tự điền). |
| `PROFILE_STORE_DIR` | `fixtures/profiles` | Thư mục chứa các file dữ liệu trang cá nhân, tra cứu theo URL. |
| `MIN_GROUNDING_FACTS` | `2` | Số thông tin thật tối thiểu (ngoài tên) để được `SUCCESS`. |

API key không bao giờ bị ghi log hay in ra.

## 4. Cấu hình và tùy chọn dòng lệnh

```text
python main.py --url URL [--profile-file FILE] [--output output.json] [--evidence evidence.json]
               [--mode auto|llm|deterministic] [--live|--no-live] [--messages 5..10] [--verbose]
```

| Tùy chọn | Ý nghĩa |
|---|---|
| `--url` | URL trang Facebook cá nhân. Chấp nhận `facebook.com/<username>`, các host `m.` / `mbasic.` / `web.`, `profile.php?id=<số>`, `/people/<tên>/<id>`. Tham số theo dõi (tracking) được loại bỏ. |
| `--profile-file` | File JSON chứa dữ liệu trang cá nhân lấy được hợp lệ (định dạng: `fixtures/README.md`). `facebook_url` trong file phải khớp với `--url`; khi truyền tùy chọn này, dữ liệu file được ưu tiên và không gọi nguồn live. |
| `--mode` | `auto` (mặc định): dùng LLM nếu có key, không thì dùng template. `llm`: bắt buộc có key. `deterministic`: chỉ dùng template, không gọi LLM. |
| `--live` / `--no-live` | Bật/tắt việc thu thập dữ liệu trực tiếp từ Facebook (xem mục 10). `--no-live` tắt mọi request tới Facebook. |
| `--messages` | Số tin nhắn làm quen muốn sinh, 5–10. |
| `--verbose` | In log từng bước ra **stderr**. stdout luôn chỉ chứa JSON. |

Khi không tìm thấy dữ liệu trong file hoặc profile store, agent thử lấy dữ liệu trực tiếp từ Facebook theo cấu hình
mô tả ở mục 10 (phần nhóm tự điền). Đây là best-effort: Facebook có thể chỉ trả trang đăng nhập hoặc không cung cấp
đủ dữ liệu; khi đó kết quả là `PARTIAL_OR_PRIVATE`. Không muốn tạo request mạng thì dùng `--no-live`.
Nếu không xác định được ảnh đại diện nhưng tìm được ảnh bìa có nhãn rõ ràng, ảnh bìa được dùng để mô tả ngữ cảnh
hình ảnh; ước lượng tuổi/giới tính vẫn chỉ dựa trên ảnh đại diện. Ảnh xem trước `og:image` không được coi mặc định là
ảnh đại diện hay ảnh bìa.

## 5. Chạy

```bash
python main.py --url "https://www.facebook.com/fixture.minh.anh"
```

Các ví dụ có sẵn khác (đều là dữ liệu giả lập, liệt kê trong [`fixtures/README.md`](fixtures/README.md)):

```bash
python main.py --url "https://www.facebook.com/fixture.thu.ha"
```

```bash
python main.py --url "https://www.facebook.com/fixture.private.user"
```

Dùng dữ liệu trang cá nhân do bạn tự cung cấp (lấy hợp lệ):

```bash
python main.py --url "https://www.facebook.com/fixture.thu.ha" --profile-file fixtures/profiles/partial_thu_ha.json --output runs/thu_ha/output.json --evidence runs/thu_ha/evidence.json
```

Chạy bộ test và lượt chạy kiểm thử tổng hợp (kết quả được lưu lại):

```bash
python -m pytest -q
```

```bash
python scripts/run_test_profiles.py
```

### Chạy với trang cá nhân thật (có sự đồng ý)

Đề bài yêu cầu chạy trên ít nhất 3 trang Facebook cá nhân thật. Có thể chạy từng URL trực tiếp; nếu Facebook không
hiển thị đủ dữ liệu công khai thì có thể bổ sung JSON profile do chủ trang cung cấp hoặc nhân viên nhập khi được phép.
Chỉ dùng dữ liệu cần thiết và không suy đoán trường còn thiếu.

1. Tạo file mẫu cho từng trang cá nhân. File được ghi vào `runs/real/`, thư mục này đã được git-ignore:

   ```bash
   python scripts/new_profile.py --url "https://www.facebook.com/<username>"
   ```

2. Điền `display_name`, `bio`, `public_info`, các bài đăng công khai gần nhất và ảnh đại diện. Với ảnh, ghi một mô tả
   ngắn vào `alt_text`, hoặc đặt `path` trỏ tới file ảnh đã lưu để mô hình AI tự mô tả. Script sẽ in hướng dẫn chi tiết.
3. Chạy tất cả cùng lúc:

   ```bash
   python scripts/run_test_profiles.py --profiles-dir runs/real
   ```

   Mỗi lượt chạy được lưu riêng trong `runs/real_run/<thời-điểm>/`, gồm báo cáo và output/evidence riêng cho từng
   profile; chạy lại không ghi đè kết quả cũ. Có thể truyền `--results FILE` nếu muốn tự chọn file báo cáo (file được
   chỉ định tường minh sẽ được cập nhật ở lần chạy sau). Ở chế độ này, các file `test_results.json`, `output.json`,
   `evidence.json` đang được commit không bao giờ bị động tới. Chỉ công bố kết quả thật khi chủ trang đồng ý. Ở hạng
   miễn phí của Gemini, Google có thể dùng dữ liệu để cải thiện sản phẩm.

Khi chạy trực tiếp với `--profile-file` hoặc nguồn Facebook công khai mà không truyền `--output`/`--evidence`, file
`output.json` và `evidence.json` ở thư mục hiện tại vẫn được cập nhật để giữ hành vi CLI; bản lưu riêng theo profile
và thời điểm chạy cũng được tạo trong `runs/real_runs/<profile-id>/<thời-điểm>/`. Dữ liệu thật lưu trong `runs/`
(đã git-ignore); chỉ giữ lại nếu phù hợp với sự đồng ý và chính sách lưu trữ của bạn.

## 6. Ví dụ đầu vào

Đầu vào tối thiểu là một URL. Dữ liệu đằng sau `fixture.minh.anh` nằm trong
[`fixtures/profiles/minh_anh.json`](fixtures/profiles/minh_anh.json) (trích đoạn):

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

## 7. Ví dụ đầu ra

`SUCCESS` ở chế độ template (không có API key), đã rút gọn. Khi có key Gemini hoặc Claude, tin nhắn do mô hình viết và
được kiểm tra bằng cùng bộ guardrail. File [`output.json`](output.json) và các trường hợp trong `test_results.json` đang
commit được tạo từ một lượt chạy có LLM như vậy.

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

Ở đây giới tính và độ tuổi là `UNKNOWN` vì trang cá nhân này không tự khai báo, và fixture không có file ảnh để mô
hình đọc. Khi có API key và ảnh đại diện, agent thêm một ước lượng được gắn nhãn rõ ràng, ví dụ
`INFERENCE: Nữ (ước lượng từ ảnh đại diện, độ tin cậy 0.85) [F13]` hoặc
`INFERENCE: 25–35 tuổi (ước lượng từ ảnh đại diện, độ tin cậy 0.70) [F14]`. Giá trị tự khai báo có dạng
`Nữ (tự khai báo trên trang cá nhân [F8])` và `29–30 tuổi (tính từ năm sinh tự khai báo 1996 [F9], tại năm 2026)`.
Dữ liệu tự khai báo luôn được ưu tiên, và agent không bao giờ đoán nhân khẩu học từ tên.

Khi mô hình thực sự đọc một ảnh (có file hoặc URL ảnh), `visual_context` ngoài phần mô tả còn kèm một câu
**"Ấn tượng tổng thể (AI, chưa kiểm chứng)"** — nhận xét ngắn về không khí/năng lượng/bối cảnh bức ảnh truyền tải.
Câu này được sàng lọc như mọi mô tả ảnh (loại nếu chạm thuộc tính nhạy cảm hoặc thông tin liên hệ) và không bao giờ
được đưa vào danh sách thông tin, nên không dùng để căn cứ tin nhắn hay chọn cách xưng hô.

`PARTIAL_OR_PRIVATE` (trang cá nhân bị khóa):

```json
{
  "status": "PARTIAL_OR_PRIVATE",
  "facebook_url": "https://www.facebook.com/fixture.private.user",
  "error_note": "PRIVATE_PROFILE: Trang cá nhân bị khóa riêng tư, không có nội dung công khai để phân tích. | Nội dung trang cá nhân chỉ hiển thị với bạn bè; ngoài tên hiển thị không có gì công khai."
}
```

`evidence.json` (không thuộc schema bắt buộc) ghi lại: trạng thái truy cập, nguồn dữ liệu, cờ dữ liệu giả lập, toàn bộ
danh sách thông tin (`F1…Fn` kèm nguồn và trạng thái FACT/INFERENCE), các thông tin được trích cho từng tin nhắn, góc
thấu cảm, lối sống và tin nhắn buổi tối, mọi lần thử của LLM và lỗi bị guardrail phát hiện, cùng các giới hạn kỹ thuật.

## 8. Xử lý lỗi

Mọi câu chữ người đọc được đều bằng tiếng Việt, đúng như đề bài. Phía trước là một mã cố định bằng tiếng Anh
(`INVALID_INPUT:`, `PRIVATE_PROFILE:`, `NOT_FOUND:`, `NO_IMAGE:`, `INSUFFICIENT_DATA:`, `UNREACHABLE:`, `INTERNAL_ERROR:`,
`TECHNICAL LIMITATION:`, cùng `NOT_AVAILABLE:`, `INFERENCE:`, `UNKNOWN` bên trong các trường) để hệ thống khác có thể
phân loại theo mã.

stdout luôn chứa đúng một chuỗi JSON hợp lệ, và `output.json` luôn được ghi.

| Tình huống | `status` | `error_note` bắt đầu bằng | Exit code |
|---|---|---|---|
| Thiếu / sai URL, tùy chọn không tồn tại, `--messages` sai | `PARTIAL_OR_PRIVATE` | `INVALID_INPUT:` | 2 |
| `--profile-file` hỏng, hoặc là dữ liệu của URL khác | `PARTIAL_OR_PRIVATE` | `INVALID_INPUT:` | 2 |
| `--mode llm` khi chưa có key (`ANTHROPIC_API_KEY` / `GEMINI_API_KEY`) | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 2 |
| Không có dữ liệu truy cập được (không có file, không có trong thư mục dữ liệu, không bật `--live`) | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 0 |
| `--live` gặp trang đăng nhập / xác minh | `PARTIAL_OR_PRIVATE` | `TECHNICAL LIMITATION:` | 0 |
| Trang cá nhân bị khóa | `PARTIAL_OR_PRIVATE` | `PRIVATE_PROFILE:` | 0 |
| Link chết (404 / "nội dung không khả dụng") | `PARTIAL_OR_PRIVATE` | `NOT_FOUND:` | 0 |
| Lỗi mạng / quá thời gian chờ / 403 / 429 / 5xx | `PARTIAL_OR_PRIVATE` | `UNREACHABLE:` | 0 |
| Ít hơn 2 thông tin thật ngoài tên, hoặc không viết được bản nháp có căn cứ | `PARTIAL_OR_PRIVATE` | `INSUFFICIENT_DATA:` | 0 |
| Không thu thập hoặc không đọc được ảnh công khai nào (đề bài mục 4) | `PARTIAL_OR_PRIVATE` | `NO_IMAGE:` | 0 |
| LLM từ chối / quá thời gian chờ / liên tục vi phạm luật | `SUCCESS` nhờ bộ sinh template (có ghi trong evidence) | — | 0 |
| Lỗi nội bộ ngoài dự kiến | `PARTIAL_OR_PRIVATE` | `INTERNAL_ERROR:` | 1 |

## 9. Tổng quan kiến trúc

```text
CLI ─► kiểm tra đầu vào ─► nguồn dữ liệu (file profile → thư mục dữ liệu → thu thập trực tiếp từ Facebook nếu bật --live, xem mục 10)
    ─► danh sách thông tin F1..Fn (FACT kèm nguồn; trường thiếu → UNKNOWN)
    ─► mô tả hình ảnh (alt_text được cung cấp, hoặc mô hình đọc ảnh → quan sát dạng INFERENCE)
    ─► ngưỡng đủ dữ liệu (SUCCESS chỉ khi có tên + ≥ 2 thông tin thật + một ảnh công khai đọc được)
    ─► nhân khẩu học (tự khai báo, nếu không thì INFERENCE ước lượng từ ảnh đại diện) + lối sống (INFERENCE)
    ─► sinh tin nhắn: Gemini hoặc Claude (JSON có cấu trúc, bắt buộc trích ID thông tin)
          └─ guardrail tất định ─ vi phạm → thử lại kèm phản hồi lỗi (≤ 2 lần) → bộ sinh template
    ─► kiểm tra guardrail lần cuối ─► JSON chặt chẽ (stdout + output.json) + evidence.json
```

- **Không bịa đặt ngay từ thiết kế.** Bộ sinh tin nhắn chỉ được trích các ID có trong danh sách thông tin. Guardrail
  từ chối:
  - ID không tồn tại, ID của thông tin suy luận (INFERENCE) và ID nhân khẩu học;
  - con số, tên riêng không có trong thông tin được trích;
  - câu giả định hoàn cảnh của khách, như "chắc bạn vừa đi làm về mệt lắm";
  - từ ngữ về thuộc tính nhạy cảm;
  - tin nhắn trung tính nhưng lại khẳng định điều gì đó về khách.
- **Giảm lộ dữ liệu và suy diễn.** Email, số điện thoại và URL bị loại khỏi fact ledger trước khi vào prompt/evidence;
  metric người theo dõi được ghi riêng nhưng không dùng làm chủ đề trò chuyện hoặc suy luận lối sống. Metadata nhận diện
  rõ Page chính thức sẽ trả `UNSUPPORTED_PROFILE_TYPE:` thay vì tạo kịch bản nhắn riêng. Tối đa một tin trong chuỗi được
  tập trung vào quan sát ảnh; giới tính/đại từ ước lượng từ ảnh không quyết định cách xưng hô.
- **Chỉ là bản nháp.** `SUCCESS` nghĩa là bản nháp qua kiểm tra tự động, không phải đã được người duyệt hay đã gửi.
  `evidence.json` luôn ghi `requires_human_review: true`; chưa có tích hợp gửi Messenger hoặc lịch gửi 20:00.
- **Không nhắc thương hiệu, không nói chuyện sản phẩm.** Thương hiệu **Dr.Bee** bị chặn ở mọi cách viết (`Dr. Bee`,
  `DrBee`, `dr bee`, `Bác sĩ Bee`…), cùng toàn bộ mảng sản phẩm: vấn đề tóc, da đầu và sản phẩm chăm sóc tóc
  (`rụng tóc`, `da đầu`, `dầu gội`, `serum`, `hair loss`…), kể cả khi chính khách nhắc đến trong bài đăng. Các từ chung
  về làm đẹp và dược (`tóc`, `mỹ phẩm`, `dược sĩ`…) chỉ được dùng khi chính khách viết ra, ví dụ nghề nghiệp là dược sĩ.
  Danh sách từ nằm trong `app/lexicons.py`.
- **Zero sales.** Guardrail từ chối từ ngữ thương mại tiếng Việt và tiếng Anh, giá tiền (`199k`, `1.500.000đ`, `20%`),
  URL, số điện thoại, email và hashtag. `ZERO_SALES_CONFIRMED` chỉ được ghi sau khi lần kiểm tra cuối cùng đạt.
- **Giọng văn ấm áp, có căn cứ.** Tin đầu tiên chào khách và nhắc tới ảnh đại diện khi có mô tả ảnh. Mọi diễn giải phải
  giữ đúng ý và ngữ cảnh của fact; không suy rộng thành cảm xúc, sự kiện, quan hệ hay hoàn cảnh hiện tại. Câu buổi tối
  chỉ gợi lại một fact đã nêu và mời khách chia sẻ thêm, không giả định khách đang ở cùng gia đình, ở nhà hay vừa tan
  làm. Các cụm placeholder/nội dung lỗi như “lần thứ n” bị từ chối; tin nhắn vẫn cần nhân viên đọc lại trước khi dùng.
- **Cách xưng hô.** Agent chỉ xưng "em" và gọi khách là "chị" hoặc "anh" khi có giới tính/đại từ tự khai báo phù hợp.
  Ước lượng từ ảnh không dùng để quyết định cách xưng hô; khi thiếu căn cứ, dùng "bạn" / "mình". Lựa chọn và căn cứ
  được ghi trong `evidence.json`. Lời trích của khách không bao giờ bị sửa.
- **Tách biệt nhà cung cấp.** Chỉ `app/llm/anthropic_client.py` import SDK `anthropic`, chỉ `app/llm/gemini_client.py`
  import `google-genai`. Cả hai cùng hiện thực interface `LLMClient`. Chỉ `app/sources/` có collector liên lạc với
  Facebook (chi tiết ở mục 10).
- **Chỉ dùng AI ở nơi cần thiết:** mô tả ảnh và viết tin nhắn tự nhiên. Kiểm tra URL, đọc dữ liệu, nhân khẩu học,
  quyết định SUCCESS và toàn bộ việc kiểm tra đều là code tất định.

Tài liệu chi tiết (tiếng Anh): [requirements.md](requirements.md) · [architecture.md](architecture.md) ·
[plan.md](plan.md) · [task.md](task.md) (trạng thái triển khai) · [fixtures/README.md](fixtures/README.md).

```text
main.py                       điểm vào chương trình
app/cli.py, output.py         dòng lệnh, ghi JSON
app/pipeline.py               điều phối các bước + bảng xử lý lỗi
app/input.py                  kiểm tra URL
app/sources/                  nguồn dữ liệu: file / profile store / trình duyệt và metadata công khai
app/ledger.py                 danh sách thông tin + ngưỡng đủ dữ liệu
app/vision.py                 mô tả hình ảnh
app/intel.py                  nhân khẩu học, lối sống, cách xưng hô
app/generation/               prompt, bộ sinh dùng LLM, bộ sinh template
app/guardrails.py             bộ kiểm tra;  app/lexicons.py danh sách từ
app/llm/                      interface LLM, adapter Claude, adapter Gemini, client giả lập cho test
fixtures/profiles/            các persona giả lập để thử nghiệm
tests/                        test đơn vị + tích hợp (offline)
scripts/new_profile.py        tạo file mẫu cho trang cá nhân thật (có đồng ý)
scripts/run_test_profiles.py  lượt chạy kiểm thử → test_results.json
```

## 10. Tiếp cận dữ liệu Facebook và lộ trình

> **Phần này do nhóm tự điền.** Hãy mô tả cách agent lấy dữ liệu trực tiếp từ Facebook:
> - cơ chế thu thập (trình duyệt/Selenium; cookie hoặc phiên đăng nhập nếu có — nêu rõ nguồn cookie và cách lưu/bảo vệ);
> - các biến `PUBLIC_BROWSER_ENABLED`, `LIVE_FETCH_ENABLED` và cờ `--live` / `--no-live` làm gì;
> - hành vi khi gặp login wall / checkpoint / CAPTCHA, và khi nào trả `PARTIAL_OR_PRIVATE`;
> - việc tuân thủ điều khoản Meta về thu thập tự động và yêu cầu quyền riêng tư/đồng ý
>   (Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15, hiệu lực 01/01/2026).
>
> <!-- TODO (nhóm điền): mô tả cơ chế thu thập dữ liệu Facebook ở đây. -->

Khi URL không trả đủ dữ liệu, dùng dữ liệu được cung cấp hợp lệ qua `--profile-file` (khách tự chia sẻ, hoặc nhân viên
chép phần công khai khi có sự đồng ý). Lớp nguồn dữ liệu tách riêng trong `app/sources/`, nên thêm nguồn mới — ví dụ
Messenger Platform khi vận hành thật — chỉ là thêm một adapter; danh sách thông tin, mô tả ảnh, sinh tin nhắn và
guardrail giữ nguyên.

### Lộ trình để thay thế hoàn toàn đội CSKH

Bài test dừng ở bước tạo kịch bản; nhân viên xem lại rồi gửi. Để agent tự vận hành, cần thêm:

1. **Nhận và gửi tin qua Messenger** (webhook và Send API của Fanpage). Mọi tin vẫn đi qua guardrail hiện có trước khi gửi.
2. **Hội thoại nhiều lượt.** Lưu lịch sử theo từng khách; điều khách tự kể được thêm vào danh sách thông tin như FACT
   có nguồn.
3. **Chuyển cho Dược sĩ** khi khách tự hỏi về tóc hoặc sản phẩm, kèm tóm tắt hồ sơ và lịch sử trò chuyện.
4. **Tin nhắn 20:00 hằng ngày** bằng bộ lập lịch theo giờ Việt Nam, mỗi ngày một chủ đề khác. Ràng buộc của Meta: Page
   chỉ được chủ động nhắn trong vòng 24 giờ kể từ tin cuối của khách. Ngoài khung đó, khách phải đồng ý nhận tin định kỳ
   (Marketing Messages), nếu không thì không được gửi.

## 11. Giới hạn đã biết

- **TECHNICAL LIMITATION: truy cập Facebook.** Facebook có thể trả về login/checkpoint/CAPTCHA hoặc nội dung hạn chế,
  nên việc lấy dữ liệu trực tiếp là best-effort. Cơ chế thu thập và giới hạn được mô tả ở mục 10 (phần nhóm tự điền).
  Khi dữ liệu công khai không được trả về, dùng `--profile-file` làm đầu vào hợp lệ hoặc xem kết quả
  `PARTIAL_OR_PRIVATE`.
- **Dữ liệu test được commit là giả lập.** Các trường hợp trong `test_results.json` dùng persona hư cấu trong
  `fixtures/profiles/`, không có dữ liệu người thật nào được commit. Để chạy trên 3 trang cá nhân thật như đề bài, dùng
  quy trình có sự đồng ý ở mục 5. Kết quả nằm trong `runs/` trừ khi chủ trang đồng ý công bố.
- **Kiểm chứng LLM.** Nhánh Gemini đã được kiểm chứng thật ngày 2026-10-06: output có cấu trúc chạy đúng, model chính bị
  quá tải thì tự chuyển sang model dự phòng, guardrail loại bản nháp đầu và model sửa ở lần thử lại. Nhánh Claude mới
  chỉ được kiểm chứng bằng test offline, vì API Anthropic cần billing. Ở hạng miễn phí, Gemini thường quá tải (HTTP 503)
  nên một lượt chạy có thể mất khoảng một phút để chuyển sang model dự phòng; đặt `GEMINI_MODEL` sang model ít bận hơn
  để tránh phải chờ.
- **Quyền riêng tư ở hạng miễn phí của Gemini.** Trang giá của Google ghi rằng dữ liệu gửi lên ở hạng miễn phí có thể
  được dùng để cải thiện sản phẩm của Google. Chỉ dùng hạng miễn phí với dữ liệu giả lập hoặc dữ liệu thử nghiệm đã có
  sự đồng ý. Với dữ liệu khách hàng thật, dùng hạng trả phí hoặc Claude.
- **Guardrail dựa trên luật.** Danh sách từ và quy tắc có thể bỏ sót kiểu bán hàng diễn đạt vòng vo hay những khẳng
  định tinh tế, và phần kiểm tra thực thể chỉ bắt số và từ viết hoa. Hãy xem `evidence.json` trước khi gửi tin.
- **Chế độ template kém tự nhiên hơn LLM.** Tin nhắn có căn cứ đầy đủ nhưng theo một bộ mẫu câu cố định. Khi có key
  Gemini hoặc Claude, mô hình viết tin nhắn và cùng bộ guardrail kiểm tra.
- **Giả định tinh tế vẫn có thể lọt qua.** Trong một lượt chạy Gemini thật, tin nhắn buổi tối chúc khách một buổi tối
  "bên giai điệu ukulele quen thuộc", ngầm giả định tối nay khách sẽ chơi đàn. Bộ luật bắt được các mẫu rõ ràng
  ("chắc hẳn", "tối nay bạn…", "mệt mỏi") nhưng không bắt được mọi sắc thái. Hãy đọc lại tin nhắn trước khi gửi.
- **Chưa có lịch gửi và chưa tự gửi tin.** `trigger_time: "20:00"` chỉ cho biết thời điểm nên gửi tin nhắn buổi tối.
  Agent không tự gửi tin; nhân viên xem lại rồi gửi. Lộ trình để tự gửi ở mục 10.
- **Nhân khẩu học chỉ là ước lượng.** Dữ liệu tự khai báo được dùng trước. Nếu không có, mô hình đọc ảnh được yêu cầu
  trả về ấn tượng giới tính biểu hiện và khoảng tuổi khi ảnh đại diện cho thấy rõ một người; kết quả chỉ được giữ khi
  đạt ngưỡng tin cậy (giới tính từ 0.7, tuổi từ 0.6) và khoảng tuổi rộng tối đa 15 năm. Ảnh phong cảnh, ảnh nhóm, ảnh
  không rõ người, ảnh lỗi hoặc không đủ tin cậy sẽ vẫn là `UNKNOWN`—không suy đoán từ tên hay cảnh vật. Mỗi ước lượng
  được gắn nhãn `INFERENCE`, có nguồn/độ tin cậy trong `evidence.json`, có thể sai và không dùng để chọn cách xưng hô
  hay làm chủ đề tin nhắn. Cần có API key và ảnh đại diện tải/đọc được.
