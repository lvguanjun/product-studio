# Product Studio

面向电商场景的本地优先白底主图批量工作室（**速卖通白底主图 · 批量工作室**），基于 FastAPI 构建，通过 OpenAI 或任意 OpenAI 兼容的 `/images/edits` 接口（如 Cloudflare AI Gateway），将实拍商品图和手机/网页截图批量转换为纯白底主图。

## 核心功能

- **批量导入与并发出图**：支持拖拽、文件选择及 `Ctrl + V` 剪贴板粘贴导入 JPG / PNG / WEBP；支持 1–4 路并发、随时停止和失败项一键重试。
- **场景预设与提示词定制**：内置 4 套电商出图预设（速卖通白底主图、去手/杂乱实拍棚拍化、极简绝对纯白无阴影、3C/包装盒高质感白底），支持直接编辑并保存浏览器本地模板。
- **静默输入预处理**：生成前自动完成 EXIF 方向校正、透明底铺白转 RGB、高像素长边上限 `2048px` 等比压缩并以高质量 JPEG（`quality=95`）上传，无需手动维护优化开关。
- **跨浏览器全局默认设置**：高级设置支持单页临时调参，点击「设为全局默认」后持久化至本地输出目录 `.settings/`，对所有浏览器生效。
- **棚拍质检与细节对比**：提供纯白 / 棋盘格 / 暗房深灰三种检视底板、80% 主图安全框参考线，以及原图与白底成品的滑块叠加对比。
- **多规格导出与历史管理**：支持 `1000x1000`、`800x800` 与模型原生 `1024x1024` 尺寸，导出 PNG / JPG / WEBP，持久化保存至本地输出目录，支持历史浏览与一键打包 ZIP。
- **访问鉴权与月度预算熔断**：全站启用 HTTP Basic Auth（`/healthz` 除外）；按 API Key 指纹和自然月在本地 `.balance/` 账本中实时估算消费，低于阈值时预警或自动暂停生图（返回 `402`）。

## 快速开始

### 环境要求

