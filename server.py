"""代码问答 HTTP 服务,基于 Claude Agent SDK。

启动时从环境变量读取配置,对外提供以下接口:
    POST /ask          同步返回代码问答结果 {answer, cost_usd, num_turns, conversation_id}
    POST /ask_stream   以 SSE 流式返回回答内容
    GET  /health       返回当前配置信息
    GET  /conversations               按最近活动倒序列出会话
    GET  /conversations/{id}/messages 返回某会话的完整历史消息

支持多轮追问:/ask 与 /ask_stream 入参 conversation_id 为空时开启新会话,
传入上一轮返回的会话ID时续接该会话上下文(基于 SDK 的 resume 能力)。

Agent 运行在 default 权限模式下,仅允许 Read/Glob/Grep/Bash 工具,
专注代码分析且不修改任何文件。对话历史持久化在 SQLite(默认 codeqa.db)。
"""

from __future__ import annotations

import json
import logging
import os
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

import store

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("code-qa")

# ---------------------------------------------------------------------------
# 启动配置(从环境变量读取)
# ---------------------------------------------------------------------------
ANTHROPIC_BASE_URL: str | None = os.environ.get("ANTHROPIC_BASE_URL")
ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
PROJECT_DIR: str | None = os.environ.get("PROJECT_DIR")
MODEL: str | None = os.environ.get("MODEL")

DEFAULT_MAX_TURNS = 10
ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Bash"]
# 权限模式:只用默认模式"回答问题",不使用 plan 等特殊模式。
# default 模式下,allowed_tools 中的读类工具自动执行;不需要文件写入。
PERMISSION_MODE = "default"

SYSTEM_PROMPT = (
    "你是一个专注于代码分析的助手。你的职责是阅读、理解并解释项目代码库,"
    "回答用户关于代码的问题。\n\n"
    "要求:\n"
    "1. 回答时必须引用具体的文件路径和行号(例如 `src/foo.py:42`),"
    "让结论可追溯、可验证。\n"
    "2. 专注代码分析;用 Read / Glob / Grep 查阅代码,必要时用 Bash 运行只读命令。\n"
    "3. 你的任务是回答问题,不需要修改任何文件。\n"
    "4. 回答准确、简洁,先给结论再给必要的依据。"
)

logger.info("配置加载: model=%s base_url=%s project_dir=%s db_path=%s",
            MODEL, ANTHROPIC_BASE_URL, PROJECT_DIR, store.DB_PATH)
if not ANTHROPIC_API_KEY:
    logger.warning("ANTHROPIC_API_KEY 未设置,Agent 调用将会失败")
if not PROJECT_DIR:
    logger.warning("PROJECT_DIR 未设置,Agent 调用将会失败")
if not MODEL:
    logger.warning("MODEL 未设置,Agent 调用将会失败")


def mask_key(key: str | None) -> str:
    """脱敏展示 API Key,避免在 /health 中泄露完整密钥。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


def build_options(max_turns: int, resume: str | None = None) -> ClaudeAgentOptions:
    """根据当前配置构造 Agent 选项。

    resume 为已存在的 SDK 会话 ID 时,Agent 会加载该会话历史(含工具调用)
    继续作答,从而支持多轮追问。
    """
    if not PROJECT_DIR:
        raise ValueError("环境变量 PROJECT_DIR 未设置")
    if not MODEL:
        raise ValueError("环境变量 MODEL 未设置")

    # 显式把网关地址与密钥传入子进程,确保 Agent 走指定网关。
    env: dict[str, str] = {}
    if ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    if ANTHROPIC_BASE_URL:
        env["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL

    kwargs: dict[str, Any] = dict(
        cwd=PROJECT_DIR,
        permission_mode=PERMISSION_MODE,  # 默认模式:只回答问题,不使用 plan
        allowed_tools=ALLOWED_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        model=MODEL,
        max_turns=max_turns,
        env=env,
        include_partial_messages=True,  # 启用增量消息,实现平滑的 token 级流式输出
        stderr=lambda line: logger.debug("[claude stderr] %s", line.rstrip()),
    )
    if resume:
        kwargs["resume"] = resume  # 复用既有 SDK 会话,实现追问
    return ClaudeAgentOptions(**kwargs)


async def run_agent(
    question: str,
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
    options = build_options(max_turns, resume=resume_session_id)
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
    question: str = Field(..., min_length=1, description="要问的代码问题")
    max_turns: int = Field(default=DEFAULT_MAX_TURNS, ge=1, le=100,
                           description="Agent 最大交互轮数")
    conversation_id: str | None = Field(
        default=None,
        description="追问时传入上一轮返回的会话ID;为空则开启新会话",
    )


def _resolve_conversation(
    conv_id: str | None,
) -> tuple[store.Conversation | None, JSONResponse | None]:
    """按 conversation_id 解析会话(由 handler 通过线程池调用)。

    传入 None 则新建会话;传入已存在 ID 则返回该会话;传入不存在的 ID 返回 404。
    返回 (会话, 错误响应):成功时错误响应为 None;失败时会话为 None。
    """
    if conv_id:
        conv = store.get_conversation(conv_id)
        if conv is None:
            return None, JSONResponse(status_code=404, content={"error": "会话不存在"})
        return conv, None
    return store.create_conversation(), None


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
        "model": MODEL,
        "anthropic_base_url": ANTHROPIC_BASE_URL,
        "project_dir": PROJECT_DIR,
        "permission_mode": PERMISSION_MODE,
        "allowed_tools": ALLOWED_TOOLS,
        "api_key_set": bool(ANTHROPIC_API_KEY),
        "api_key_masked": mask_key(ANTHROPIC_API_KEY),
        "default_max_turns": DEFAULT_MAX_TURNS,
    }


@app.post("/ask")
async def ask(payload: AskRequest):
    """同步问答:返回 {answer, cost_usd, num_turns, conversation_id}。

    入参 conversation_id 为空时开启新会话;否则续接该会话(追问)。
    """
    conv, err = await run_in_threadpool(_resolve_conversation, payload.conversation_id)
    if err is not None:
        return err

    answer = ""
    cost_usd = 0.0
    num_turns = 0
    sdk_session_id: str | None = None
    try:
        async for kind, data in run_agent(
            payload.question, payload.max_turns, conv.sdk_session_id
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

    # 会话解析在进入流之前完成:不存在的会话直接 404,不进入 SSE。
    conv, err = await run_in_threadpool(_resolve_conversation, payload.conversation_id)
    if err is not None:
        return err

    async def event_generator() -> AsyncIterator[str]:
        try:
            sdk_session_id: str | None = None
            async for kind, data in run_agent(
                payload.question, payload.max_turns, conv.sdk_session_id
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

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
