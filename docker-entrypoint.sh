#!/bin/sh
set -eu

mkdir -p /app/ckpt /app/logs
chown voyager:voyager /app/ckpt /app/logs

exec runuser -u voyager -- "$@"
