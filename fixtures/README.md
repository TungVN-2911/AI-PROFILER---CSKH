# Dữ liệu mẫu (fixtures)

Mọi trang cá nhân ở đây đều là **persona giả lập** (`"synthetic": true`). Tên, tổ chức, bài đăng và ID số đều là hư
cấu, được viết ra để thử nghiệm; chúng không mô tả người thật và không được thu thập từ Facebook. Các username
`fixture.*` và số trong `profile.php?id=` chỉ là giá trị giữ chỗ; agent không bao giờ liên lạc với Facebook cho các URL
này, trừ khi truyền `--live` một cách tường minh.

Agent tra cứu `fixtures/profiles/*.json` theo `facebook_url` đã chuẩn hóa (đổi thư mục bằng `PROFILE_STORE_DIR`), nên
có thể chạy trực tiếp từng URL dưới đây:

```bash
python main.py --url "https://www.facebook.com/fixture.minh.anh"
```

| File | URL | Tình huống | Kết quả mong đợi |
|---|---|---|---|
| `minh_anh.json` | `https://www.facebook.com/fixture.minh.anh` | Trang công khai đầy đủ: tiểu sử, công việc, học vấn, 3 sở thích, thành phố, 3 bài đăng, mô tả ảnh đại diện | `SUCCESS`, 10 tin nhắn, `MÔ TẢ ẢNH (từ dữ liệu được cung cấp)`, giới tính/độ tuổi `UNKNOWN` |
| `no_image_quoc_bao.json` | `https://www.facebook.com/fixture.quoc.bao` | Trang công khai đầy đủ nhưng không có ảnh nào | `PARTIAL_OR_PRIVATE`, `NO_IMAGE:` (đề bài mục 4: không thu thập được ảnh) |
| `declared_khanh_linh.json` | `https://www.facebook.com/fixture.khanh.linh` | Tự khai báo giới tính, pronouns và năm sinh | `SUCCESS`, giới tính/độ tuổi được suy ra và gắn ID thông tin; tin nhắn xưng "chị" / "em" |
| `profile_id_variant.json` | `https://www.facebook.com/profile.php?id=100000000000042` | Dạng URL số `profile.php?id=` | `SUCCESS` |
| `partial_thu_ha.json` | `https://www.facebook.com/fixture.thu.ha` | Truy cập `PARTIAL`: chỉ có tên + tiểu sử + mô tả ảnh đại diện (đúng 2 thông tin dùng được) | `SUCCESS` với chuỗi tin ngắn hơn (7 tin nhắn) |
| `name_only.json` | `https://www.facebook.com/fixture.name.only` | Công khai nhưng chỉ có tên hiển thị | `PARTIAL_OR_PRIVATE`, `INSUFFICIENT_DATA:` |
| `private_user.json` | `https://www.facebook.com/fixture.private.user` | Trang cá nhân bị khóa | `PARTIAL_OR_PRIVATE`, `PRIVATE_PROFILE:` |
| `dead_link.json` | `https://www.facebook.com/fixture.dead.link` | Tài khoản đã xóa / link chết | `PARTIAL_OR_PRIVATE`, `NOT_FOUND:` |

URL nào không có fixture (và không dùng `--profile-file` / `--live`) sẽ trả về `PARTIAL_OR_PRIVATE` kèm ghi chú
`TECHNICAL LIMITATION:`.

## Định dạng

Mọi trường trừ `facebook_url` đều không bắt buộc; trường thiếu hoặc để trống được ghi
nhận là `UNKNOWN` và không bao giờ bị tự điền. Khóa không xác định bị từ chối. `access.state` (`PUBLIC`, `PARTIAL`,
`PRIVATE`, `LOGIN_REQUIRED`, `NOT_FOUND`, `UNREACHABLE`) cho phép một fixture mô phỏng trang bị giới hạn hoặc link chết
mà không cần truy cập mạng; các trường dữ liệu trang cá nhân bị bỏ qua trừ khi trạng thái là `PUBLIC` hoặc `PARTIAL`.
