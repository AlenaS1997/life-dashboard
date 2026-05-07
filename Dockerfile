# Кастомный образ n8n для Railway.
#
# Зачем нужен:
# - Railway монтирует Volume с владельцем root (mode 700).
# - Базовый образ n8n (n8nio/n8n) запускается под пользователем `node` (uid 1000).
# - Поэтому при старте n8n падает с EACCES: permission denied при попытке
#   создать /data/.n8n.
#
# Этот образ оборачивает официальный n8n entrypoint в chown — выдаёт node-у
# доступ на каталог Volume перед стартом приложения.
#
# Использование в Railway:
# 1. Service → Settings → Source → переключи с Docker Image на GitHub Repo.
# 2. Укажи репозиторий alenas1997/life-dashboard.
# 3. Build path: оставь корень (/), Dockerfile path: Dockerfile.
# 4. Сохрани → Railway соберёт образ и задеплоит.
# 5. Mount Path Volume должен быть /data, env N8N_USER_FOLDER=/data — как сейчас.

FROM n8nio/n8n:latest

# Railway монтирует Volume с владельцем root и mode 700, поэтому стандартный
# запуск n8n под пользователем `node` падает с EACCES на /data.
# Решение — запустить n8n под root. Под root доступ на Volume гарантирован,
# никакие apk add / chown / switch-user не нужны.
USER root

# Подменяем entrypoint: создаём папку Volume и сразу запускаем n8n под root.
RUN printf '#!/bin/sh\nset -e\nmkdir -p "${N8N_USER_FOLDER:-/data}"\nexec n8n "$@"\n' > /docker-entrypoint-fix.sh && \
    chmod +x /docker-entrypoint-fix.sh

# Глушим warning n8n про запуск под root: для нашего homelab-кейса это норма.
ENV N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=false

ENTRYPOINT ["/docker-entrypoint-fix.sh"]
