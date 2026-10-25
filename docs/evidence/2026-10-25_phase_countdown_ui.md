# 浏览器倒计时接入证据

日期：2026-10-25

代码提交：`631a475`

交接文档提交：`88381eb`

## 实现范围

`RoomSnapshot` 增加四个服务端字段：

```text
server_time
deadline_at
deadline_kind
remaining_ms
```

`deadline_kind` 只允许 `last_words`、`speech`、`self_destruct`。读取当前截止时间
的规则与后台超时扫描复用同一阶段判断，避免网页显示与服务端推进使用不同来源。

Vue 新增 `PhaseCountdown.vue`。组件以快照剩余毫秒为锚点，使用浏览器单调时钟
递减显示；到达零后显示“等待服务端推进”，不会修改阶段或代替后台计时器。

## 验证结果

测试环境：仓库内 `.venv` 与 `frontend/node_modules`。

```text
命令：.\.venv\Scripts\python.exe -m unittest discover -s tests -q
结果：Ran 174 tests in 1.013s
结论：OK
```

```text
命令：npm run build
结果：Static Vue build written to frontend\dist
结论：TypeScript 检查和静态构建通过
```

```text
命令：$env:WOLFARENA_BASE_URL='http://127.0.0.1:8010'; npm run smoke:client
结果：
  createdPhase=等待开始
  roomIdDisplayedExactly=true
  hostUpdatedAfterJoin=true
  phaseAfterAction=首夜狼队讨论
  connectionText=已连接
  countdownLabel=服务端截止时间公开发言倒计时2.3秒
  countdownDecreased=true
结论：通过
```

服务端启动时仅为本地冒烟会话清空 `DEEPSEEK_API_KEY`，未读取或输出真实密钥。

## 提交与远端核对

```text
代码提交：631a475 feat: show server-authoritative phase countdown
文档提交：88381eb docs: record countdown evidence and next P0
远端 main：88381ebf6e48839b11f36555a78ba9d0cb24f631
标签：v0.9.12.2-countdown-ui
```

本次沙箱不能写入 E 盘仓库的 `.git`。提交与推送通过临时 Git 元数据完成，使用
远端 URL 临时传入已缓存凭证，未写入文件或输出凭证。远端 `refs/heads/main` 和
标签已用带认证的 `git ls-remote` 复核。

## 验收边界

本次证明的是：

1. 服务端快照能根据三种真实截止字段生成倒计时数据。
2. 超时扫描和倒计时展示使用同一截止来源。
3. 编译后的 Vue 组件在 DOM 环境中显示倒计时并真实递减。

本次没有证明：

1. 完整九人局网页从创建到胜负的端到端脚本已通过。
2. 浏览器人工录屏中的 30 秒发言、30 秒遗言和 10 秒自爆窗口均与阶段切换误差
   小于 1 秒。
3. 刷新恢复、独立观战页、死亡视角、赛后结算和 390px 完整验收已完成。

下一项 P0 是刷新恢复：

- 保存房间号与玩家 Token。
- 恢复时验证凭证和房间是否存在。
- 恢复座位、身份、阶段和事件。
- 重建 WebSocket。
- 凭证无效时清除本地会话并明确提示。
