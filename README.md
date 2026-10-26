# “笨”人学习

AI 课后复习与查漏补缺平台。围绕用户上传的学习材料，提供处理与校正、结构化笔记、知识图谱、客观测验、错题重练、引导式 Tutor，以及复习计划和内部日历。

本仓库公开前后端源码、数据库迁移、提示词和测试，供阅读与本地开发。线上邀请试点入口为 [“笨”人学习](https://sr9rtrj3qbdm2junbffg4.apigateway-cn-beijing.volceapi.com/login)。线上邀请码、生产配置和学习数据不随源码提供。

## 直接看源码

- [后端 API 与业务逻辑](backend/app/)
- [Provider 接入](backend/app/providers/)
- [任务提示词](backend/app/prompts/)
- [前端页面](frontend/app/)与[功能模块](frontend/features/)
- [数据库迁移](backend/alembic/)
- [后端测试](backend/tests/)与[前端测试](frontend/tests/)

## 技术栈

- 前端：Next.js、React、TypeScript。
- 后端：Python 3.11、FastAPI、SQLAlchemy、独立 Worker。
- 本地数据：SQLite 与本地文件；生产部署代码支持 S3 兼容对象存储与备份。
- 模型与解析：可配置 DeepSeek / OpenAI-compatible LLM、火山 ASR/OCR；本地配置默认使用 Mock Provider，供开发与合同测试。

## 本地启动

需要 Python 3.11、[uv](https://docs.astral.sh/uv/) 和 Node.js。请按前端锁文件安装依赖。

```bash
git clone https://github.com/turetegeblocfaun-star/benren-learning.git
cd benren-learning
cp .env.example .env
cd backend
uv sync --frozen
```

本地也使用邀请码登录。先生成自己的邀请码 Hash：

```bash
uv run python scripts/hash_invite.py
```

根据提示输入自定义邀请码，将输出的 Hash 填入根目录 `.env` 的 `INVITE_CODE_HASHES` JSON 数组，并为 `SESSION_SIGNING_KEY` 设置独立的随机值。`.env.example` 中的 Provider 默认配置可用于本地 Mock 开发；接入真实服务时再填写自己的凭据。

初始化数据库并启动 API：

```bash
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8100
```

另开终端启动后台 Worker：

```bash
cd benren-learning/backend
uv run python -m app.worker
```

再开终端启动前端：

```bash
cd benren-learning/frontend
cp .env.example .env.local
npm ci
npm run dev
```

- 本地页面：<http://127.0.0.1:3100/login>
- 本地 API 文档：<http://127.0.0.1:8100/docs>
- 本地健康检查：<http://127.0.0.1:8100/api/v1/health>

## 验证

后端：

```bash
cd backend
uv run ruff check .
uv run mypy app
uv run pytest -q
```

前端：

```bash
cd frontend
npm run typecheck
npm run lint
npm run test -- --run
```

浏览器联调测试与真实 Provider 冒烟需要自行准备相应环境；相关入口在 `frontend/e2e/` 和 `backend/scripts/`。

## 当前边界

本次公开的是本地工程源码快照，包含 Tutor 来源引用和 PDF 笔记模型路由修复。线上实例的配置与发布进度应单独核对。外部日历、通知、官方联网和 SFT 由后端配置与授权条件控制；未配置时不代表可以直接使用。
