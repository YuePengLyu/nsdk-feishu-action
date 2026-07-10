# nsdk-feishu-action

每日定时获取 [nsdk.top](https://nsdk.top/) 纳指基金估值数据，推送到飞书。

## 架构

- **GitHub Actions** 定时触发（每天北京时间 8:30）
- Python 脚本调用 nsdk.top API 获取估值数据
- 通过飞书 Open API 发送消息

## 需要的 GitHub Secrets

| Secret | 说明 |
|--------|------|
| `FEISHU_APP_ID` | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret |
| `FEISHU_OPEN_ID` | 接收消息的用户 Open ID |
