import undetected_chromedriver as uc
import time

options = uc.ChromeOptions()
# Giữ nguyên đường dẫn profile trùng với code dự án của bạn
options.add_argument(r"--user-data-dir=./storage/selenium_profile") 

driver = uc.Chrome(options=options)
driver.get("https://facebook.com")

print("HÃY ĐĂNG NHẬP THỦ CÔNG TRÊN TRÌNH DUYỆT VÀ VƯỢT 2FA (NẾU CÓ)...")
# Cho bạn 2 phút để tự gõ tài khoản, mật khẩu, nhập mã 2FA và bấm "Nhớ trình duyệt"
time.sleep(120) 

driver.quit()
print("Đã lưu phiên đăng nhập thành công!")
