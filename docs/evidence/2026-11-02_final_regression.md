# 11 月 2 日最终回归与视频审核

日期：2026-11-02

执行人：Hurry

代码：`0359973`（`docs: record Edge acceptance and video link, strip local paths`，2026-11-01 19:40）

## 一、最终回归

### 1.1 全量测试

```text
python -m unittest discover -s tests
Ran 234 tests in 4.595s
OK
```

### 1.2 公网冒烟

```powershell
python deploy\smoke.py http://106.14.113.216:8080
```

```text
target: http://106.14.113.216:8080
health: ok {'status': 'ok', 'service': 'wolfarena-api', 'version': '0.6.0'}
home: ok bytes=557
create_room: ok status=201
  ws_player: ok (authenticated)
  ws_spectator: ok (authenticated)
ws_bad_token: ok (rejected)
ALL CHECKS PASSED
```

**判定：通过。**

## 二、口径核对（任务单第 3 项）

全局检索 `106.14.113.216`：

- 所有**正式对外链接**均为 `http://106.14.113.216:8080/`
- 仅 3 处不带端口，且都出现在「反例说明」上下文中：
  - `2026-10-30_acceptance_checklist.md`：「80 端口 `http://106.14.113.216/` 返回的是另一个项目，不能写进材料」
  - `2026-10-30_prerelease_check.md`：同义说明（两处）

**判定：通过。** 材料中没有把 80 端口当作正式入口的写法。

## 三、视频审核（任务单第 2 项）

记录地址：`https://www.bilibili.com/video/BV1hxxi6HEuS/`

匿名访问：

```text
HTTP 200（无跳转、无需登录即可返回页面）
记录信息：191 秒，公开可访问
```

订书机 2026-11-02 确认：视频为公开链接，已在 `2026-10-30_acceptance_checklist.md` 中登记，时长为 191 秒。链接一节**已闭环**；画面与音频内容仍待人工核验。

### 3.1 能证明与不能证明的部分

| 检查点 | 状态 |
| --- | --- |
| 链接可访问、公开 | **已验证**（HTTP 200） |
| 时长 191 秒与记录一致 | 未独立核验（需播放器渲染后的时长字段） |
| 画面无密钥 | **无法核验**——需要人眼逐帧观看 |
| 画面无手机号 | **无法核验**——同上 |
| 画面无后台管理界面 | **无法核验**——同上 |
| 无 80 端口地址 / 无「训练后变强」表述 | **无法核验**——音频与字幕需人听 |

**必须说明**：自动化只能确认「链接可用」。任务单第 2 项要求的「无密钥、无手机号、无后台、公开可播」中，后四项属于内容审核，**本轮未完成，不能写通过**。

建议由祁楷按下面清单自查并签字，或提供可下载的 MP4 后由人工抽检：

```text
[ ] 全程无 API Key、token、密码出现在画面
[ ] 无手机号、真实姓名、身份证等个人信息
[ ] 无服务器 SSH、数据库、后台管理界面
[ ] 出现的网址均为 http://106.14.113.216:8080
[ ] 无「AI 通过训练变强」「训练后胜率提升」等表述
[ ] 视频为公开状态，未登录可播放
```

## 三之二、测试账号（订书机已确认）

订书机 2026-11-02 确认：**系统为免登录**，材料中按「无需注册账号，打开链接即可开始对局」表述。

因此该项不构成缺口，但需确认 PPT、README、交付说明三处措辞一致，避免出现「请使用测试账号登录」这类与实际不符的描述。

## 四、冻结 tag（任务单第 4 项）——未完成

```text
git ls-remote --tags origin | grep "0.11\|training-evidence"
→ 无输出
```

**远端不存在 `v0.11-training-evidence`。** 现有 tag 中最新的为 `v0.9.9.1-server-seed`。

这一项属于订书机的动作，我这边只能确认「未推送」。**冻结在版本层面尚未完成**：如果最终提交以 tag 作为基准，现在没有可引用的版本标签。

建议：尽快执行

```powershell
git tag -a v0.11-training-evidence -m "training evidence freeze"
git push origin v0.11-training-evidence
```

## 五、补做 11-01 的训练复算

任务单 11-01 要求写 `docs/evidence/2026-11-01_training_reproducibility.md`，仓库中**不存在该文件**（只有 `2026-11-01_training_display_report.md`，属展示报告）。本轮补做，结果如下。

### 5.1 L2 v2 评估复算

```powershell
python -m backend.simulator --games 200 --seed-start 1000 --policy l2 `
  --model-in strategy_library/models/l2-qtable-v2.json --out <输出目录>
```

| 指标 | 文档记录 | 本轮复算 |
| --- | --- | --- |
| 好人胜 / 狼人胜 | 70 / 130 | **70 / 130** |
| 好人胜率 | 35.0% | **35.0%** |
| 失败局 | 0 | **0** |
| actions.jsonl SHA-256 | `625b44c7…d1877` | **`625B44C7F272…D1AD1877`** |

### 5.2 指标独立复算

```text
python -m backend.metrics --run <输出目录>
→ matches_summary: true
→ differences: []
```

### 5.3 模型校验

| 模型 | content_hash | 训练 seed |
| --- | --- | --- |
| `l2-qtable-v1.json` | `3461404ed50f43b8…`（与文档一致） | 0–999 |
| `l2-qtable-v2.json` | `57cea29e7b77e46a…`（与文档一致） | 0–999 |

训练 seed 上限 999，评估 seed 起点 1000，**无重叠**。

### 5.4 结论

L2 v2 好人胜率 35.0%，低于 L1 的 36.5%（10-27 与 10-29 两次记录均为 36.5%）。**L2 未超过 L1，G-06 维持 No-Go**，与前次结论一致，无差异需要标注。

## 六、今日结论

| 任务单项 | 结果 |
| --- | --- |
| 最终冒烟（234 测试 + 公网 smoke） | **通过** |
| 视频审核 | **链接已闭环**（HTTP 200，191 秒，订书机登记）；画面与音频内容未核验 |
| 口径核对（统一 :8080） | **通过** |
| 测试账号 | **已确认**：免登录，材料按此表述 |
| 冻结 tag `v0.11-training-evidence` | **未完成**，远端无此 tag（截至 11-02 17:40 复查仍缺） |

```text
可以对外说的：
  234 项自动化测试通过；公网 :8080 冒烟全部通过；
  固定 seed 可复现且指标可独立复算；L2 未超 L1，负结果如实保留。

不能对外说的：
  「训练后变强」「全项验收通过」「视频已审核通过」。
```

## 七、本次未做的事

- 未观看视频内容，未对画面与音频作任何通过判断。
- 未创建或推送 tag（属订书机动作）。
- 未修改 `backend/`、`frontend/`、`strategy_library/` 任何代码与模型。
- 未改写 Git 历史。
