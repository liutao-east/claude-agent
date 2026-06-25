# Code Q&A Service

基于 **Claude Agent SDK** 的多场景智能问答服务，**内置 Web 界面**，HTTP 即可调用。

它围绕一个核心理念设计:**对内**让 Agent 精确阅读代码 / 日志 / 数据库来定位事实,**对外**只用业务语言给出结论——面向前端、测试等**非后端使用者**,不暴露后端源码、文件路径、日志原文、SQL 等实现细节。

## 特性

- 🖥️ **内置 Web 界面** — 启动后浏览器打开首页即可使用,支持场景切换、多会话管理、流式渲染。
- 🧩 **多场景** — `config.json` 声明若干场景,各带独立提示词 / 工作目录 / 允许工具 / 模型,请求时按名选用。
- 🔒 **只读安全** — Agent 以 `default` 权限模式运行,默认仅 `Read / Glob / Grep / Bash`,不修改任何文件。
- 💬 **多轮追问** — 每轮回答自动持久化到 **SQLite**,服务重启后仍可续接上下文。
- 📡 **流式输出** — `/ask_stream` 以 SSE 逐 token 推送。
- 🚫 **业务化输出** — 自带两个场景都约束 Agent:查到的实现细节不外泄,只给对接契约与业务结论。

## 内置场景

| 场景 | 面向 | 做什么 | 对外输出 |
| --- | --- | --- | --- |
| **`code-qa`** 代码问答 | 前端工程师 | 查阅后端代码,解释接口怎么对接、有什么行为 | HTTP 路径与方法、请求/响应字段、错误码、状态流转(**不输出源码/路径/类名**) |
| **`troubleshoot`** 问题排查 | 前端等非后端使用者 | 依据**日志 + 代码 + 只读 MySQL** 定位线上问题 | 业务化根因 + 定位线索(traceId/时间点/接口路径)+ 处理建议(**不输出日志原文/堆栈/SQL**) |

> 两个场景共同边界:查到的代码、日志、数据仅用于 Agent 内部定位;回答中不出现源码、文件路径、异常堆栈、表名字段等实现细节。

## 快速开始

```bash
# 1. 安装 uv(极速 Python 包管理器)
#    macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
#    Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 创建环境并安装依赖(读取 pyproject.toml)
uv python install 3.10
uv venv --python 3.10
uv sync

# 3. 复制配置并填入真实值
cp config.json.example config.json      # 业务配置
cp agent.env.json.example agent.env.json # 部署配置(含密钥)

# 4. 启动
uv run python server.py
```

启动后默认监听 `http://0.0.0.0:8000`:

- 🌐 **浏览器打开首页** → 直接使用 Web 界面
- 🔍 `GET /health` → 查看当前配置

## 配置

配置拆成两份文件:**业务配置**(可团队共享)与**部署配置**(含密钥,已被 `.gitignore` 忽略)。

### `config.json` — 业务配置

```jsonc
{
  "project_dir": "/path/to/your/project",  // Agent 默认工作目录(被分析的项目代码)
  "host": "0.0.0.0",
  "port": 8000,
  "log_level": "INFO",
  "db_path": "codeqa.db",
  "default_scenario": "code-qa",

  "scenarios": [
    { "name": "code-qa", "description": "代码问答",
      "system_prompt_file": "scenarios/code_qa.md" },

    { "name": "troubleshoot", "description": "项目问题排查",
      "system_prompt_file": "scenarios/troubleshoot.md",
      "cwd": "/path/to/your/project",            // 代码目录
      "add_dirs": ["/data/logs/neo-star"],       // cwd 之外的日志目录
      "model": "opus",                            // 场景级模型(可写别名 sonnet/opus/haiku)
      "env": { "API_TIMEOUT_MS": "6000000" },     // 场景级覆盖全局 env 的同 key
      "vars": { "LOG_DIR": "/data/logs/neo-star", "DATABASE": "neo_star" },
      "allowed_tools": ["Read","Glob","Grep","Bash","mcp__mysql__mysql_query"],
      "mcp_servers": { /* 只读 MySQL 查询,见下 */ } }
  ]
}
```

**场景字段速查**:

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `system_prompt_file` / `system_prompt` | 必填其一 | 提示词文件(相对 `server.py` 目录)/ 内联字符串 |
| `cwd` | `project_dir` | Agent 工作目录 |
| `add_dirs` | `[]` | cwd 之外允许访问的目录(如日志目录) |
| `allowed_tools` | `["Read","Glob","Grep","Bash"]` | 自动放行的工具;接入 MCP 后需把对应工具名加进来 |
| `model` | `ANTHROPIC_MODEL` | 场景级模型覆盖(可写别名) |
| `max_turns` | `10` | 场景默认交互轮数 |
| `vars` | `{}` | 提示词里 `${VAR}` 占位符的替换值 |
| `env` | 全局 env | 覆盖全局 env 的同 key(给 Agent 主进程) |
| `mcp_servers` | `{}` | MCP 服务器配置(给 MCP 子进程,env 独立) |

