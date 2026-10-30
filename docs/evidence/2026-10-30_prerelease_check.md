# 10 月 30 日预成果提交前检查报告

日期：2026-10-30

执行人：Hurry

检查对象：`github.com/imdsj/wolfarena`，main 分支 `2fbffb6`（`style: complete dark night theme across cards, roster and countdown`）

## 一、总体结论

```text
公网入口      ：可用（http://106.14.113.216:8080）
代码仓库      ：公开，匿名可克隆
干净环境      ：全新目录克隆后可测试、可构建、可启动
测试          ：234 项通过
密钥与凭据    ：未发现泄漏
待订书机确认  ：视频链接、测试账号、对外使用的链接是否固定 8080
```

**判定：可以提交预成果。** 以下逐项给出实测证据。

## 二、公网入口（任务单第 3 项）

### 2.1 实测

| 地址 | 结果 |
| --- | --- |
| `http://106.14.113.216:8080/health` | **200** `{"status":"ok","service":"wolfarena-api","version":"0.6.0"}` |
| `http://106.14.113.216:8080/` | **200**，`<title>WolfArena 狼域</title>` |
| `/src/main.js`、`/src/components/GameResultPanel.js`、`/vendor/vue.esm-browser.prod.js` | 均 **200**，前端文件齐全 |

### 2.2 功能验证（不只是页面能打开）

在公网地址上完成后端动作：

```text
POST /api/rooms  → 201，room_id 0nmSjA-Z，座位 1，身份 hunter，观战密码存在
WS /ws/rooms/{id} authenticate → authenticated → snapshot
POST action start_night → 阶段自动推进
GET  /api/rooms/{id}   → 1 / DAY_DISCUSSION，10 条可见事件，可用动作 ['speech']
```

**结论：公网环境能建房、能连 WebSocket、能推进阶段，不是空壳页面。**

### 2.3 必须注意：80 端口不是本项目

```text
http://106.14.113.216/      → 200，返回「奉贤小孩模拟器」（另一个项目）
http://106.14.113.216:8080/ → 200，WolfArena
```

**所以对外链接必须带 `:8080`。** 如果演示材料里写成 `http://106.14.113.216`，评委会打开另一个项目。这一条建议在演示 PPT、README、交付说明里统一改成 `http://106.14.113.216:8080`。

### 2.4 观察到的新行为

本次公网测试中，只点了一次 `start_night`，之后未做任何操作，阶段自动推进到了 `DAY_DISCUSSION`。

这与 `91a8819 fix: auto-play idle human turns so a game never stalls` 一致：真人闲置时由系统代打，避免卡死。**这解决了此前记录的「真人挂机会停在当前阶段」的问题**，但也意味着演示时要说明「AI 会自动接管闲置回合」，否则看起来像「自己动了」。

## 三、仓库公开性

```text
GET https://api.github.com/repos/imdsj/wolfarena → 200
private: False    visibility: public    default_branch: main
GET raw.githubusercontent.com/.../README.md → 200
```

匿名克隆成功：

```text
git clone --depth 1 https://github.com/imdsj/wolfarena.git
→ 2fbffb6，包含 backend / frontend / deploy / docs / tests / strategy_library / training_runs
```

## 四、全新目录干净环境（任务单第 1、2 项）

模拟评委拿到代码的完整路径，全部在空目录中进行，不复制任何本机文件。

| 步骤 | 命令 | 结果 |
| --- | --- | --- |
| 1. 匿名克隆 | `git clone --depth 1 https://github.com/imdsj/wolfarena.git` | 成功，`2fbffb6` |
| 2. 建虚拟环境 | `python -m venv .venv` | 成功 |
| 3. 装依赖 | `.venv\Scripts\python -m pip install -r requirements.txt` | 成功，无报错 |
| 4. 跑测试 | `python -m unittest discover -s tests` | **Ran 234 tests, OK** |
| 5. 前端依赖 | `npm install`（frontend） | 成功，53 包 |
| 6. 前端构建 | `npm run build` | 成功，输出 `frontend/dist` |
| 7. 启动服务 | `python -m uvicorn backend.api:app --port 8010` | 成功 |
| 8. 健康检查 | `GET /health` | 200，`wolfarena-api v0.6.0` |
| 9. 页面 | `GET /` | 200，579 字节，含 `WolfArena` |
| 10. 建房 | `POST /api/rooms` | 201，座位 1，身份 seer |

**结论：干净环境可以独立跑起来，不依赖本机的 `.venv`、`dist` 或任何私有文件。**

说明：本地已有环境是 233 项测试，干净克隆是 234 项，差异来自最新提交新增的 1 条用例，属正常。

## 五、密钥与个人信息（任务单第 4 项）

| 检查项 | 结果 |
| --- | --- |
| `.env` / `*.key` / `*.pem` / `id_rsa*` / `*.p12` | 未发现 |
| 硬编码密钥（`sk-…` / `AKIA…` / `ghp_…`） | 未发现 |
| API Key 读取方式 | 仅 `os.getenv(...)`，从环境变量读取 |
| 邮箱 | 仅 GitHub 隐私邮箱 `…@users.noreply.github.com` |
| `.gitignore` | `.env`、`.venv/`、`dist/`、`training_runs/*`、`__pycache__/` 均已排除 |

### 5.1 本机路径清理进度

| 内容 | 10-29 扫描 | 10-30 复查 |
| --- | ---: | ---: |
| `C:\Users\dings\…` | 31 | **13** |
| `D:\传智杯\…` | 25 | **27 → 已清 13 处，剩余多为订书机文档中的记录** |

我负责的三份 evidence 文档（`2026-10-25_hurry_web_acceptance.md`、`2026-10-27_training_ground_decision.md`、`2026-10-29_hurry_gate_and_security_check.md`）中的 13 处绝对路径已全部替换为 `<local-path>` 占位符。

**仍存在的部分**：`docs/13_项目交接说明书_2026-10-24.md`、`docs/14_AI完整交接说明书_2026-10-25.md`、`docs/handoff/` 下的历史文档。这些属于交接材料，清理需订书机确认表述后再改，避免破坏原意。

风险定级：**低**。泄漏的是用户名与目录结构，不是凭据。仓库公开不构成安全事件，但建议在 11 月正式提交前统一改为相对路径。

## 六、需要订书机确认的三项

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 演示视频链接 | **未见** | 仓库与文档中都没有视频地址，需提供 |
| 测试账号 | **未见** | 当前系统无需登录即可游玩，若清单要求账号需说明「免登录」 |
| 对外链接口径 | **待统一** | 建议固定 `http://106.14.113.216:8080`，明确 80 端口属于其他项目 |

## 七、10 月 30 日可写与不可写

**可以写**：

- 九人局引擎完整可运行，234 项自动化测试通过
- 公网地址可访问，能建房、能联机、能推进阶段
- 固定 seed 可复现，200 局日志与指标可复算
- L0 / L1 / L2 三策略在同一评估集上的对照结果

**不可写**：

- 「AI 通过训练变强」——L2（35.0%）未超过 L1（36.5%），G-06 维持 No-Go
- 「训练前后胜率提升」——无训练版，不得生成此类结论
- 「全项验收通过」——M-02、P-02、T-03 至 T-05、A-01 至 A-03 仍未验，须如实写「未验」

## 八、本次检查未做的事

- 未修改 `backend/`、`frontend/` 任何业务代码。
- 未部署或重启公网服务（只做只读探测与一次建房，未影响现有对局）。
- 未改写 Git 历史。
- 未使用系统 Python（干净环境与本地均用 `.venv`）。
