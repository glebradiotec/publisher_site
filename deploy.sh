#!/bin/bash
# =============================================================
#  Скрипт автоматического деплоя Publisher Site
#  Сервер: 141.105.68.223 (HOSTKEY VPS, Ubuntu 24.04)
#
#  Использование:
#    1. Скопировать проект на сервер (scp или git)
#    2. Запустить: bash deploy.sh
# =============================================================

set -e  # Остановка при ошибке

APP_NAME="publisher"
APP_DIR="/var/www/publisher_site"
APP_USER="www-data"
DOMAIN="_"  # Замените на ваш домен, например: radiotec.ru
PORT=8000

echo "============================================"
echo "  Деплой Publisher Site"
echo "============================================"

# --- 1. Обновление системы ---
echo ""
echo "[1/7] Обновление системы..."
apt update -y && apt upgrade -y

# --- 2. Установка пакетов ---
echo ""
echo "[2/7] Установка Python, Nginx, Certbot..."
apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx ufw

# --- 3. Настройка файрвола ---
echo ""
echo "[3/7] Настройка файрвола..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# --- 4. Настройка Python-окружения ---
echo ""
echo "[4/7] Настройка Python-окружения..."
cd "$APP_DIR"

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# Генерируем SECRET_KEY если не задан
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo "SECRET_KEY сгенерирован: ${SECRET_KEY:0:8}..."

deactivate

# --- 5. Создание systemd-сервиса ---
echo ""
echo "[5/7] Создание systemd-сервиса..."

cat > /etc/systemd/system/${APP_NAME}.service << SERVICEEOF
[Unit]
Description=Publisher Site (Flask + Gunicorn)
After=network.target

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment="SECRET_KEY=${SECRET_KEY}"
Environment="FLASK_DEBUG=0"
ExecStart=${APP_DIR}/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:${PORT} --timeout 120 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Права на папку проекта
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

systemctl daemon-reload
systemctl enable ${APP_NAME}
systemctl start ${APP_NAME}

echo "Gunicorn запущен на порту ${PORT}"

# --- 6. Настройка Nginx ---
echo ""
echo "[6/7] Настройка Nginx..."

cat > /etc/nginx/sites-available/${APP_NAME} << NGINXEOF
server {
    listen 80;
    server_name ${DOMAIN};

    client_max_body_size 100M;

    # Статика — отдаётся Nginx напрямую (быстрее)
    location /static/ {
        alias ${APP_DIR}/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Всё остальное — проксируем в Gunicorn
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120;
    }
}
NGINXEOF

# Активируем сайт
ln -sf /etc/nginx/sites-available/${APP_NAME} /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl restart nginx

echo "Nginx настроен"

# --- 7. Инициализация БД ---
echo ""
echo "[7/7] Инициализация базы данных..."
cd "$APP_DIR"
source venv/bin/activate
python3 -c "
from app import app, db, init_data
with app.app_context():
    db.create_all()
    init_data()
"
deactivate

# Возвращаем права после создания БД
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

# --- Готово! ---
echo ""
echo "============================================"
echo "  ДЕПЛОЙ ЗАВЕРШЁН!"
echo "============================================"
echo ""
echo "  Сайт доступен: http://$(hostname -I | awk '{print $1}')"
echo "  Админка:        http://$(hostname -I | awk '{print $1}')/admin"
echo "  Логин:          admin"
echo "  Пароль:         admin2026"
echo ""
echo "  ВАЖНО: Смените пароль администратора!"
echo ""
echo "  Для HTTPS с доменом выполните:"
echo "    1. Укажите домен в DNS (A-запись → $(hostname -I | awk '{print $1}'))"
echo "    2. Замените server_name в /etc/nginx/sites-available/${APP_NAME}"
echo "    3. certbot --nginx -d ваш-домен.ru"
echo ""
echo "  Полезные команды:"
echo "    systemctl status ${APP_NAME}    — статус приложения"
echo "    systemctl restart ${APP_NAME}   — перезапуск"
echo "    journalctl -u ${APP_NAME} -f    — логи"
echo "============================================"
