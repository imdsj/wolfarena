# 11 月 3 日冻结验证

日期：2026-11-03

执行人：Hurry

代码：远端 main `172080b`（`docs: add 11-03 three-minute visual storyboard`）

## 一、冻结标签（今日第一优先）

### 1.1 标签已存在

```text
GitHub API /repos/imdsj/wolfarena/tags
→ v0.11-training-evidence  →  0f22874
```

tag 总数 42，`v0.11-training-evidence` 已在远端。**此前「标签缺失」的结论已失效，该项闭环。**

> 说明：11-02 我用 `git ls-remote --tags` 查询时因网络中断（`CONNECT tunnel failed`）返回空结果，误判为「标签不存在」。实际是命令失败而非标签缺失。本轮改用 API 查询，确认存在。这是查询方法的失误，不是订书机的问题。

### 1.2 标签指向与当前 HEAD 的差距

```text
标签提交：0f22874  docs: finalize 11-02 freeze manifest and defense rehearsal（11-02 20:25）
当前 HEAD：172080b  docs: add 11-03 three-minute visual storyboard（11-03 14:37）
ahead_by 2，behind_by 0
```

标签之后的 2 个提交，改动文件仅两份：

```text
added  docs/evidence/2026-11-03_video_selfcheck.md      (+32)
added  docs/evidence/2026-11-03_visual_storyboard.md   (+112)
```

**无任何代码、测试、模型、配置改动。**

判定：**冻结有效。** 标签指向 11-02 的代码状态，之后的提交只增文档，代码层面与标签一致。若最终提交要求「标签即交付版本」，可说明「标签后仅有文档补充，代码零变更」。

## 二、完整测试

`git clone` 本轮被网络阻断（三次均 `CONNECT tunnel failed, response 502`），改用 GitHub API 下载 `main` 压缩包（752 KB，`imdsj-wolfarena-172080b/`）后测试。

```text
python -m unittest discover -s tests
Ran 234 tests in 2.728s
OK
```

**判定：通过。234 项与 11-02 一致，无新增失败。**

## 三、公网 smoke

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

## 四、敏感信息扫描

对象：`172080b` 快照全部文件。

| 检查项 | 结果 |
| --- | --- |
| 密钥特征（`sk-` / `ghp_` / `AKIA`） | **0 个文件命中** |
| `.env` / `*.key` / `*.pem` / `id_rsa*` | **0 个** |
| 手机号（11 位，排除十六进制上下文） | **0 处** |
| `C:\Users\dings` 绝对路径 | **0 处** |
| `C:\Users\hanrui` 绝对路径 | **1 处，已修**（见下） |

### 4.1 手机号扫描的误报说明

初版正则在 `2026-10-28_l2_*` 的 manifest/summary 中命中 6 处形如 `1[3-9]\d{9}` 的串，逐一核对后确认**全部是 SHA-256 哈希的中间片段**，例如：

```text
模型内容哈希：e59dc5b0ee14640355271bfe234ead337bd1fdaef1f346512ed30234011ea27b
                         ^^^^^^^^^^^ e14640355271b
```

排除十六进制上下文后重新扫描，**0 处命中**。仓库中不存在手机号。

### 4.2 处理的一处路径

`docs/evidence/2026-10-22_env_and_test_baseline.md` 中记录 Python 路径时写入了真实用户目录：

```text
修改前：C:\Users\hanrui\AppData\Local\Programs\Python\Python314\python.exe
修改后：C:\Users\<user>\AppData\Local\Programs\Python\Python314\python.exe
```

已在本轮提交中替换为占位符。

## 五、今日结论

| 任务单项 | 结果 |
| --- | --- |
| 等推送 | **完成**，远端 `172080b` |
| 完整测试 | **234 项通过** |
| 公网 smoke | **ALL CHECKS PASSED** |
| 标签 `v0.11-training-evidence` | **存在**，指向 `0f22874`；之后仅 2 份文档，代码零改动 |
| 敏感信息 | **无密钥、无手机号、无 dings 路径**；1 处 hanrui 路径已修 |

```text
可以对外说：代码已冻结并打标签；234 项测试通过；公网 :8080 冒烟全部通过；
            仓库无密钥与个人信息。
不能说：视频内容已通过（画面与音频仍待人工审核）。
```

## 六、留给 11-04 / 11-05

1. **视频画面与音频审核**（11-04 主任务）：我无法观看视频，此项必须由真人完成。仓库新增的 `2026-11-03_video_selfcheck.md` 是自查表，需祁楷逐项确认。
   - 注意：订书机已说明「本次参考片不是我们的成片」，需确认**最终成片**的链接，否则审核对象不明确。
2. **交付包一致性核对**（11-05）：作品介绍、README、evidence 中的链接、数字、限制描述需三处一致。
3. **回执**：订书机仍在走流程，未提交。

## 七、本次未做的事

- 未观看视频，未对内容作任何通过判断。
- 未创建或推送 tag（订书机已完成）。
- 未修改 `backend/`、`frontend/`、`strategy_library/`。
- 未改写 Git 历史。
