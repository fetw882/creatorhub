# CreatorHub 运营部团队版（feat/team-auth-dashboard）

## 角色
| 角色 | 能看 | 能做 |
|---|---|---|
| admin 管理员 | 全部账号、全部页面 | 全部操作、用户管理、设置 |
| manager 主管 | 全部账号（只读）、看板/概览/队列/风控 | 不能改账号/同步/删除/改设置/登录平台 |
| operator 运营 | 仅归属人=自己 owner_name 的账号 | 查看自己账号作品/私信、改自己账号标签 |
| viewer 只读 | 仅运营看板汇总（无私信内容/未读明细） | 无 |

## 路由权限（app/auth.py RULES）
- public：/api/auth/login、静态资源、首页
- any：/api/auth/me、logout、/api/dashboard（数据按角色收窄）
- scoped_list：账号/概览/私信收件箱等列表，运营自动过滤到自己的账号
- manager：只读类接口（主管及以上）
- acct_read / acct_write：带 account_id 的接口，运营仅限自己账号；写操作仅 tags
- admin：用户管理、设置、删除、同步、登录平台等；**未分类路由默认仅 admin**
- 所有 JSON 响应剥离 cookie/storage_state/password_hash/token_hash/proxy_password，代理 URL 密码脱敏为 `***`

## 启动与建管理员
```
python -m app.manage create-admin --username admin      # 交互输入密码
# 或首次启动时设置环境变量 CREATORHUB_ADMIN_PASSWORD（用完即删）
python -m app.manage create-user --username xx --role operator --owner-name 李枫林   # 可加 --password-file
```
会话 cookie `ch_session`（HttpOnly、SameSite=Lax、12h），登录失败 5 次/5 分钟锁定（按用户名和 IP）。

## 凭据加密状态
未启用。环境未安装 `cryptography`，且启用需改动 main.py 与采集引擎中所有 cookie/storage_state 读写点，风险高。
已提供：`app/credentials_crypto.py`（Fernet，`enc:v1:` 前缀，明文兼容读）与
`python -m app.manage encrypt-credentials --dry-run`（只统计明文行数，不改数据）。`--apply` 未实现。

## 上线前检查
- 必须 HTTPS（反代）并设置 `CREATORHUB_COOKIE_SECURE=1`
- 只放内网或 VPN，**不要暴露公网**
- 备份 DB 与 `auth-secret.key`（权限 600）
- 删除测试用户，改强密码

## 风险
- 上游仓库无 LICENSE，商用/再分发授权不明
- 自动化操作可能违反平台条款，存在账号封禁风险
- 登录锁定计数在内存中，重启清零；多进程部署不共享
