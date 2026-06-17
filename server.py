"""多场景问答 HTTP 服务,基于 Claude Agent SDK。

启动时从 config.json 读取配置(结构与 Claude Code 的 settings.json 一致,
其中 env 块原样透传给 Agent 子进程,可配置网关/密钥/代理),对外提供以下接口:
    POST /ask          同步返回问答结果 {answer, cost_usd, num_turns, conversation_id}
    POST /ask_stream   以 SSE 流式返回回答内容
    GET  /health       返回当前配置信息
    GET  /scenarios    列出可用场景
    GET  /conversations               按最近活动倒序列出会话
    GET  /conversations/{id}/messages 返回某会话的完整历史消息

支持多场景:config.json 的 scenarios 块声明若干场景,每个场景有自己的
system_prompt、允许工具、工作目录(cwd)与附加目录(add_dirs)。/ask 与
/ask_stream 入参 scenario 选择场景,为空时使用 default_scenario。无 scenarios
配置时自动合成默认的 code-qa(代码问答)场景,保持向后兼容。

支持多轮追问:入参 conversation_id 为空时开启新会话,传入上一轮返回的会话ID
时续接该会话上下文(基于 SDK 的 resume 能力);追问沿用会话首轮绑定的场景。

Agent 运行在 default 权限模式下,只读分析、不修改任何文件。对话历史(含所属
场景)持久化在 SQLite(默认 codeqa.db)。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

# ---------------------------------------------------------------------------
# 配置加载(JSON 文件,结构与 Claude Code 的 settings.json 一致)
#
# 默认读取项目根目录下的 config.json,可用环境变量 CODEQA_CONFIG 指定其它路径。
# 其中 env 块会原样透传给 Agent 子进程,因此把 HTTP_PROXY / HTTPS_PROXY、
# API_TIMEOUT_MS 等写进 env,即可让 Agent 的出站请求走代理。示例见 config.json.example。
# ---------------------------------------------------------------------------
CONFIG_PATH = Path(os.environ.get("CODEQA_CONFIG", "config.json"))
if not CONFIG_PATH.is_absolute():
    # 相对路径按 server.py 所在目录解析,不受启动 cwd 影响。
    CONFIG_PATH = Path(__file__).resolve().parent / CONFIG_PATH


def load_config() -> dict[str, Any]:
    """读取 JSON 配置;文件缺失或解析失败时返回空配置并告警。"""
    log = logging.getLogger("code-qa")
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning("配置文件不存在: %s(请复制 config.json.example 为 config.json)", CONFIG_PATH)
        return {}
    except json.JSONDecodeError as e:
        log.error("配置文件解析失败 %s: %s", CONFIG_PATH, e)
        return {}


CONFIG: dict[str, Any] = load_config()

# store 在导入时即把 DB_PATH 求值为模块常量,故库路径需在导入它之前写入环境变量。
if CONFIG.get("db_path"):
    os.environ["DB_PATH"] = str(CONFIG["db_path"])

import store  # noqa: E402  必须在依据配置设置 DB_PATH 之后导入

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=CONFIG.get("log_level") or os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("code-qa")

# ---------------------------------------------------------------------------
# 启动配置(取自 config.json)
# ---------------------------------------------------------------------------
# env 块整体透传给 Agent 子进程:ANTHROPIC_* 决定网关与密钥,HTTP(S)_PROXY 让出站走代理。
AGENT_ENV: dict[str, str] = {
    str(k): str(v) for k, v in (CONFIG.get("env") or {}).items()
}
ANTHROPIC_BASE_URL: str | None = AGENT_ENV.get("ANTHROPIC_BASE_URL")
ANTHROPIC_API_KEY: str | None = AGENT_ENV.get("ANTHROPIC_API_KEY")
# 全局默认:场景内省略 cwd / model 时回退到这两项。
PROJECT_DIR: str | None = CONFIG.get("project_dir")
MODEL: str | None = CONFIG.get("model")

DEFAULT_MAX_TURNS = 10
DEFAULT_ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Bash"]
# 权限模式:只用默认模式"回答问题",不使用 plan 等特殊模式。
# default 模式下,allowed_tools 中的读类工具自动执行;不需要文件写入。
PERMISSION_MODE = "default"

# 无 scenarios 配置时合成的默认代码问答场景所用提示词(向后兼容)。
BUILTIN_CODE_QA_PROMPT = (
    "你是一个专注于代码分析的助手。你的职责是阅读、理解并解释项目代码库,"
    "回答用户关于代码的问题。\n\n"
    "要求:\n"
    "1. 回答时必须引用具体的文件路径和行号(例如 `src/foo.py:42`),"
    "让结论可追溯、可验证。\n"
    "2. 专注代码分析;用 Read / Glob / Grep 查阅代码,必要时用 Bash 运行只读命令。\n"
    "3. 你的任务是回答问题,不需要修改任何文件。\n"
    "4. 回答准确、简洁,先给结论再给必要的依据。"
)


# ---------------------------------------------------------------------------
# 场景注册表
# ---------------------------------------------------------------------------
@dataclass
class Scenario:
    """一个可选择的问答场景。

    各字段决定 Agent 的运行方式:system_prompt 是已解析(读文件 + ${VAR} 替换)
    后的提示词;cwd 为工作目录;add_dirs 为 cwd 之外允许访问的目录(如日志目录)。
    """

    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str]
    cwd: str | None
    add_dirs: list[str] = field(default_factory=list)
    model: str | None = None
    max_turns: int = DEFAULT_MAX_TURNS
    mcp_servers: dict[str, Any] = field(default_factory=dict)


def _resolve_relative(p: str) -> Path:
    """把相对路径按 server.py 所在目录解析(与 CONFIG_PATH 行为一致)。"""
    path = Path(p)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path


def _load_prompt(spec: dict[str, Any], variables: dict[str, str]) -> str:
    """取出场景提示词文本并做 ${VAR} 替换。

    用 string.Template.safe_substitute(``$VAR`` / ``${VAR}`` 语法),
    不用 str.format —— 提示词里含 logback 的 ``%d{yyyy-MM-dd}`` 等花括号,
    format 会因此报错。
    """
    if spec.get("system_prompt_file"):
        text = _resolve_relative(spec["system_prompt_file"]).read_text(encoding="utf-8")
    elif spec.get("system_prompt"):
        text = str(spec["system_prompt"])
    else:
        raise ValueError("场景缺少 system_prompt 或 system_prompt_file")
    return Template(text).safe_substitute(variables)


def load_scenarios(config: dict[str, Any]) -> dict[str, Scenario]:
    """从配置构造场景注册表(按配置中的顺序)。

    无 scenarios 配置时合成默认 code-qa 场景;单个场景加载失败时记录错误并跳过。
    """
    raw = config.get("scenarios")
    scenarios: dict[str, Scenario] = {}

    if not raw:
        scenarios["code-qa"] = Scenario(
            name="code-qa",
            description="代码问答",
            system_prompt=BUILTIN_CODE_QA_PROMPT,
            allowed_tools=list(DEFAULT_ALLOWED_TOOLS),
            cwd=PROJECT_DIR,
            model=MODEL,
        )
        return scenarios

    for spec in raw:
        name = spec.get("name")
        if not name:
            logger.error("场景缺少 name 字段,已跳过: %s", spec)
            continue
        try:
            prompt = _load_prompt(spec, {k: str(v) for k, v in (spec.get("vars") or {}).items()})
        except (OSError, ValueError) as e:
            logger.error("场景 %s 提示词加载失败,已跳过: %s", name, e)
            continue
        scenarios[name] = Scenario(
            name=name,
            description=spec.get("description") or "",
            system_prompt=prompt,
            allowed_tools=spec.get("allowed_tools") or list(DEFAULT_ALLOWED_TOOLS),
            cwd=spec.get("cwd") or PROJECT_DIR,
            add_dirs=[str(_resolve_relative(d)) for d in (spec.get("add_dirs") or [])],
            model=spec.get("model") or MODEL,
            max_turns=int(spec.get("max_turns") or DEFAULT_MAX_TURNS),
            mcp_servers=spec.get("mcp_servers") or {},
        )
    return scenarios


def resolve_default_scenario(config: dict[str, Any], scenarios: dict[str, Scenario]) -> str:
    """决定默认场景名:配置项 > 列表首个 > code-qa。"""
    name = config.get("default_scenario")
    if name and name in scenarios:
        return str(name)
    if scenarios:
        return next(iter(scenarios))
    return "code-qa"


SCENARIOS: dict[str, Scenario] = load_scenarios(CONFIG)
DEFAULT_SCENARIO: str = resolve_default_scenario(CONFIG, SCENARIOS)

logger.info("配置加载: config=%s base_url=%s db_path=%s scenarios=%s default=%s",
            CONFIG_PATH, ANTHROPIC_BASE_URL, store.DB_PATH,
            list(SCENARIOS), DEFAULT_SCENARIO)
if not ANTHROPIC_API_KEY:
    logger.warning("ANTHROPIC_API_KEY 未设置,Agent 调用将会失败")
if not SCENARIOS:
    logger.warning("未加载到任何场景,Agent 调用将会失败")
for _s in SCENARIOS.values():
    if not _s.cwd:
        logger.warning("场景 %s 未配置 cwd(project_dir),调用将会失败", _s.name)
    if not _s.model:
        logger.warning("场景 %s 未配置 model,调用将会失败", _s.name)


def mask_key(key: str | None) -> str:
    """脱敏展示 API Key,避免在 /health 中泄露完整密钥。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def build_options(
    scenario: Scenario, max_turns: int, resume: str | None = None
) -> ClaudeAgentOptions:
    """根据场景构造 Agent 选项。

    resume 为已存在的 SDK 会话 ID 时,Agent 会加载该会话历史(含工具调用)
    继续作答,从而支持多轮追问。
    """
    if not scenario.cwd:
        raise ValueError(f"场景 {scenario.name} 未配置 cwd(project_dir)")
    if not scenario.model:
        raise ValueError(f"场景 {scenario.name} 未配置 model")

    # env 块整体透传给子进程:ANTHROPIC_* 指定网关/密钥,HTTP(S)_PROXY 让出站走代理。
    env: dict[str, str] = dict(AGENT_ENV)

    kwargs: dict[str, Any] = dict(
        cwd=scenario.cwd,
        permission_mode=PERMISSION_MODE,  # 默认模式:只回答问题,不使用 plan
        allowed_tools=scenario.allowed_tools,
        system_prompt=scenario.system_prompt,
        model=scenario.model,
        max_turns=max_turns,
        env=env,
        include_partial_messages=True,  # 启用增量消息,实现平滑的 token 级流式输出
        stderr=lambda line: logger.debug("[claude stderr] %s", line.rstrip()),
    )
    if scenario.add_dirs:
        # 让 Agent 能访问 cwd 之外的目录(如排查场景的日志目录)。
        kwargs["add_dirs"] = scenario.add_dirs
    if scenario.mcp_servers:
        kwargs["mcp_servers"] = scenario.mcp_servers
    if resume:
        kwargs["resume"] = resume  # 复用既有 SDK 会话,实现追问
    return ClaudeAgentOptions(**kwargs)


