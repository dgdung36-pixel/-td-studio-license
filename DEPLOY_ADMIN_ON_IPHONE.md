# Trong Dung Studio — Triển khai License Server + Web Admin (Build51)

**Đây là source có workflow triển khai, không phải một server/website đã lên mạng.** Bạn cần tài khoản GitHub, tài khoản hosting Python (ví dụ Render), và **PostgreSQL bền vững**. Làm hoàn toàn bằng Safari trên iPhone được; GitHub Actions dùng runner riêng để build.

## 1. Đưa source vào repo GitHub

1. Mở repo bạn muốn dùng (ví dụ `aovmodup`) trong Safari.
2. Đưa **các thư mục và tệp nằm bên trong ZIP** vào **gốc repo**, không để thừa một lớp tên thư mục ZIP. Các tệp bắt buộc phải nằm đúng: `.github/workflows/deploy-admin-pages.yml`, `WebAdmin/index.html`, `OnlineService/app.py`, `render.yaml`.
3. Giữ workflow build iOS `.github/workflows/build-ios-public-v1.2.yml`; workflow Pages mới chạy độc lập.
4. Vì trình tải file GitHub bằng giao diện có giới hạn, bạn có thể upload qua git trên máy tính hoặc GitHub web UI. Không upload Admin token, database password, tệp `.env` hoặc key plaintext.

## 2. Tạo database bền vững

- Tạo PostgreSQL tại Supabase (hoặc Postgres managed phù hợp). Lấy **kết nối phía server** (Postgres connection string) và đặt vào biến `DATABASE_URL` trên Render; KHÔNG đưa vào Github Pages, GitHub Actions vars, repo hoặc app.
- Bảo đảm kết nối hợp lệ cho psycopg (đặc biệt với hosting IPv4-only, có thể cần chế độ pooler theo hướng dẫn của nhà cung cấp). Các chi tiết cấu hình/giá có thể thay đổi theo nhà cung cấp.
- Cần kế hoạch sao lưu và phục hồi. Database dùng cho key; mất DB là mất trạng thái key/thiết bị/phiên.
- Render free Postgres **không phù hợp cho lâu dài**: theo tài liệu Render, database free hết hạn sau **30 ngày**, sau đó dữ liệu có thể bị xóa. Đừng nhầm gói web service free với database có lưu trữ dài hạn.

## 3. Triển khai License Server FastAPI trên Render

1. Vào https://dashboard.render.com → New → Blueprint → kết nối đúng repo.
2. Chọn Blueprint từ file `render.yaml` ở gốc. Nó tạo một web service `trong-dung-studio-license` với `rootDir=OnlineService`.
3. Điền các **environment variables riêng trên Render**:
   - `DATABASE_URL` = Postgres connection string an toàn, bền vững.
   - `LICENSE_ADMIN_TOKEN` = chuỗi bí mật ngẫu nhiên **ít nhất 32 ký tự**, khác hoàn toàn key cấp cho người dùng. Tạo bằng password manager hoặc `python3 -c 'import secrets; print(secrets.token_urlsafe(42))'`. Giữ riêng, không gửi cho người dùng.
   - `ADMIN_ALLOWED_ORIGINS` = `https://USERNAME.github.io` (thay USERNAME bằng GitHub username). Không có đường dẫn repo phía sau; nếu dùng custom domain thì ghi origin custom domain đó.
   - `APP_ENV` đã là `production`; `ACCESS_LOG_RETENTION_DAYS` mặc định `30`.
4. Deploy; mở `https://TÊN-SERVICE.onrender.com/health` và `https://TÊN-SERVICE.onrender.com/v1/license/status`. Bạn cần thấy `ready: true` ở endpoint status. Nếu không, kiểm tra env và PostgreSQL.
5. **Không dùng Admin token hoặc credentials trong GitHub Actions**. Chúng chỉ thuộc về backend và cá nhân quản trị.

`render.yaml` chọn web service free chỉ để thử nghiệm; dịch vụ này có thể ngủ khi ít hoạt động, khiến xác thực key chậm hoặc tạm thất bại. Để phục vụ người dùng liên tục, dùng hosting và Postgres phù hợp với mức độ tin cậy cần thiết.

