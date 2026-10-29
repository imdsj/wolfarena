#!/usr/bin/env bash
# WolfArena 部署前只读检查 + 备份。只读取和复制，不删除、不覆盖现有站点。
#
# 用法：
#   bash backup-check.sh                 # 只做只读检查和 nginx 配置备份
#   bash backup-check.sh /www/wwwroot/xxx # 额外打包指定站点目录
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="/www/backup/wolfarena-${STAMP}"
SITE_DIR="${1:-}"

mkdir -p "${DEST}"
echo "[1/4] 系统与运行时信息 -> ${DEST}/system-info.txt"
{
  echo "== date"; date
  echo "== kernel"; uname -a
  echo "== os"; cat /etc/os-release 2>/dev/null || true
  echo "== nginx"; nginx -v 2>&1 || true
  echo "== nginx -t"; nginx -t 2>&1 || true
  echo "== python"; python3 -V 2>&1 || true
  echo "== node"; node -v 2>&1 || true
  echo "== npm"; npm -v 2>&1 || true
  echo "== listening 8001"; ss -lntp 2>/dev/null | grep -E ':8001\b' || echo "(8001 未被占用)"
  echo "== listening 80/443"; ss -lntp 2>/dev/null | grep -E ':(80|443)\b' || true
} > "${DEST}/system-info.txt" 2>&1

echo "[2/4] 站点目录清单（只读）-> ${DEST}/wwwroot-list.txt"
ls -la /www/wwwroot > "${DEST}/wwwroot-list.txt" 2>&1 || true

echo "[3/4] 备份 nginx 配置 -> ${DEST}/nginx-config"
if [ -d /www/server/panel/vhost/nginx ]; then
  cp -a /www/server/panel/vhost/nginx "${DEST}/nginx-config"
elif [ -d /etc/nginx ]; then
  cp -a /etc/nginx "${DEST}/nginx-config"
else
  echo "未找到 nginx 配置目录" | tee "${DEST}/nginx-config.MISSING"
fi

if [ -n "${SITE_DIR}" ]; then
  if [ -d "${SITE_DIR}" ]; then
    echo "[4/4] 打包站点 ${SITE_DIR} -> ${DEST}/site.tar.gz"
    tar czf "${DEST}/site.tar.gz" -C "$(dirname "${SITE_DIR}")" "$(basename "${SITE_DIR}")"
  else
    echo "[4/4] 站点目录不存在：${SITE_DIR}" >&2
  fi
else
  echo "[4/4] 未指定站点目录，跳过站点打包（可重新指定）"
fi

cat > "${DEST}/ROLLBACK.txt" <<EOF
备份时间：${STAMP}
备份目录：${DEST}

回滚 nginx 配置：
  cp -a ${DEST}/nginx-config/. /www/server/panel/vhost/nginx/
  nginx -t && nginx -s reload

回滚站点目录（若打包过）：
  tar xzf ${DEST}/site.tar.gz -C /www/wwwroot

已知信息：
$(grep -E '^(== nginx|== python|== node|== listening)' "${DEST}/system-info.txt" || true)
EOF

echo
echo "备份完成：${DEST}"
echo "回滚说明：${DEST}/ROLLBACK.txt"