async def run_agent(
    question: str,
    scenario: Scenario,
    max_turns: int,
    resume_session_id: str | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """运行 Agent,产出 (kind, data) 事件流。

    事件类型:
        ("text",   delta_str)                                  文本增量(用于流式)
        ("result", {answer, cost_usd, num_turns, session_id})  成功结束
        ("error",  message_str)                                Agent 报错结束

    resume_session_id 为已存在的 SDK 会话 ID 时,Agent 会续接该会话历史作答。
    """
    options = build_options(scenario, max_turns, resume=resume_session_id)
    prev_text = ""        # 上一条 AssistantMessage 的累计文本,用于计算增量
    answer = ""           # 累计的完整回答

    async for message in query(prompt=question, options=options):
        if isinstance(message, AssistantMessage):
            # 合并该消息内所有文本块(忽略 tool_use 等)。
            text = "".join(
                block.text for block in message.content if isinstance(block, TextBlock)
            )
            if not text:
                continue
            # 开启 include_partial_messages 后,同一条消息会以"不断增长"的形式
            # 反复出现;通过前缀匹配取出本次新增的部分。
            if text.startswith(prev_text):
                delta = text[len(prev_text):]
            else:
                # 新的一轮回答(例如工具调用之后),从头输出。
                delta = text
            if delta:
                answer += delta
                yield ("text", delta)
            prev_text = text

        elif isinstance(message, ResultMessage):
            cost = float(message.total_cost_usd or 0.0)
            turns = int(message.num_turns or 0)
            if message.is_error:
                errors = message.errors or []
                detail = "; ".join(errors) if errors else "Agent 返回错误"
                yield ("error", detail)
            else:
                yield ("result", {
                    "answer": answer,
                    "cost_usd": cost,
                    "num_turns": turns,
                    "session_id": message.session_id,
                })
            return


def sse(event: str, data: Any) -> str:
    """格式化一条 SSE 事件。ensure_ascii=False 以 UTF-8 原样输出中文。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
app = FastAPI(title="Code Q&A Service", version="1.0.0")

# 启动即建表(幂等);库文件路径由环境变量 DB_PATH 控制,默认 codeqa.db
store.init_db()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="要问的问题")
    scenario: str | None = Field(
        default=None,
        description="选择场景;为空则使用 default_scenario。追问时须与会话所属场景一致",
    )
    max_turns: int | None = Field(default=None, ge=1, le=100,
                                  description="Agent 最大交互轮数;为空则用场景默认值")
    conversation_id: str | None = Field(
        default=None,
        description="追问时传入上一轮返回的会话ID;为空则开启新会话",
    )


def _resolve_scenario_and_conversation(
    conv_id: str | None,
    scenario_name: str | None,
) -> tuple[store.Conversation | None, Scenario | None, JSONResponse | None]:
    """解析(场景, 会话)(由 handler 通过线程池调用)。

    - 新会话(conv_id 为空):场景取 scenario_name 或 DEFAULT_SCENARIO;
      未知场景名返回 400;随后新建会话并绑定该场景。
    - 追问(conv_id 非空):会话不存在返回 404;以会话存储的场景为准重建,
      若请求显式传了不同的 scenario 返回 400(避免上下文/目录错配)。

    返回 (会话, 场景, 错误响应):成功时错误响应为 None。
    """
    if conv_id:
        conv = store.get_conversation(conv_id)
        if conv is None:
            return None, None, JSONResponse(status_code=404, content={"error": "会话不存在"})
        stored = conv.scenario or DEFAULT_SCENARIO
        if scenario_name and scenario_name != stored:
            return None, None, JSONResponse(
                status_code=400,
                content={"error": f"该会话属于场景 '{stored}',不能用场景 '{scenario_name}' 追问"},
            )
        scenario = SCENARIOS.get(stored)
        if scenario is None:
            return None, None, JSONResponse(
                status_code=400, content={"error": f"会话所属场景 '{stored}' 不存在"})
        return conv, scenario, None

    name = scenario_name or DEFAULT_SCENARIO
    scenario = SCENARIOS.get(name)
    if scenario is None:
        return None, None, JSONResponse(
            status_code=400, content={"error": f"未知场景: {name}"})
    conv = store.create_conversation(scenario=name)
    return conv, scenario, None


def _persist_turn(
    conv: store.Conversation,
    question: str,
    answer: str,
    cost_usd: float,
    num_turns: int,
    sdk_session_id: str | None,
) -> None:
    """把一轮成功的问答写入存储(由 handler 通过线程池调用)。"""
    store.add_message(conv.id, "user", question)
    store.add_message(conv.id, "assistant", answer, cost_usd, num_turns)
    if sdk_session_id:
        store.set_sdk_session_id(conv.id, sdk_session_id)
    store.touch(conv.id, add_cost=cost_usd, add_turns=num_turns)


@app.get("/health")
async def health() -> dict[str, Any]:
    """返回当前配置信息(密钥脱敏)。"""
    return {
        "anthropic_base_url": ANTHROPIC_BASE_URL,
        "permission_mode": PERMISSION_MODE,
        "api_key_set": bool(ANTHROPIC_API_KEY),
        "api_key_masked": mask_key(ANTHROPIC_API_KEY),
        "default_max_turns": DEFAULT_MAX_TURNS,
        "default_scenario": DEFAULT_SCENARIO,
        "scenarios": list(SCENARIOS),
    }


@app.get("/scenarios")
async def scenarios_endpoint() -> dict[str, Any]:
    """列出可用场景(不含密钥)。"""
    return {
        "default_scenario": DEFAULT_SCENARIO,
        "scenarios": [
            {
                "name": s.name,
                "description": s.description,
                "cwd": s.cwd,
                "add_dirs": s.add_dirs,
                "model": s.model,
                "allowed_tools": s.allowed_tools,
                "max_turns": s.max_turns,
            }
            for s in SCENARIOS.values()
        ],
    }


@app.post("/ask")
async def ask(payload: AskRequest):
    """同步问答:返回 {answer, cost_usd, num_turns, conversation_id}。

    入参 conversation_id 为空时开启新会话;否则续接该会话(追问)。
    """
    conv, scenario, err = await run_in_threadpool(
        _resolve_scenario_and_conversation, payload.conversation_id, payload.scenario
    )
    if err is not None:
        return err

    max_turns = payload.max_turns if payload.max_turns is not None else scenario.max_turns
    answer = ""
    cost_usd = 0.0
    num_turns = 0
    sdk_session_id: str | None = None
    try:
        async for kind, data in run_agent(
            payload.question, scenario, max_turns, conv.sdk_session_id
        ):
            if kind == "text":
                answer += data
            elif kind == "result":
                cost_usd = data["cost_usd"]
                num_turns = data["num_turns"]
                sdk_session_id = data.get("session_id")
            elif kind == "error":
                return JSONResponse(
                    status_code=502,
                    content={"error": data, "answer": answer,
                             "cost_usd": cost_usd, "num_turns": num_turns},
                )
    except ValueError as e:
        # 配置缺失
        return JSONResponse(status_code=500, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        logger.exception("Agent 调用失败")
        return JSONResponse(status_code=500, content={"error": str(e)})

    # 成功回答后落库:用户提问 + 助手回答 + 绑定 SDK 会话 + 累计统计
    await run_in_threadpool(_persist_turn, conv, payload.question, answer,
                            cost_usd, num_turns, sdk_session_id)

    return {"answer": answer, "cost_usd": cost_usd, "num_turns": num_turns,
            "conversation_id": conv.id}


@app.post("/ask_stream")
async def ask_stream(payload: AskRequest):
    """流式问答:以 SSE 返回回答内容。

    事件流:
        event: token   data: {"text": "..."}                                  文本增量
        event: done    data: {"answer","cost_usd","num_turns","conversation_id"}
        event: error   data: {"error": "..."}

    入参 conversation_id 为空时开启新会话;否则续接该会话(追问)。
    """

    # 场景/会话解析在进入流之前完成:不存在的会话直接 404、未知场景 400,不进入 SSE。
    conv, scenario, err = await run_in_threadpool(
        _resolve_scenario_and_conversation, payload.conversation_id, payload.scenario
    )
    if err is not None:
        return err

    max_turns = payload.max_turns if payload.max_turns is not None else scenario.max_turns

    async def event_generator() -> AsyncIterator[str]:
        try:
            sdk_session_id: str | None = None
            async for kind, data in run_agent(
                payload.question, scenario, max_turns, conv.sdk_session_id
            ):
                if kind == "text":
                    yield sse("token", {"text": data})
                elif kind == "result":
                    sdk_session_id = data.get("session_id")
                    yield sse("done", {**data, "conversation_id": conv.id})
                    # 成功结束:把本轮问答落库。
                    await run_in_threadpool(
                        _persist_turn, conv, payload.question, data["answer"],
                        data["cost_usd"], data["num_turns"], sdk_session_id,
                    )
                elif kind == "error":
                    yield sse("error", {"error": data})
        except ValueError as e:
            yield sse("error", {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.exception("Agent 流式调用失败")
            yield sse("error", {"error": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲,保证实时推送
            "Connection": "keep-alive",
        },
    )


@app.get("/conversations")
async def conversations(limit: int = 50):
    """按最近活动倒序列出会话摘要。"""
    return await run_in_threadpool(store.list_conversations, limit)


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str):
    """返回某个会话的元信息与完整历史消息(user/assistant 交替)。"""
    conv = await run_in_threadpool(store.get_conversation, conversation_id)
    if conv is None:
        return JSONResponse(status_code=404, content={"error": "会话不存在"})
    messages = await run_in_threadpool(store.list_messages, conversation_id)
    return {"conversation": conv.as_dict(), "messages": messages}


def main() -> None:
    """启动 uvicorn 服务(供 `python server.py` 与 `code-qa` 入口使用)。"""
    import uvicorn

    host = str(CONFIG.get("host") or os.environ.get("HOST", "0.0.0.0"))
    port = int(CONFIG.get("port") or os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
