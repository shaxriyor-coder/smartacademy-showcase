#!/usr/bin/env bash
# Platformani yangilash — serverda, root sifatida:
#   bash /opt/smartacademy/deploy/scripts/deploy.sh
# Zaxira -> kod -> paketlar -> migratsiya -> build -> qayta ishga tushirish -> tekshiruv.
# smartbot/ (testbot.service) ham shu repodan yangilanadi. docs/DEPLOY.md, "Yangilash".
set -euo pipefail

APP=/opt/smartacademy
as_app() { sudo -u smartacademy -H bash -c "cd '$APP' && $1"; }

echo "1/6 Zaxira..."
bash "$APP/deploy/scripts/backup.sh"

echo "2/6 Kod..."
# Papkani root sifatida `git pull` qilish (yoki root bilan clone) `.git` ni
# root'niki qilib qo'yadi. Keyingi deploy esa git'ni smartacademy nomidan
# ishlatadi va "fatal: .git/index: index file open failed: Permission denied"
# bilan yiqiladi. Shuning uchun egasi tekshiriladi va kerak bo'lsa tiklanadi.
owned_by_app() { [ "$(stat -c %U "$1" 2>/dev/null)" = "smartacademy" ]; }
if ! owned_by_app "$APP" || ! owned_by_app "$APP/.git" \
   || { [ -f "$APP/.git/index" ] && ! owned_by_app "$APP/.git/index"; }; then
  echo "   papka egasi tiklanmoqda: chown -R smartacademy $APP"
  chown -R smartacademy:smartacademy "$APP"
fi

before=$(git -C "$APP" rev-parse --short HEAD)
as_app "git pull --ff-only"
echo "   $before -> $(git -C "$APP" rev-parse --short HEAD)"

echo "3/6 Paketlar..."
# Build uchun devDependencies ham kerak (TypeScript, Tailwind, tsx, prisma).
as_app "npm ci --include=dev --no-audit --no-fund"
as_app "checker/.venv/bin/pip install -q -r checker/requirements.txt"
as_app "smartbot/.venv/bin/pip install -q -r smartbot/requirements.txt"

echo "4/6 Migratsiyalar..."
as_app "npx prisma migrate deploy && npx prisma generate"

echo "5/6 Tekshiruv va build..."
# Bot kodida sintaksis xatosi bo'lsa, qayta ishga tushirishdan oldin to'xtaymiz.
as_app "cd smartbot && .venv/bin/python -m compileall -q bot.py config.py database handlers services utils"
as_app "NODE_OPTIONS=--max-old-space-size=1536 npm run build"

echo "6/6 Qayta ishga tushirish..."
systemctl restart smartacademy-checker smartacademy-web smartacademy-notify testbot
sleep 5
if ! systemctl is-active --quiet testbot; then
  echo "XATO: testbot (smartbot) ishlamayapti. Qarang: journalctl -u testbot -n 100" >&2
  exit 1
fi
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3000/api/health >/dev/null; then
    echo "Tayyor: platforma javob beryapti ($(git -C "$APP" rev-parse --short HEAD))."
    exit 0
  fi
  sleep 2
done
echo "XATO: /api/health javob bermadi. Qarang: journalctl -u smartacademy-web -n 100" >&2
exit 1