## 4. Tự xuất bản web Admin qua GitHub Actions + GitHub Pages

1. Trong repo → **Settings → Secrets and variables → Actions → Variables**, thêm `AOV_LICENSE_SERVER_URL` = `https://TÊN-SERVICE.onrender.com` (**chỉ origin HTTPS**). Đây là URL công khai, không phải secret.
2. Repo → **Settings → Pages → Build and deployment → Source = GitHub Actions**.
3. Repo → **Actions → TD Studio Build51 - Deploy Admin to GitHub Pages → Run workflow** (branch `main`). Hoặc push thay đổi trong `WebAdmin/` sẽ tự chạy.
4. Khi workflow xanh, mở liên kết trong workflow hoặc tại `https://USERNAME.github.io/REPO/admin/`. Địa chỉ có thể khác nếu dùng domain riêng.
5. Dán `LICENSE_ADMIN_TOKEN` vào ô bí mật và chọn **Kết nối**. Server sẽ kiểm tra token; nếu sai, trang không cho truy cập API.
6. Bạn có thể tạo key, đặt thời hạn/số thiết bị, sao chép key mới, đổi key, thu hồi/khôi phục, xóa key, gỡ thiết bị, xem/xóa IP log.

**Không bật wildcard CORS** (`*`), không công khai Admin token, không gắn Admin token vào URL, HTML, JS, biến Actions hay IPA. GitHub Pages là site công khai, nhưng mọi dữ liệu và thao tác nhạy cảm luôn nằm sau API có xác thực trên backend.

## 5. Nối app iOS và build IPA

Workflow iOS hiện có **khác** với workflow Pages. Cùng dùng biến `AOV_LICENSE_SERVER_URL`; app sẽ hỏi key và xác thực với backend khi chạy.

Repo → Actions → workflow `AOV MOD UP V3.0 Build50 - License IPA & QA` → Run workflow. Workflow hiện tạo IPA **chưa ký**. Bạn cần ký theo cách phân phối IPA của mình.

Không nên phát hành khi chưa test từ thiết bị thật: nhập key đúng/sai, revoke, rotate, giới hạn thiết bị, mất mạng và kiểm tra iOS app kết nối HTTPS.

## 6. Xử lý lỗi thường gặp

| Lỗi | Cách kiểm tra |
|---|---|
| Trang Pages 404 | `Settings → Pages` phải dùng GitHub Actions, workflow deploy phải thành công, kiểm tra đường dẫn `/admin/` |
| Web có giao diện nhưng không đăng nhập được | Kiểm tra `AOV_LICENSE_SERVER_URL`, `ADMIN_ALLOWED_ORIGINS` (origin không có repo path), HTTPS, Render running, DB kết nối và token |
| HTTP 401 | Admin token sai; kiểm tra `LICENSE_ADMIN_TOKEN` chỉ trên Render |
| HTTP 503 / server không start | Thiếu hoặc lỗi `DATABASE_URL`, Admin token ngắn hơn 32, PostgreSQL không kết nối được |
| IP là proxy | Mặc định backend tin IP peer; chỉ khai báo `TRUSTED_PROXY_CIDRS` sau khi xác minh proxy thực tế, không tin header tùy ý |
| IPA không chạy | Kiểm tra workflow iOS, file IPA unsigned và ký ứng dụng. Web deploy thành công KHÔNG có nghĩa IPA đã build |
| Key tự mất sau redeploy | Database đang dùng tệp SQLite trên hệ thống ephemeral hoặc database free hết hạn — phải dùng PostgreSQL bền vững |

## 7. Bảo mật / quyền riêng tư

- IP và thời điểm xác thực được ghi cho vận hành, chống lạm dụng và kiểm tra license. Người dùng phải được thông báo, không thu GPS hoặc dữ liệu file MOD.
- Mặc định xóa log 30 ngày theo cơ chế cleanup khi có request; không đảm bảo thời điểm xóa chính xác nếu server không nhận request. Có nút xóa log thủ công trong Admin.
- IP không phải định danh chắc chắn và không suy ra địa chỉ chính xác.
- Khi triển khai công khai, kiểm tra yêu cầu pháp lý/quyền riêng tư áp dụng tại nơi bạn và người dùng hoạt động.
