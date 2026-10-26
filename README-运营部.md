# CreatorHub 运营部版（fork：fetw882/creatorhub，分支 feat/account-owner-tags）

在上游 CreatorHub 基础上，给账号增加 **归属人（owner）** 和 **标签（tags）**，用于运营部按人、按标签管理账号。
仅限本机使用，不要部署到公网（原因见「已知限制」）。

## 一、本地启动（一步步）

### 0. 准备
- Python 3.10 或更新版本（命令行运行 `python3 --version` 或 Windows 上 `py -3 --version` 检查）
- Git
- （只有改前端代码才需要）Node.js 18+

### 1. 下载代码
```bash
git clone -b feat/account-owner-tags https://github.com/fetw882/creatorhub.git
cd creatorhub
```

### 2. 一键启动（推荐）
| 系统 | 操作 |
|---|---|
| Mac / Linux | 终端执行 `sh start.sh` |
| Windows | 双击 `start.cmd`（或在 cmd 里运行 `start.cmd`） |

首次启动会自动安装依赖、生成 `config.yaml`，之后浏览器打开 **http://127.0.0.1:8765**。

### 3. 手动启动（一键脚本失败时）
Mac / Linux：
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml        # 按需修改
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```
Windows（PowerShell）：
```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy config.example.yaml config.yaml
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```
用测试配置/测试数据启动时，先设环境变量 `CREATORHUB_CONFIG_PATH`：
- Mac/Linux：`CREATORHUB_CONFIG_PATH=/路径/config.test.yaml .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765`
- Windows PowerShell：`$env:CREATORHUB_CONFIG_PATH="C:\路径\config.test.yaml"; .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8765`

### 4. 使用
1. 打开 http://127.0.0.1:8765 ，进入「账号」页。
2. 表格列：账号 / 归属人·标签 / 状态 / 操作。
3. 顶部两个下拉框：按归属人筛选、按标签筛选。
4. 某行「更多」→「归属/标签」打开编辑弹窗：归属人可从已有名单选或直接填写；标签用逗号分隔，也可点下方已有标签快速添加；点「保存」。

### 5. 改前端后重新构建（可选）
```bash
npm install
npm run build:ui
```

## 二、字段说明
| 字段 | 类型 | 说明 |
|---|---|---|
| owner（归属人） | 文本，最长 40 字 | 账号负责人。空 = 无归属人 |
| tags（标签） | 文本列表，每个最长 24 字 | 例如 主号、美妆。库内以 JSON 存储，自动去重 |

旧数据库启动时会自动补这两列，无需手工迁移。

接口：
- `GET /api/accounts?platform=douyin&owner=张三&tag=美妆` —— 列表，owner/tag 可选，精确匹配
- `PATCH /api/accounts/{id}`，body `{"owner":"张三","tags":["主号","美妆"]}` —— 字段不传 = 不修改；传空字符串/空数组 = 清除；账号不存在返回 404

## 三、已知限制
- **无登录、无权限**：任何能访问 8765 端口的人都能看到/操作所有账号。只能绑 127.0.0.1，不能多人共用（多人登录与权限属第二阶段）。
- **敏感信息明文**：Cookie、登录态、代理密码明文存在本地 SQLite，电脑丢失或被他人使用即泄露。
- **授权**：上游仓库没有 LICENSE，默认保留所有权利，内部使用前建议确认授权。
- **平台风险**：项目含绕过平台风控的签名/指纹相关代码，使用有违反平台条款、被封号的风险。
- 筛选只支持单个归属人 + 单个标签，精确匹配；标签在内存中过滤，账号很多时会稍慢。
- 「归属/标签」按钮在「更多」菜单里；窄屏（≤860px）下表头隐藏，改为卡片布局。
- 首次打开会弹出新手引导，关掉后不再出现。
