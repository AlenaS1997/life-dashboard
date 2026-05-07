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

# Создаём целевую директорию и выдаём права пользователю node (uid 1000),
# под которым работает n8n. Делаем это в entrypoint, потому что Volume
# монтируется только на runtime, а не на build time.
RUN echo '#!/bin/sh' > /usr/local/bin/fix-perms-and-start.sh && \
    echo 'set -e' >> /usr/local/bin/fix-perms-and-start.sh && \
    echo 'mkdir -p "${N8N_USER_FOLDER:-/home/node/.n8n}"' >> /usr/local/bin/fix-perms-and-start.sh && \
    echo 'chown -R node:node "${N8N_USER_FOLDER:-/home/node/.n8n}"' >> /usr/local/bin/fix-perms-and-start.sh && \
    echo 'exec su-exec node n8n "$@"' >> /usr/local/bin/fix-perms-and-start.sh && \
    chmod +x /usr/local/bin/fix-perms-and-start.sh

# n8nio/n8n alpine-based — в нём уже есть su-exec.
ENTRYPOINT ["/usr/local/bin/fix-perms-and-start.sh"]
