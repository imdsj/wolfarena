# 预成果验收清单 · 2026-10-30

按赛事预成果验收逐项核对。每一项都标了证据来源和当前状态。

| 项目 | 通过标准 | 状态 | 证据 |
| --- | --- | --- | --- |
| 仓库 | 未登录可访问，README 含安装/测试/启动/限制 | 通过 | GitHub 仓库已公开，匿名访问 200；README 含运行与边界说明 |
| 页面 | 健康检查 200、页面可打开、WebSocket 可连接 | 通过 | `deploy/smoke.py` 输出 `ALL CHECKS PASSED`（health 200 / home 200 / ws 玩家+观战认证成功 / 坏令牌拒绝） |
| 核心玩法 | 至少一局 INIT→END，AI 自动补位 | 通过 | 新增测试 `test_idle_human_night_role_reaches_end_via_autoplay`：真人狼人不操作，600 次超时推进到 END |
| 多人 | 1–3 名真人，第 4 名按设置拒绝 | 通过 | `test_default_room_allows_three_humans_and_rejects_the_fourth` |
| 权限 | 玩家无狼聊/他人身份/死因；观战密码独立；死亡视角不升级 | 通过 | `test_good_player_only_sees_their_own_role`、`test_wolf_player_only_sees_wolf_roles`、`test_player_wolf_and_spectator_views_are_different`、`test_death_causes_are_hidden_from_players`、`test_dead_wolf_keeps_own_role_but_not_teammate_roles` |
| 手机 | 390px 可完成主要路径，无横向滚动 | 待验 | 需要真实浏览器在 390px 视口复测，尚无截图证据 |
| 模型 | 无 Key/超时/非法 JSON 有兜底，不修改非法状态 | 通过 | `test_ai_provider.py`：无 Key 本地兜底、超时重试后兜底、非法 JSON 修复一次、非法动作不改变阶段 |
| 训练证据 | L0/L1 200 局可复算；L2 如实说明 | 通过 | `2026-10-29_l2_train_eval_200.md`、`2026-10-29_l2_qtable_v2_expanded_state.md`；L0/L1 动作哈希逐字节可复现，L2 明确 No-Go |
| 视频 | 3 分钟 MP4，普通话，体现真实页面和限制 | 未开始 | 待录制 |
| 安全 | 无 .env、Key、密码、真人和未脱敏数据 | 通过 | `git ls-files .env` 为空；提交树无 `sk-`/`ghp_`/`gho_`/私钥模式；仓库公开前已扫描 |

## 本次阻断修复

真人被分到夜晚角色或轮到自己投票时不操作，会卡死整局。已修复：
夜晚动作与投票增加 20 秒服务端截止时间，到期用 L0 策略替真人执行一步
合法动作并继续推进。详见
`docs/evidence/2026-10-30_human_idle_timeout_fix.md`。提交 `91a8819`。

## 公网地址口径

- 对外统一使用 `http://106.14.113.216:8080/`，**必须带 `:8080`**。
- 80 端口 `http://106.14.113.216/` 返回的是另一个项目，不能写进材料。
- 公网冒烟与干净环境克隆的结论见 `2026-10-30_prerelease_check.md`（Hurry）。

## 提交回执（待项目负责人完成）

- commit：`4f3e59f`（Hurry 预发布检查之后的最新 main；提交前请再核对一次）
- tag：`v0.10-pre-result`（指向 `b25e6b7`，为冻结候选；阻断修复与夜间节奏在其后的 main）
- 仓库 URL：`https://github.com/imdsj/wolfarena`
- 手机端 M-02：390×844 窗口可正常游玩，截图证据仍待补
- 视频文件名与哈希：待录制后填写
- 提交时间与回执位置：以赛事个人中心为准，回执只存团队私密位置，不入库
