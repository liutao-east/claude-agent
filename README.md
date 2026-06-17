# Code Q&A Service

基于 **Claude Agent SDK**(`claude-agent-sdk`)的代码问答 HTTP 服务。

Agent 以 **default** 权限模式运行,仅允许 `Read` / `Glob` / `Grep` / `Bash` 工具,
专注代码分析、引用具体文件路径与行号,**不修改任何文件**。对话历史持久化在
**SQLite**(默认 `codeqa.db`),支持**多轮追问**。

> ⚠️ 注意:旧包名 `claude-code-sdk` 已废弃,类名 `ClaudeCodeOptions` 已改为 `ClaudeAgentOptions`,
> 本项目使用的是新包 `claude-agent-sdk`。

---

## 功能

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/ask` | POST | 同步问答,返回 `{answer, cost_usd, num_turns, conversation_id}` |
| `/ask_stream` | POST | 以 **SSE** 流式返回回答内容(逐 token) |
| `/health` | GET | 返回当前配置信息 |
| `/conversations` | GET | 按最近活动倒序列出会话 |
| `/conversations/{id}/messages` | GET | 返回某会话的完整历史消息 |

### 多轮追问

`/ask` 与 `/ask_stream` 的入参支持可选的 `conversation_id`:

- **不带** `conversation_id`(或为空):开启新会话,响应里返回新的 `conversation_id`。
- **带** `conversation_id`:在该会话上**追问**,Agent 会续接之前的上下文
  (包括上一轮 Read / Grep 过的文件)继续作答,无需重复提供背景。

追问基于 Claude Agent SDK 的 `resume` 能力实现:每轮的回答会自动持久化,
服务重启后仍可继续追问。

---

## 一、环境准备(基于 uv)

[uv](https://docs.astral.sh/uv/) 是一个极速的 Python 包/项目管理器。先安装 uv:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 二、初始化与安装依赖

在项目根目录(`server.py` 所在目录)执行:

```bash
# 创建并使用 Python 3.10+ 虚拟环境
uv python install 3.10
uv venv --python 3.10

# 根据 pyproject.toml 安装依赖
uv sync
```

> `uv sync` 会读取本项目的 `pyproject.toml`,自动安装 `claude-agent-sdk`、`fastapi`、`uvicorn` 等依赖。

## 三、配置(config.json)

配置采用 **JSON** 文件,结构与 Claude Code 的 `settings.json` 一致——尤其 `env`
块格式完全相同,**可与 `~/.claude/settings.json` 互相复制**。复制示例并填入真实值:

```bash
cp config.json.example config.json
```

编辑 `config.json`:

```jsonc
{
  "model": "claude-sonnet-4-6",          // 模型名称(需为网关支持的 ID)
  "project_dir": "/path/to/your/project", // 被分析的项目代码路径(绝对路径)
  "host": "0.0.0.0",                      // 可选,默认 0.0.0.0
  "port": 8000,                           // 可选,默认 8000
  "log_level": "INFO",                    // 可选,默认 INFO

  // env 块整体透传给 Agent 子进程;不需要的项可删除
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-gateway.example.com", // 任意 Anthropic 兼容网关
    "ANTHROPIC_API_KEY": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "HTTP_PROXY": "http://127.0.0.1:7897",   // 让 Agent 出站请求走代理
    "HTTPS_PROXY": "http://127.0.0.1:7897",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  }
}
```

> - **代理**:把 `HTTP_PROXY` / `HTTPS_PROXY` 写进 `env` 即可——该块会原样传入
>   驱动 Claude Code 的子进程,Agent 的出站请求(访问网关/模型)随之走代理。
> - **网关/密钥**:`ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` 同样放在 `env` 里。
> - `config.json` 含密钥,已在 `.gitignore` 中忽略,勿提交。
> - 默认读取项目根目录下的 `config.json`;可用环境变量 `CODEQA_CONFIG` 指定其它路径。

## 四、启动服务

```bash
# 读取 config.json 并启动(推荐)
uv run python server.py
```

也可以用 uvicorn 直接拉起 ASGI 应用(host/port 仍取自 config.json,命令行参数可覆盖):

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

启动后默认监听 `http://0.0.0.0:8000`,可访问 `GET /health` 查看配置。

---

## 五、接口调用示例

### 1. 查看配置

```bash
curl http://localhost:8000/health
```

### 2. 同步问答 `/ask`

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "这个项目的入口在哪里?它做了什么?", "max_turns": 10}'
```

响应示例:

```json
{
  "answer": "项目入口位于 `src/main.py:12`……",
  "cost_usd": 0.001,
  "num_turns": 3,
  "conversation_id": "9b3f...-...-..."
}
```

入参:

```jsonc
{
  "question": "你的代码问题",
  "max_turns": 10,                  // 可选,默认 10
  "conversation_id": "9b3f...-...-..." // 可选,追问时传入上一轮返回的会话ID
}
```

#### 多轮追问示例

```bash
# 1) 首轮提问,拿到 conversation_id
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "这个项目的入口在哪?它做了什么?"}'

# 2) 带上 conversation_id 追问,Agent 会延续上一轮上下文
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "刚才说的那个文件里,鉴权逻辑具体在几行?", "conversation_id": "<上一步的ID>"}'
```

### 3. 流式问答 `/ask_stream`(SSE)

```bash
curl -N -X POST http://localhost:8000/ask_stream \
  -H "Content-Type: application/json" \
  -d '{"question": "解释 src/auth.py 的鉴权流程", "max_turns": 10}'
```

SSE 事件流:

```text
event: token
data: {"text": "项目入口"}

event: token
data: {"text": "位于 `src/main.py:12`……"}

event: done
data: {"answer": "项目入口位于 `src/main.py:12`……", "cost_usd": 0.001, "num_turns": 3}
```

| event | data | 含义 |
| --- | --- | --- |
| `token` | `{"text": "..."}` | 回答的文本增量 |
| `done`  | `{"answer","cost_usd","num_turns","conversation_id"}` | 成功结束,与 `/ask` 返回结构一致 |
| `error` | `{"error": "..."}` | 失败 |

> 用 `-N`(`--no-buffer`)确保 curl 实时打印流式数据。
> Python 客户端可用 `httpx` 的 `client.stream("POST", url)` 逐行读取。

---

## 六、Agent 行为说明

- **权限模式 `default`**:只用于回答问题;`allowed_tools` 中的读类工具自动执行,不做文件写入。
- **允许工具**:`Read`、`Glob`、`Grep`、`Bash`(用于查阅代码 / 运行只读命令)。
- **system_prompt**:要求 Agent 引用具体文件路径和行号(如 `src/foo.py:42`)。
- **消息处理**:正确处理 `AssistantMessage` / `TextBlock` / `ResultMessage`,
  并从 `ResultMessage` 提取 `total_cost_usd` 与 `num_turns`。
- **流式实现**:开启 `include_partial_messages`,对增量消息做前缀差分,
  实现 token 级别的实时推送。

---

## 七、项目结构

```text
.
├── server.py         # FastAPI 服务:接口路由 + Agent 调用逻辑(含追问编排)
├── store.py          # SQLite 持久化层:会话与消息 CRUD
├── pyproject.toml      # uv 项目与依赖声明
├── config.json.example # 配置示例(复制为 config.json)
└── README.md
```
