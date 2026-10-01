#!/bin/bash
# ====================================================================
#  TX3 PLATFORM - AUTOMATED 1-CLICK SERVER INSTALLER & DEPLOYMENT
# ====================================================================
set -e

RED='\030[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${CYAN}=====================================================${NC}"
echo -e "${CYAN}   🚀 TX3 REMOTE PLATFORM - AUTOMATED SERVER SETUP   ${NC}"
echo -e "${CYAN}=====================================================${NC}"

# Check root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}❌ Vui lòng chạy script với quyền root (sudo bash install_server.sh)${NC}"
  exit 1
fi

# 1. Interactive Inputs
echo -e "\n${YELLOW}[1/6] THÔNG TIN CẤU HÌNH THIẾT LẬP${NC}"
read -p "👉 Nhập Tên Miền (Domain) của bạn (Ví dụ: tx3.yourdomain.com): " DOMAIN_NAME
if [ -z "$DOMAIN_NAME" ]; then
  echo -e "${RED}❌ Tên miền không được để trống!${NC}"
  exit 1
fi

read -p "👉 Sử dụng Cloudflare Tunnel tự động (HTTPS + Tự tạo DNS)? (y/n) [mặc định: y]: " USE_CF
USE_CF=${USE_CF:-y}

if [[ "$USE_CF" =~ ^[Yy]$ ]]; then
  echo -e "${CYAN}ℹ️ Chuẩn bị kết nối Cloudflare Tunnel...${NC}"
  read -p "👉 Nhập Cloudflare Tunnel Token (Nếu có, bấm Enter để đăng nhập bằng Cloudflare Login): " CF_TOKEN
fi

# 2. System Dependencies Update
echo -e "\n${YELLOW}[2/6] ĐANG TẢI & CÀI ĐẶT CÁC CÔNG CỤ CẦN THIẾT (Docker, Git, WireGuard)...${NC}"
apt-get update -y >/dev/null 2>&1 || true
apt-get install -y curl git wget build-essential wireguard docker.io docker-compose-v2 net-tools >/dev/null 2>&1 || true

systemctl enable docker --now >/dev/null 2>&1 || true

# 3. Download / Clone Source Code
INSTALL_DIR="/opt/tx3-platform"
echo -e "\n${YELLOW}[3/6] TỰ ĐỘNG TẢI MÃ NGUỒN TX3 PLATFORM...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${CYAN}Cập nhật mã nguồn mới nhất tại $INSTALL_DIR...${NC}"
    cd "$INSTALL_DIR"
else
    echo -e "${CYAN}Khởi tạo thư mục $INSTALL_DIR...${NC}"
    mkdir -p "$INSTALL_DIR"
    # Giả định clone từ git repo hoặc copy local
    if [ -d "/home/dts/androidbox/tx3-platform" ]; then
        cp -r /home/dts/androidbox/tx3-platform/* "$INSTALL_DIR/"
    fi
    cd "$INSTALL_DIR"
fi

# 4. Generate Security Keys & Env
echo -e "\n${YELLOW}[4/6] TỰ ĐỘNG CẤU HÌNH BIẾN MÔI TRƯỜNG & KHÓA BẢO MẬT...${NC}"
SECRET_KEY=$(openssl rand -hex 32)
BOOTSTRAP_TOKEN=$(openssl rand -base64 24 | tr -d '+/=' | cut -c1-32)

cat <<ENVEOF > .env
TX3_SECRET_KEY=$SECRET_KEY
BOOTSTRAP_TOKEN=$BOOTSTRAP_TOKEN
DOMAIN_NAME=$DOMAIN_NAME
SERVER_URL=https://$DOMAIN_NAME
WG_SERVER_ENDPOINT=$DOMAIN_NAME:51820
ENVEOF

# 5. Cloudflare Tunnel Setup (If Enabled)
if [[ "$USE_CF" =~ ^[Yy]$ ]]; then
  echo -e "\n${YELLOW}[5/6] THIẾT LẬP CLOUDFLARE TUNNEL (AUTO HTTPS & DOMAIN)...${NC}"
  if ! command -v cloudflared &> /dev/null; then
    curl -L --output /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb >/dev/null 2>&1
    dpkg -i /tmp/cloudflared.deb >/dev/null 2>&1 || true
    rm -f /tmp/cloudflared.deb
  fi

  if [ -n "$CF_TOKEN" ]; then
    cloudflared service install "$CF_TOKEN" || true
    systemctl start cloudflared || true
  else
    echo -e "${CYAN}🔑 Vui lòng mở đường dẫn sau trên trình duyệt để xác thực Cloudflare:${NC}"
    cloudflared tunnel login || true
    cloudflared tunnel create tx3-tunnel || true
    cloudflared tunnel route dns tx3-tunnel "$DOMAIN_NAME" || true
  fi
fi

# 6. Launch Docker Containers
echo -e "\n${YELLOW}[6/6] KHỞI CHẠY HỆ THỐNG MANAGEMENT SERVER & WIREGUARD...${NC}"
docker compose down >/dev/null 2>&1 || true
docker compose up -d --build

echo -e "\n${GREEN}=====================================================${NC}"
echo -e "${GREEN}  🎉 CÀI ĐẶT THÀNH CÔNG HỆ THỐNG MANAGEMENT SERVER! ${NC}"
echo -e "${GREEN}=====================================================${NC}"
echo -e "🌐 Server URL:        ${CYAN}https://$DOMAIN_NAME${NC}"
echo -e "🔑 Bootstrap Token:   ${YELLOW}$BOOTSTRAP_TOKEN${NC}"
echo -e "📂 Thư mục cài đặt:   ${CYAN}$INSTALL_DIR${NC}"
echo -e "-----------------------------------------------------"
echo -e "📌 Sử dụng Bootstrap Token trên để mở GUI TX3_Control_GUI!"
echo -e "${GREEN}=====================================================${NC}"
