# 公网部署更新记录 · 2026-11-05

## 背景

公网 `http://106.14.113.216:8080/` 此前一直跑 10 月 30 日的旧版本，
导致看不到夜晚主题、发言气泡、自由选座和训练场接口。

## 变更

| 项 | 值 |
| --- | --- |
| 部署前提交 | `0881724` |
| 部署后提交 | `196dc4e` |
| 服务器路径 | `/www/wwwroot/wolfarena` |
| 服务 | `wolfarena.service`（systemd） |
| 备份 | `/www/backup/wolfarena-dist-predeploy-196dc4e.tgz`、`/www/backup/wolfarena-predeploy-head.txt` |

步骤：

1. `git fetch origin`（远端 `196dc4e`）。
2. `git merge --ff-only origin/main`（工作区原本干净，快进，无冲突）。
3. `cd frontend && npm ci && npm run build`。
4. `systemctl restart wolfarena`。

没有使用 `git reset --hard`，没有覆盖任何本地修改，部署前已备份 `frontend/dist`。

## 验证

| 检查 | 结果 |
| --- | --- |
| `systemctl is-active wolfarena` | active |
| `GET /health` | 200，`wolfarena-api 0.6.0` |
| `styles.css` 中 `night-mode` | 52 条 |
| `LobbyPanel.js` 中“查询空座” | 2 处 |
| `styles.css` 中 `speech-bubble` | 8 条 |
| `deploy/smoke.py http://106.14.113.216:8080` | `ALL CHECKS PASSED` |
| `GET /api/training/models` | 四个固定 ID |
| `GET /api/training/metrics?model_id=l2.qtable.v2` | 200 样本、35.0%、`no_go=true` |

## 说明

- 本次登录使用团队既有 SSH 密钥，密钥文件不入库、不写入文档。
- 服务器 git 提示 dubious ownership，已按标准做法把项目目录加入
  `safe.directory`，未改动仓库内容。
- 回滚方式：`/www/backup` 下的 dist 备份，或把代码回退到 `0881724` 后重建前端。
