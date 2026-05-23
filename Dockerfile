# Sử dụng Python phiên bản chính thức làm nền tảng
FROM python:3.10-slim

# Đặt thư mục làm việc trong container
WORKDIR /app

# Sao chép file danh sách thư viện vào trước để tận dụng cache
COPY requirements.txt .

# Cài đặt các thư viện cần thiết
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn của bot vào container
COPY . .

# Lệnh để khởi chạy bot (Thay Main.py thành file chạy chính của bạn nếu viết thường)
CMD ["python", "Main.py"]