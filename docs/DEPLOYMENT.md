# TX3 Remote Management Platform - Hướng dẫn triển khai

## Yêu cầu hệ thống

### Management Server
- Linux (Ubuntu 22.04+ / Debian 12+)
- Python 3.11+
- PostgreSQL 15+
- WireGuard
- RAM: 2GB+, Disk: 20GB+

### Windows Manager (TX3 Manager.exe)
- Windows 10/11 (64-bit)
- Flutter SDK 3.29+ (để build)
- WireGuard for Windows

### Android Box
- Amlogic S905W, RAM 2GB
- ROM đã root (ROM Builder v1.0.1)
- Có Internet (Ethernet hoặc Wi-Fi)

---

## Phase 1: Triển khai Server

### 1.1 Cài đặt bằng Docker (Khuyến nghị)

```bash
cd /home/dts/androidbox/tx3-platform

# Tạo file .env
cat > .env << 'EOF'
TX3_SECRET_KEY=$(openssl rand -hex 32)
WG_SERVER_ENDPOINT=your-server-ip:51820
WG_SERVER_PUBLIC_KEY=your-wg-public-key
EOF

# Khởi động
docker compose up -d

# Seed database (lần đầu)
docker compose exec server python -m database.seed
```

### 1.2 Cài đặt thủ công

```bash
cd management-server

# Tạo virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Cấu hình PostgreSQL
sudo -u postgres createdb tx3_management
sudo -u postgres psql -d tx3_management -f database/schema.sql

# Cấu hình .env
cp .env.example .env
# Sửa các giá trị trong .env

# Seed data
python -m database.seed

# Chạy server
python run.py
```

### 1.3 Cấu hình WireGuard Server

```bash
# Cài WireGuard
sudo apt install wireguard

# Tạo keypair
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key

# Cấu hình /etc/wireguard/wg0.conf
[Interface]
Address = 10.88.0.1/24
ListenPort = 51820
PrivateKey = <server-private-key>

# Peer entries sẽ được thêm tự động bởi provisioning server

# Bật WireGuard
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0
```

---

## Phase 2: Build ROM với Remote Management

### 2.1 Chuẩn bị

1. Mở ROM Builder v0.7.0 (hoặc v2.4.3 exe)
2. Chọn firmware gốc (VD: TX3_MOD22092026.img)
3. Phân tích ROM

### 2.2 Kích hoạt Remote Management

1. Chuyển sang tab **Remote Management**
2. Tick ✅ **Tích hợp Remote Management**
3. Cấu hình:
   - ✅ Auto Start
   - ✅ WireGuard
   - ✅ Live Remote
   - ✅ Mouse / Keyboard / D-Pad
   - ✅ File Transfer
   - ✅ Remote ADB
   - ✅ APK Install
   - ✅ Auto Reconnect
   - ✅ Resource Guard
   - ✅ Watchdog
   - ✅ **Auto ADB** (tự động bật ADB khi flash lần đầu)
4. Nhập Server URL: `http://your-server:8400`
5. Nhập Bootstrap Token (từ bước seed)
6. Chọn Profile: **Auto - S905W/2GB optimized**
7. Áp dụng thay đổi → Đóng gói ROM

### 2.3 Flash ROM

1. Flash ROM đã build vào box bằng USB Burning Tool
2. Boot → Internet → Agent tự khởi động
3. Provisioning tự động → WireGuard kết nối → ONLINE

---

## Phase 3: Sử dụng TX3 Manager

### 3.1 Build TX3 Manager

```bash
cd windows-manager
flutter pub get
flutter build windows --release
```

File exe nằm trong `build/windows/x64/runner/Release/`

### 3.2 Đăng nhập

1. Mở TX3 Manager.exe
2. Nhập Server URL: `http://your-server:8400`
3. Nhập License Key (từ bước seed)
4. Đăng nhập: admin / admin123
5. **ĐỔI MẬT KHẨU NGAY!**

### 3.3 Quản lý thiết bị

- **Tìm kiếm**: Theo tên, vị trí, MAC, IP, tag, ghi chú
- **REMOTE**: Xem màn hình realtime H.264, điều khiển mouse/keyboard
- **FILES**: Duyệt, upload, download file (có resume, hash verify)
- **ADB**: Chạy lệnh ADB từ xa
- **INSTALL APK**: Cài ứng dụng từ xa
- **REBOOT**: Khởi động lại box

