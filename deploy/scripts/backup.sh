#!/usr/bin/env bash
# Platforma zaxirasi: baza (pg_dump) va yuklangan rasmlar, 14 kun saqlanadi.
# docs/DEPLOY.md, 15-qadam. Kunlik: /etc/cron.daily/smartacademy-backup shu faylni chaqiradi;
# deploy.sh ham har yangilashdan oldin chaqiradi.
set -euo pipefail

DIR=/opt/smartacademy-backups
KEEP_DAYS=14
STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$DIR"
chmod 700 "$DIR"

sudo -u postgres pg_dump -Fc smartacademy_platform > "$DIR/platform-$STAMP.dump"
# smartbot bazasi ham: bot endi shu repodan yangilanadi (smartbot/).
sudo -u postgres pg_dump -Fc testbot_db > "$DIR/testbot-$STAMP.dump"
tar -czf "$DIR/uploads-$STAMP.tar.gz" -C /opt/smartacademy/public uploads

find "$DIR" -type f -mtime +"$KEEP_DAYS" -delete
echo "Zaxira tayyor: $DIR/platform-$STAMP.dump, $DIR/testbot-$STAMP.dump, $DIR/uploads-$STAMP.tar.gz"
