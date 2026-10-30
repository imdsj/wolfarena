# 10 月 29 日训练门禁与安全检查

日期：2026-10-29

执行人：Hurry

执行环境：`<local-path>` 的 `.venv`（Python 3.14.0），代码取自远端 `main` 的压缩包

代码版本：`de85b20`（`docs: add 10-30 pre-result acceptance checklist`）

## 一、取代码的方式与限制

`git pull` 在当前网络下持续失败：

```text
fatal: unable to access 'https://github.com/imdsj/wolfarena/': CONNECT tunnel failed, response 502
```

同一时刻 `api.github.com` 可访问。因此改用 GitHub API 下载 `main` 的压缩包（731 KB，解压为 `imdsj-wolfarena-de85b20/`），在其上跑测试与复算，`.venv` 复用本地环境。

**这意味着本次核对的不是本地 git 工作区，而是远端 main 的快照。** 结论对远端有效；本地工作区仍停在 `00a8ba5`，网络恢复后需 `git pull` 同步。

## 二、仓库公开性（任务单 15 分钟项）

匿名请求（不带任何凭据）：

```text
GET https://api.github.com/repos/imdsj/wolfarena   → 200
GET https://raw.githubusercontent.com/.../README.md → 200
```

元数据：

```text
full_name       : imdsj/wolfarena
private         : False
visibility      : public
default_branch  : main
pushed_at       : 2026-10-29T03:58:37Z
license         : None
```

**结论：仓库已转公开，匿名可读。10 月 30 日评审可以直接访问。**

补充：`license` 为 `None`，即无 LICENSE 文件。比赛未要求开源协议，不阻塞交付，但若评审问「是否开源」需说明「代码公开可读，未附协议」。

## 三、233 项测试

```text
python -m unittest discover -s tests
Ran 233 tests in 3.002s
OK
```

比 10-28 的 206 项多 27 项，新增集中在 L2 Q 表与自动化真人补位。无失败、无跳过。

## 四、L2 训练门禁独立复核

不采信文档结论，逐项用本机复跑核对。

### 4.1 门禁表

| 判据 | 要求 | 我的核查方式 | 结论 |
| --- | --- | --- | --- |
| 训练/评估 seed 分离 | 训练 seed 不得含 1000–1199 | 读 `l2-qtable-v1.json` / `v2.json` 的 `meta`：均为 `train_seed_start=0`、`train_seed_end=999` | **通过** |
| 三策略同评估集 | L0 / L1 / L2 均为 1000–1199 | 三个 manifest 的 `seed_start=1000`、`seed_end=1199` | **通过** |
| 复现性 | 同模型同 seed 两次一致 | 复跑 L2 v2 200 局，`actions.jsonl` SHA-256 = `625B44C7…D1877`，与文档记录一致 | **通过** |
| 合法性 | 非法动作 0，失败局单列 | 复跑结果 `errors_by_type={}`、`failed_games=0` | **通过** |
| 指标可复算 | 从原始日志复算且一致 | `python -m backend.metrics` → `matches_summary=true`、`differences=[]` | **通过** |
| 真实性 | 有模型卡与 manifest | `docs/evidence/2026-10-29_l2_model_card.md`、6 份 manifest 均在库 | **通过** |

### 4.2 复跑数据

L2 v2 评估（200 局，seed 1000–1199）：

| 指标 | 文档记录 | 我的复跑 |
| --- | --- | --- |
| 好人胜 | 70 | **70** |
| 狼人胜 | 130 | **130** |
| 好人胜率 | 35.0% | **35.0%** |
| 平均步数 | 73.485 | **73.485** |
| 失败局 | 0 | **0** |
| 动作流 SHA-256 | `625b44c7…d1877` | `625B44C7F272…D1AD1877` |

### 4.3 三策略横向对比（评估集 1000–1199，各 200 局）