---

## Bảo mật

- ⚠ Mỗi box có keypair WireGuard riêng (không shared key)
- ⚠ Bootstrap token chỉ dùng cho provisioning, có giới hạn lượt sử dụng
- ⚠ ADB chỉ qua WireGuard, không expose trực tiếp ra Internet
- ⚠ Audit log cho mọi hành động nhạy cảm
- ⚠ Rate limiting + lockout cho đăng nhập
- ⚠ Session/token có expiration
- ⚠ Box-to-box mặc định bị cô lập

---

## Cấu trúc dự án

```
tx3-platform/
├── README.md
├── docker-compose.yml
├── protocol/
│   └── protocol_v1.json          # Protocol definitions
├── management-server/
│   ├── api/
│   │   ├── main.py               # FastAPI app
│   │   ├── config.py             # Settings
│   │   ├── schemas.py            # Pydantic models
│   │   └── routes/
│   │       ├── auth_routes.py
│   │       ├── device_routes.py
│   │       ├── provisioning_routes.py
│   │       ├── license_routes.py
│   │       ├── audit_routes.py
│   │       ├── batch_routes.py
│   │       └── ws_routes.py      # WebSocket for realtime
│   ├── auth/
│   │   └── __init__.py           # JWT + RBAC
│   ├── database/
│   │   ├── __init__.py           # SQLAlchemy async
│   │   ├── models.py             # ORM models
│   │   ├── schema.sql            # DDL
│   │   └── seed.py               # Initial data
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── run.py
├── android-agent/
│   ├── agent/tx3-agent.sh        # Main agent daemon
│   ├── supervisor/tx3-supervisor.sh
│   ├── stream/tx3-stream.sh      # H.264 capture
│   ├── file-transfer/tx3-file.sh
│   ├── init/tx3-init.sh          # Boot script + Auto ADB
│   └── provisioning/bootstrap.conf
├── rom-builder/
│   └── modules/remote-management/
│       ├── __init__.py           # Injection logic
│       └── ui_tab.py             # ROM Builder UI tab
├── windows-manager/              # Flutter Windows app
│   ├── lib/
│   │   ├── main.dart
│   │   ├── models/models.dart
│   │   ├── services/api_service.dart
│   │   ├── providers/
│   │   │   ├── auth_provider.dart
│   │   │   ├── device_provider.dart
│   │   │   ├── remote_provider.dart
│   │   │   └── transfer_provider.dart
│   │   └── screens/
│   │       ├── login_screen.dart
│   │       ├── main_screen.dart
│   │       ├── device_list_screen.dart
│   │       └── device_detail_screen.dart
│   └── pubspec.yaml
└── docs/
    └── DEPLOYMENT.md
```

---

## Roadmap

| Phase | Nội dung | Trạng thái |
|-------|---------|-----------|
| 0 | Khảo sát ROM thật | ✅ Đã khảo sát source |
| 1 | WireGuard + Device Agent | ✅ Agent scripts hoàn chỉnh |
| 2 | Windows Manager Core | ✅ Flutter app + Login/Device/Search |
| 3 | Remote MVP | ✅ Stream protocol + UI |
| 4 | Remote Stability | ✅ Supervisor + Resource Guard + Adaptive |
| 5 | File Transfer | ✅ Chunked + Resume + Hash + Bandwidth |
| 6 | ADB/APK/Batch | ✅ Routes + Batch operations |
| 7 | Security/RBAC/Audit | ✅ JWT + Roles + Audit Log |
| 8 | ROM Builder Integration | ✅ Module + UI Tab + Auto ADB |
| 9 | Production Hardening | ⏳ Stress test cần box thật |

---

## Lưu ý quan trọng

1. **Benchmark trên box thật**: Profile encoder, MediaCodec, nhiệt, RAM, FPS chỉ chốt được sau khi test trên S905W/2GB thật.
2. **SELinux**: Cần kiểm tra SELinux policy trên ROM thật, có thể cần thêm policy rules.
3. **WireGuard kernel module**: Kiểm tra ROM có expose wireguard.ko hay cần dùng userspace implementation.
4. **H.264 encoder**: screenrecord fallback hoạt động nhưng chưa tối ưu bằng native MediaCodec. Cần native binary cho production.
5. **File transfer lớn**: Chunk size cần benchmark trên eMMC/flash thật, 4MB là giá trị khởi đầu.
