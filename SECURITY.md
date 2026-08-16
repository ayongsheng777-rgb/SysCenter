# 安全说明

感谢你对 SysCenter 安全的关注。本项目用于管理服务器、网络资产与自动化流程，安全至关重要。

## 认证模型

- **TOTP 双因素认证**：登录用 RFC 6238 动态码（Google Authenticator / 1Password / Authy 兼容）。
- **会话令牌**：登录成功后签发 HMAC-SHA256 签名的 Bearer 令牌，存于 Redis（带 TTL）。登出即吊销。
- **RBAC**：`require_role(*roles)` 对高危路由做角色护栏；当前为单管理员（admin），已预留多用户扩展点。

## 已知安全边界

- **公网必须 HTTPS**：本项目默认 HTTP（因纯 IPv6 环境 80/443 被封）。对外请使用 Cloudflare Tunnel / Access 等，形成「HTTPS 隧道 + OTP 双重门禁」。
- **弱口令**：`.env` 中的 `PG_PASSWORD` 请设为强密码；启动时会对默认/占位弱口令告警。
- **密钥不落库**：OTP 密钥、飞书 Secret、AI Key 等敏感信息不入库、不入 Git；`DATA_DIR` 下的密钥文件已被 `.gitignore` 屏蔽。

## 报告漏洞

若发现安全问题，请勿公开披露，直接提交私有 issue 或联系维护者，附上：

1. 受影响模块与版本
2. 复现步骤
3. 影响评估

我们会在确认后尽快修复并发布更新。