- Python `>= 3.11`（推荐 `3.12`，见 `.python-version`）
- [uv](https://docs.astral.sh/uv/)
- Node.js（可选，仅运行前端 JS 单元测试时需要）

### 本地运行

1. 安装依赖：

   ```bash
   uv sync --locked
   ```

2. 配置环境变量：

   ```bash
   cp .env.example .env
   ```

   在 `.env` 中填入必填的 `API_KEY`（或 `OPENAI_API_KEY`）与 `ACCESS_KEY`。

3. 启动服务：

   ```bash
   ./start.sh
   # 或直接使用 CLI
   uv run product-studio
   ```

   CLI 支持 `--host`、`--port` 和 `--reload` 参数，例如：

   ```bash
   uv run product-studio --host 127.0.0.1 --port 8765 --reload
   ```

4. 浏览器访问 `http://127.0.0.1:8765`，在 Basic Auth 弹窗中将**用户名和密码均填写为 `ACCESS_KEY`**。

## Docker 部署

项目提供多架构容器镜像（`linux/amd64`、`linux/arm64`），推送到 `main` 或发布 `v*` 标签时由 GitHub Actions 自动构建并发布至 GHCR。

### 使用 Docker Compose（推荐）

1. 准备 `.env`（至少配置 `API_KEY` 和 `ACCESS_KEY`）：

   ```bash
   cp .env.example .env
   ```

2. 启动容器：

   ```bash
   docker compose up -d
   ```

默认配置会：

- 拉取 `ghcr.io/lvguanjun/product-studio:latest`
- 将容器 `8765` 端口映射到宿主机回环地址 `127.0.0.1:${HOST_PORT:-8765}`
- 将 `./outputs` 挂载到容器 `/app/outputs` 以持久化成品图、元数据与余额账本
- 通过 `/healthz` 执行健康检查，并以非 root 用户 `appuser` 运行服务

### 本地构建镜像

```bash
docker build -t product-studio .
```

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `API_KEY` | 是* | - | 上游生图 API Key（也兼容 `OPENAI_API_KEY`） |
| `ACCESS_KEY` | 是 | - | HTTP Basic Auth 共享密钥（用户名与密码相同；未配置时除 `/healthz` 外返回 `503`） |
| `OPENAI_BASE_URL` | 否 | `https://api.openai.com/v1` | 覆盖上游 OpenAI 兼容网关 Base URL（如 Cloudflare AI Gateway） |
| `CF_AIG_TOKEN` | 否 | 空 | 可选，配置后自动附加 `cf-aig-authorization: Bearer <token>` 请求头（用于开启鉴权的 Cloudflare AI Gateway） |
| `HOST` | 否 | CLI `127.0.0.1` / 容器 `0.0.0.0` | 服务监听地址 |
| `PORT` | 否 | `8765` | 服务监听端口 |
| `HOST_PORT` | 否 | `8765` | `docker-compose.yml` 宿主机映射端口 |
| `OUTPUT_DIR` | 否 | `./outputs`（容器 `/app/outputs`） | 成品图、JSON 元数据、`.balance/` 账本及 `.settings/` 全局默认配置存储目录 |
| `MONTHLY_BUDGET_USD` | 否 | `25` | 单个 API Key 每月估算预算上限（美元） |
| `BALANCE_WARN_THRESHOLD_USD` | 否 | `5.0` | 余额预警阈值（美元） |
| `BALANCE_DISABLE_THRESHOLD_USD` | 否 | `1.0` | 熔断阈值（美元），估算余额低于或等于该值时暂停生图 |
| `BILLING_TIMEZONE` | 否 | `UTC` | 月度预算重置使用的 IANA 时区名称 |
| `BALANCE_USED_OFFSET_USD` | 否 | `0` | 手动补录当前账单月的外部消费金额（美元） |
| `BALANCE_USED_OFFSET_MONTH` | 否 | 空（所有月份生效） | 限定 `BALANCE_USED_OFFSET_USD` 生效的月份，格式 `YYYY-MM` |

> 说明：预算与余额基于模型单价和接口返回的 `usage` 字段在本地估算，未返回 `usage` 时按单张 `$0.04` 兜底估算，实际账单以上游控制台为准。

## 主要 API

除 `GET /healthz` 外，所有接口均需通过 Basic Auth 认证。

| 方法与路径 | 说明 |
| --- | --- |
| `GET /` | 返回 Web 工作台页面 |
| `GET /healthz` | 健康检查（免认证），返回 `{"status": "ok"}` |
| `GET /api/config` | 返回可用模型、场景预设、出厂/全局默认设置、网关状态与当前余额信息 |
| `PUT /api/settings` | 保存服务端全局默认设置（模型、画质、并发数、导出尺寸与格式） |
| `GET /api/balance` | 查询当前 API Key 的月度预算与估算余额 |
| `POST /api/generate` | 上传原图并调用模型生成白底成品图，持久化图片与元数据 |
| `GET /api/outputs/{filename}` | 获取已生成的成品图文件 |
| `GET /api/history?limit=40` | 获取历史生成记录（按创建时间倒序） |
| `POST /api/download-zip` | 传入 `{"filenames": [...]}` 批量打包下载成品图 ZIP |

## 项目结构

```text
.
├── src/product_studio/
│   ├── app.py          # FastAPI 应用工厂、路由、图片预处理/后处理与鉴权中间件
│   ├── balance.py      # 月度预算估算、本地账本与阈值熔断逻辑
│   ├── settings.py     # 服务端全局默认设置的校验与持久化存储
│   ├── cli.py          # product-studio CLI 入口
│   └── static/         # 前端工作台（HTML / CSS / JS）
├── tests/              # pytest 后端与 Node.js 前端逻辑测试
├── docker/             # 容器入口脚本
├── docs/               # 架构决策记录（ADR）与开发文档
├── GLOSSARY.md         # 领域术语表
├── Dockerfile
├── docker-compose.yml
└── start.sh
```

## 开发与校验

与 `.github/workflows/ci-docker.yml` 保持一致的本地校验命令：

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

若本机未安装 Node.js，可跳过标记为 `node` 的前端逻辑测试：

```bash
uv run pytest -m "not node"
```
