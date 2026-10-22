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
| `python` 命令 | 原为 Microsoft Store 占位别名；已将 `Python314` 与 `Python314\Scripts` 加入用户 PATH，现指向 `C:\Users\hanrui\AppData\Local\Programs\Python\Python314\python.exe` | **已修复** |
| pip | `pip 25.2`（随 Python 3.14 安装） | 可用 |
| Node | `v24.22.1`，系统安装于 `D:\Edge\node.exe`，已在 PATH | **已修复** |
| npm | `11.19.1`（随 Node 安装） | **已修复** |
| PowerShell 执行策略 | CurrentUser = `RemoteSigned`（原为 Undefined，导致 `npm.ps1` 被禁止执行） | **已修复** |

## 3. 已知问题

作用范围说明：**ENV-01 和 ENV-02 只影响本机（Hurry 的开发电脑），不是项目缺陷，也不影响仓库和别人的机器**；ENV-03 属于仓库级问题，影响所有人。

| 编号 | 问题 | 作用范围 | 影响 | 建议处理 |
| --- | --- | --- | --- | --- |
| ENV-01 | `python -m unittest` 会失败，`python` 是 Microsoft Store 别名占位 | 仅本机 | **已于 2026-10-22 修复**：把 `Python314` 和 `Python314\Scripts` 前置到用户 PATH，现在 `python -m unittest discover -s tests -v` 可直接执行并返回 17 项通过 | 修改前已备份用户 PATH 到 `%USERPROFILE%\path-user-backup-20261022.txt`，如需回退可直接恢复该文件内容 |
| ENV-02 | 系统未安装 Node.js 和 npm，现有 Node 来自开发工具内置目录 | 仅本机 | **已于 2026-10-22 修复**：安装 Node.js LTS 到 `D:\Edge`，现为 `v24.22.1` + `npm 11.19.1` | 前端初始化后可执行 `npm install` 与 `npm run dev` |
| ENV-04 | PowerShell 执行策略默认禁止运行 `.ps1`，`npm` 命令报「无法加载文件 …npm.ps1，因为在此系统上禁止运行脚本」 | 仅本机 | **已于 2026-10-22 修复**：设置 `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`（仅影响当前用户，无需管理员） | 如需回退：`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy Undefined`。若不想改策略，也可改用 `npm.cmd` 代替 `npm` |
| ENV-03 | 仓库尚无 `.gitattributes` | 全仓库 | 换行符由各人本机设置决定，可能出现整文件被判定为修改的假 diff | 由仓库负责人统一添加 `* text=auto` 后再逐次提交，避免一次改动过多文件 |

## 4. 本次确认

- 仓库可从远端克隆，克隆后 `main` 分支与 `origin/main` 一致。
- 提交作者身份正确，能归属到本人 GitHub 账号。
- 现有 17 项单元测试在本机可复现通过，基线成立。
- 夜间行动、女巫用药、猎人开枪、自爆、投票、遗言等功能尚未实现，对应验收用例见 `docs/07_test_cases.md` 第 2 节，**当前无法执行**。

## 5. 下一里程碑

等待订书机实现夜间流程（狼队长选举、两轮狼人发言、刀人、预言家查验、女巫用药、夜间结算）后，执行 `docs/07_test_cases.md` 中的 TC-01 至 TC-07，并按同一格式追加执行记录。