| 策略 | 版本 | 好人胜率 | 与 L1 对比 |
| --- | --- | ---: | --- |
| L0 随机 | `l0.random.v1` | 84.0% | — |
| L1 人工规则 | `l1.rule.v1` | 36.5% | 基准 |
| L2 v1 Q 表 | `l2.qtable.v1` | 31.5% | −5.0pp |
| L2 v2 扩状态 | `l2.qtable.v2` | 35.0% | −1.5pp（3 局） |

**L2 两个版本都没有超过 L1。** 订书机给的结论「判据全过，但不足以晋升，G-06 维持 No-Go」与实测一致，我认同。

需要强调的是：**门禁全过 ≠ 策略变强**。这些判据只证明实验真实、可复现、可审计，不证明学习有效。n=200 时单个比例的 95% 置信区间约 ±6.6pp，35.0% 与 36.5% 的 1.5pp 差距完全在噪声内。

## 五、密钥与个人信息扫描

扫描对象：远端 main 快照的全部文件。

| 检查项 | 结果 |
| --- | --- |
| `.env` / `*.key` / `*.pem` / `id_rsa*` / `*.p12` | **未发现** |
| 硬编码密钥（`sk-…`、`AKIA…`、`ghp_…`） | **未发现** |
| API Key 引用方式 | 仅 `os.getenv("DEEPSEEK_API_KEY")` / `os.getenv("OPENAI_API_KEY")`，从环境读取，正确 |
| 邮箱 | 仅 `345704669+hurry114514@users.noreply.github.com`（GitHub 隐私邮箱，安全） |
| `.gitignore` 覆盖 | `.env`、`.venv/`、`dist/`、`training_runs/*`、`__pycache__/` 均已排除 |
| **本机绝对路径** | **发现问题，见下** |

### 5.1 需要清理：公开仓库里含本机路径

仓库已公开，但文档中保留了大量本机绝对路径：

| 内容 | 出现次数 | 涉及文件 |
| --- | ---: | --- |
| `C:\Users\dings\…`（订书机本机路径，含 Windows 用户名） | **31** | `docs/13_项目交接说明书_2026-10-24.md`、`docs/14_AI完整交接说明书_2026-10-25.md`、`docs/handoff/2026-10-25/*`、部分 evidence |
| `<local-path>`（Hurry 本机路径） | **25** | `docs/13`、`docs/14`、`docs/evidence/2026-10-25_hurry_web_acceptance.md`、`2026-10-27_training_ground_decision.md` 等 |

风险等级：**低但不该留**。泄漏的是 Windows 用户名与目录结构，不是凭据。但仓库公开后，评委会看到「文档里的命令路径和实际仓库位置无关」，观感不好，也不符合交接文档应有的通用性。

处理建议：

1. 交接说明与 handoff 文档里的路径统一改成相对路径（`<repo>`）或占位符。
2. evidence 文档里记录命令时，用 `cd <repo>` 代替绝对路径。
3. **不要为了清理而改写 Git 历史**——历史里仍会保留这些字符串。新增一次清理提交即可，并在 README 或交付说明中说明「历史提交中含早期本机路径，不影响代码」。

## 六、今日结论

```text
仓库公开        ：已公开，匿名可读 ✅
测试            ：233 项通过 ✅
训练门禁        ：6 项判据全部通过 ✅
L2 是否变强     ：否。v1 31.5%、v2 35.0%，均低于 L1 36.5% → G-06 维持 No-Go ✅（结论正确）
密钥扫描        ：无凭据泄漏 ✅
个人信息        ：56 处本机绝对路径需清理 ⚠️
```

10 月 30 日可交付范围不变：九人局引擎、固定 seed 单机演示、200 局日志与指标、完整测试报告、预录演示；**训练前后对照仍为阻塞**，不得宣称 AI 已变强。

## 七、本次未做的事

- 未修改 `backend/` 或 `strategy_library/` 任何业务代码。
- 未重新训练 L2（直接复算既有模型，避免生成与文档不一致的新数据）。
- 未改写 Git 历史。
- 未使用系统 Python（复用 `.venv`）。