> **只读 MySQL**(troubleshoot 场景):用 `@benborla29/mcp-server-mysql` 经 npx 启动,`ALLOW_*_OPERATION` 全置 `false` 即只读(仅 `SELECT`);配置后须把 `mcp__mysql__mysql_query` 加入 `allowed_tools`。

### `agent.env.json` — 部署配置

结构为 `{"env": {...}}`,与本机 `~/.claude/settings.json` 的 `env` 块**同构,可整块互相复制**,整体透传给 Agent 子进程。

```jsonc
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-gateway.example.com", // 网关;留空回退本机配置
    "ANTHROPIC_API_KEY": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", // 密钥
    "ANTHROPIC_MODEL": "glm-5.1",                            // 默认模型
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5-turbo",         // 别名 → 真实模型 ID
    "ANTHROPIC_DEFAULT_OPUS_MODEL":   "glm-5.1",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL":  "glm-5",
    "HTTP_PROXY":  "http://127.0.0.1:7897",                  // 代理(可选)
    "HTTPS_PROXY": "http://127.0.0.1:7897",
    "API_TIMEOUT_MS": "3000000"
  }
}
```

**配置优先级(从高到低)**:场景级 `config.json` 字段 → 全局 `agent.env.json` → 本机 `~/.claude`。

> ⚠️ `agent.env.json` 含密钥,勿提交。也可用环境变量 `CODEQA_CONFIG` / `CODEQA_ENV` 指定两份配置的路径。

## HTTP 接口

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/` | GET | **Web 界面**(场景选择 + 会话管理 + 流式渲染) |
| `/ask` | POST | 同步问答,返回 `{answer, cost_usd, num_turns, conversation_id}` |
| `/ask_stream` | POST | 以 **SSE** 流式返回回答(逐 token) |
| `/health` | GET | 当前配置信息(密钥脱敏) |
| `/scenarios` | GET | 列出可用场景(name/description/guide/cwd/model/allowed_tools…) |
| `/conversations` | GET | 按最近活动倒序列出会话 |
| `/conversations/{id}/messages` | GET | 返回某会话的完整历史消息 |

**入参**(`/ask` 与 `/ask_stream` 共用):

```jsonc
{
  "question": "你的问题",
  "scenario": "troubleshoot",          // 可选,选择场景;新会话为空时用 default_scenario
  "max_turns": 10,                      // 可选,为空用场景默认值
  "conversation_id": "9b3f...-...-..." // 可选,追问时传入上一轮返回的会话 ID
}
```

> 追问须沿用会话首轮绑定的场景;若显式传入不同场景,返回 `400`。

## 调用示例

```bash
# 1) 查看配置
curl http://localhost:8000/health

# 2) 同步问答
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "下单接口要传哪些字段?返回什么?"}'
# → {"answer":"该接口为 POST /order/create,需传……","cost_usd":0.001,"num_turns":3,"conversation_id":"9b3f…"}

# 3) 追问(带上上一轮的 conversation_id)
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "amount 超过上限会返回什么错误码?", "conversation_id": "<上一步的ID>"}'

# 4) 流式问答(SSE,用 -N 关闭缓冲实时打印)
curl -N -X POST http://localhost:8000/ask_stream \
  -H "Content-Type: application/json" \
  -d '{"question": "解释鉴权流程", "max_turns": 10}'
```

**SSE 事件流**:

| event | data | 含义 |
| --- | --- | --- |
| `token` | `{"text": "..."}` | 回答文本增量 |
| `done` | `{answer, cost_usd, num_turns, conversation_id}` | 成功结束(与 `/ask` 一致) |
| `error` | `{"error": "..."}` | 失败 |

## Agent 行为

- **权限 `default`** — 只回答问题;`allowed_tools` 中的读类工具自动执行,不写文件。
- **场景隔离** — 每个场景有独立的提示词、`cwd`、`add_dirs`;排查场景通过 `add_dirs` 访问 cwd 之外的日志目录。
- **消息处理** — 只把 `AssistantMessage` 的 `TextBlock` 正文推给前端;工具调用、读回的文件内容、思考过程都不会到达用户。
- **流式实现** — 开启 `include_partial_messages`,对增量消息做前缀差分,实现 token 级实时推送。

## 项目结构

```text
.
├── server.py            # FastAPI 服务:场景注册表 + 接口路由 + Agent 调用 + SSE 流式
├── store.py             # SQLite 持久化层:会话(含所属场景)与消息 CRUD(零第三方依赖)
├── static/              # 内置 Web 界面(首页 index.html + styles/ + js/)
├── scenarios/           # 场景提示词
│   ├── code_qa.md       #   代码问答(面向前端、防泄漏后端实现)
│   └── troubleshoot.md  #   项目问题排查(日志 + 代码 + 只读 MySQL)
├── tests/js/            # 前端单测
├── pyproject.toml       # uv 项目与依赖声明(claude-agent-sdk / fastapi / uvicorn)
├── config.json.example  # 业务配置示例 → 复制为 config.json
├── agent.env.json.example # 部署配置示例 → 复制为 agent.env.json
└── README.md
```
