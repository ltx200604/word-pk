#!/usr/bin/env bash
# 单词 PK —— 阿里云/任意 Linux 服务器一键部署
# 用法: bash deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/word-pk}"
PORT="${PORT:-8765}"
REPO_URL="${REPO_URL:-https://github.com/ltx200604/word-pk.git}"

echo "==> 1/5 安装基础依赖"
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y git python3 python3-pip python3-venv ufw
elif command -v yum >/dev/null 2>&1; then
  yum install -y git python3 python3-pip firewalld
else
  echo "请使用 Ubuntu/Debian/CentOS"
  exit 1
fi

echo "==> 2/5 拉取/更新代码"
mkdir -p "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only || true
else
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> 3/5 创建虚拟环境并安装依赖"
python3 -m venv .venv
./.venv/bin/pip install -U pip
./.venv/bin/pip install -r requirements.txt

echo "==> 4/5 写入 systemd 服务"
cat > /etc/systemd/system/word-pk.service <<EOF
[Unit]
Description=Word PK
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=3
Environment=PORT=${PORT}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable word-pk
systemctl restart word-pk

echo "==> 5/5 放行端口 ${PORT}"
if command -v ufw >/dev/null 2>&1; then
  ufw allow "${PORT}/tcp" || true
  ufw allow ssh || true
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port=${PORT}/tcp || true
  firewall-cmd --reload || true
fi

sleep 2
if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
  echo ""
  echo "=========================================="
  echo " 部署成功！"
  echo " 浏览器打开: http://$(curl -fsS ifconfig.me 2>/dev/null || echo '你的公网IP'):${PORT}"
  echo " 电脑可以关机，手机收藏这个网址即可"
  echo "=========================================="
else
  echo "服务可能未就绪，请查看: journalctl -u word-pk -n 50"
  systemctl status word-pk --no-pager || true
fi
