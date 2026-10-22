# 环境与测试基线记录

日期：2026-10-22

对应提交：`779e116`（`test: add acceptance cases for night actions, witch, self-destruct and voting`）

执行人：Hurry

用途：记录首次验收执行的环境状态与测试基线，作为后续回归的对照基准。

## 1. 测试命令与结果

```powershell
cd D:\传智杯\wolfarena
py -m unittest discover -s tests -v
```

```text
----------------------------------------------------------------------
Ran 17 tests in 0.004s

OK
```

17 项全部通过，与 `docs/evidence/2026-10-22_step-6_test_report.md` 记录的基线一致。

## 2. 本机环境实测

| 项 | 实测结果 | 状态 |
| --- | --- | --- |
| Git | `git version 2.56.0.windows.2`，安装在 `D:\Edge\Git`，`D:\Edge\Git\cmd` 已在系统 PATH | 可用 |
| Git 身份 | `hurry114514 <345704669+hurry114514@users.noreply.github.com>`（GitHub 匿名邮箱） | 已配置 |
| 凭据 | Git Credential Manager 2.9.1，GitHub 账号已登录并缓存 | 可用，push 免重复登录 |
| Python | `py --version` → **3.14.0** | 可用 |
| `python` 命令 | 指向 `WindowsApps\python.exe`，是 Microsoft Store 的占位别名，执行报「Python was not found」 | **不可用** |
| Node | `v22.22.2`，但路径为 `C:\Users\hanrui\.workbuddy\binaries\node\...`，非系统安装 | 仅工具内置 |
| npm | 不可用 | **不可用** |

## 3. 已知问题

| 编号 | 问题 | 影响 | 建议处理 |
| --- | --- | --- | --- |
| ENV-01 | `python -m unittest` 会失败，`python` 是 Microsoft Store 别名占位 | README 与文档里的示例命令在这台机器上跑不通，新人容易卡住 | 本机统一用 `py -m unittest`；或在「设置 → 应用 → 高级应用设置 → 应用执行别名」关闭 python.exe 别名后重装 Python |
| ENV-02 | 系统未安装 Node.js 和 npm，现有 Node 来自开发工具内置目录 | 前端 `npm install` / `vite dev` 无法执行，10/29 的响应式检查会阻塞 | 10/28 前安装 LTS 版 Node.js（自带 npm） |
| ENV-03 | 仓库尚无 `.gitattributes` | 换行符由各人本机设置决定，可能出现整文件被判定为修改的假 diff | 由仓库负责人统一添加 `* text=auto` 后再逐次提交，避免一次改动过多文件 |

## 4. 本次确认

- 仓库可从远端克隆，克隆后 `main` 分支与 `origin/main` 一致。
- 提交作者身份正确，能归属到本人 GitHub 账号。
- 现有 17 项单元测试在本机可复现通过，基线成立。
- 夜间行动、女巫用药、猎人开枪、自爆、投票、遗言等功能尚未实现，对应验收用例见 `docs/07_test_cases.md` 第 2 节，**当前无法执行**。

## 5. 下一里程碑

等待订书机实现夜间流程（狼队长选举、两轮狼人发言、刀人、预言家查验、女巫用药、夜间结算）后，执行 `docs/07_test_cases.md` 中的 TC-01 至 TC-07，并按同一格式追加执行记录。
