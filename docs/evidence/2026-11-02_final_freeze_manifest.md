# 11 月 2 日最终冻结清单

今天只做只读确认与材料归档，不新增功能、不重新训练。

## 1. 代码状态

| 项 | 值 |
| --- | --- |
| 合并基线 | `9417049`（含 Hurry 的 `2026-11-02_final_regression.md`） |
| 工作区 | 干净，0 个未提交/未跟踪文件 |
| 测试 | `python -m unittest discover -s tests` → 234 项 OK |
| 公网入口 | `http://106.14.113.216:8080/`（必须带 `:8080`） |
| 公网冒烟 | `deploy/smoke.py` → `ALL CHECKS PASSED`（Hurry 11-02 复跑） |

## 2. 交付材料四样

| 材料 | 状态 | 位置 |
| --- | --- | --- |
| 演示视频 | 已上传、公开 | `https://www.bilibili.com/video/BV1hxxi6HEuS/`（191 秒） |
| 训练展示 | 数字与口径已定稿 | `2026-11-01_training_display_report.md` |
| 作品介绍 DOCX | 已通过逐页检查（由订书机侧维护） | 作品包内 `提交材料/17_WolfArena_省赛预指导作品介绍.docx` |
| 公网链接 | 统一 `:8080` | `http://106.14.113.216:8080/` |

说明：

- 视频画面与音频仍需人工核验一次（是否出现 Key/密码/后台地址，L2 是否明确说 No-Go）。
- 训练展示图表/PPT 与视频原文件不在本仓库，属团队本地交付物；仓库只保存数字、口径与复算命令。
- 390px 截图位于 `docs/evidence/browser-2026-10-26/`，由 Edge（Chromium 内核）采集。

## 3. 冻结边界

- 不再新增功能；只允许修复无法启动、无法推进、身份/密钥泄漏这类阻断问题。
- 不再重新训练；L0/L1/L2 的数字以现有证据为准。
- 任何材料不得出现“训练后变强”“胜率提升”表述。

## 4. 复现入口

```powershell
python -m unittest discover -s tests
python -m backend.metrics --run training_runs/eval-l2-v2-200
python deploy/smoke.py http://106.14.113.216:8080
```
