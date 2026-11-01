# 程序组bot

内部 QQ bot：监控 GitHub 私有仓库（提交 / PR / release），通过 OneBot v11 + Lagrange 推送到指定 QQ 群与个人，并支持 @bot / 私聊指令查询。

- **监控仓库**：`Jimmyxiao2009/FanShengJing`（私有，依赖本机 `gh auth login` 登录态）
- **协议**：OneBot v11 反向 WebSocket（bot 是 WS 服务端，Lagrange 是客户端）
- **通知规则**：新提交 / 新 PR / 新 release（nightly 与 draft 除外）；新 release 若挂了附件，文字通知发出后会自动把附件也逐个发到同样的群/私聊（最多 5 个，跟 `file` 指令共用下载/上传逻辑）
- **可靠性**：消息全部发送成功才推进水位，失败下轮自动补发；gh 故障指数退避（60s→5min 封顶），不丢事件

## 一、首次部署

### 1. 安装依赖（已完成可跳过）

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

### 2. gh 登录（私有仓库必需）

```bash
gh auth login        # 浏览器登录，协议选 https
gh auth status       # 确认已登录 Jimmyxiao2009
```

### 3. 配置 .env

从模板创建并填写（自检脚本也会自动帮你复制模板）：

| 键 | 说明 |
|---|---|
| `ONEBOT_ACCESS_TOKEN` | WS 握手凭据（任意随机串），**必须与 Lagrange 端 AccessToken 一致** |
| `GITHUB_REPO` | 已填 `Jimmyxiao2009/FanShengJing` |
| `NOTIFY_GROUP_IDS` | 公开大群、程序组群群号，JSON 数组或逗号分隔，如 `[123, 456]` |
| `NOTIFY_USER_IDS` | 需要私收通知的个人 QQ 号 |
| `GITHUB_POLL_INTERVAL` | 轮询间隔秒数，默认 60 |

### 4. Lagrange 端配置

在 Lagrange.OneBot 的 `appsettings.json` 中：

```json
{
  "Implementations": [
    {
      "Type": "ReverseWebSocket",
      "Host": "127.0.0.1",
      "Port": 8080,
      "Suffix": "/onebot/v11/ws",
      "ReconnectInterval": 5000,
      "HeartBeatInterval": 5000,
      "AccessToken": "与 .env 的 ONEBOT_ACCESS_TOKEN 完全一致"
    }
  ]
}
```

然后正常启动 Lagrange 并登录 bot 的 QQ 号（扫码或密码）。bearer token 只是 bot ↔ Lagrange 之间的握手凭据，不替代 QQ 登录。

### 5. 启动

- 双击 `start.bat`（先自检再启动），或
- 命令行：`python bot.py`

### 6. 验证

群里 @bot 发 `ping` → 应回 `pong`；发 `help` → 回指令清单。

## 二、指令

| 指令 | 触发方式 | 响应 |
|---|---|---|
| `ping` | 群 @ 或私聊 | `pong` |
| `help` / `帮助` | 同上 | 指令清单 |
| `release` / `发布` | 同上 | 最新正式发布 + 最新预发布（各一条，缺失显示"暂无"） |
| `file` / `文件` | 同上 | 下载最新 release 的附件并发到当前会话（最多 5 个，无附件时给下载页链接） |
| `commits [n]` / `提交` | 同上 | 最近 n 条提交（1-10，默认 5） |
| `pr` | 同上 | 开放 PR 列表（≤10） |

同一会话 5 秒内重复查询会被防抖忽略。

## 三、通知样例

```
【程序组bot】新提交 · Jimmyxiao2009/FanShengJing @ main
chore: 更新战斗数值 — Jimmyxiao2009
时间: 2026-08-15 14:00
https://github.com/Jimmyxiao2009/FanShengJing/commit/<sha>
```

新 release 挂了附件时，这条文字通知发完之后会紧接着把每个附件当文件消息发过去（群用 `upload_group_file`，私聊用 `upload_private_file`），不需要额外去问 bot 要。附件下载失败不会影响文字通知已经发出去这件事，但这条 release 的水位不会推进，下一轮会重试（文字通知可能因此重复发一次）。

## 四、运维

- **状态文件**：`data/state.json`（水位）。删除后重启 = 重建基线，不会重发历史事件（首轮只记录不发通知）
- **日志**：控制台实时输出；`.env` 里 `LOG_TO_FILE=1` 后写 `logs/bot.log`（10MB 轮转 ×10 份）。token 永远脱敏
- **自检**：`python scripts/check_env.py`（Python/.env/端口/gh 登录逐项检查）
- **测试**：`.venv/Scripts/python -m pytest tests/ -q`（39 个用例，含伪 Lagrange WS 端到端）

### 开机自启（可选）

任务计划程序 → 创建基本任务 → 触发器“登录时” → 操作启动 `start.bat`。建议先给 Lagrange 也建一个同样的任务（或用一个包装脚本按顺序拉起两者）。

## 五、安全红线

- `.env`、`data/`、`logs/` 已在 `.gitignore`，**绝不入库**
- `ONEBOT_ACCESS_TOKEN` 泄露 = bot 控制权，请勿外传；错误 token 的连接会被 403 拒绝并记日志
- 群发限频：默认每 60s 一轮轮询，仅在有新事件时发送，无风险

## 六、故障排查

| 现象 | 处理 |
|---|---|
| Lagrange 连不上 | 确认两端口令一致、bot 先启动、`PORT` 未被占用 |
| 收不到通知 | 看 `data/state.json` 是否已基线；`gh auth status` 是否登录；日志有无 `发送到群 … 失败` |
| `gh 未登录` 报错 | 运行 `gh auth login`；bot 会自动退避重试，恢复后补发 |
| 重复收到同一条 | 属于补发机制的预期代价（at-least-once）；若某目标长期失败，检查该群号/好友关系 |
