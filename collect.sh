#!/bin/bash
# collect.sh — wrapper chamado pela cron
# Carrega o .env e executa o collector Python.
# Uso na cron:
#   */5 * * * * /home/jose/Projects/zabbix/zabbix-tuya-robot-vacuum/collect.sh >> /tmp/tuya_zabbix.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

set -a
# shellcheck source=.env
source "${SCRIPT_DIR}/.env"
set +a

exec /home/jose/Projects/python/zabbix_tuya_poll/venv/bin/python \
     "${SCRIPT_DIR}/tuya_zabbix.py"
