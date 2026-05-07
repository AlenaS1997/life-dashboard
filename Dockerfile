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

USER root

# n8n image alpine-based, su-exec нужен для запуска n8n под пользователем node
# после того как мы (под root) сделали chown на Volume.
RUN apk add --no-cache su-exec

# Создаём entrypoint-скрипт. Делаем это в build time (а не в runtime),
# потому что Volume монтируется только при старте контейнера.
RUN printf '#!/bin/sh\nset -e\nmkdir -p "${N8N_USER_FOLDER:-/home/node/.n8n}"\nchown -R node:node "${N8N_USER_FOLDER:-/home/node/.n8n}"\nexec su-exec node n8n "$@"\n' > /usr/local/bin/fix-perms-and-start.sh && \
    chmod +x /usr/local/bin/fix-perms-and-start.sh

ENTRYPOINT ["/usr/local/bin/fix-perms-and-start.sh"]
