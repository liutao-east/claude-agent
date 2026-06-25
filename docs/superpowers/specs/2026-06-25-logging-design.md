# 后端日志设计规范

**日期：** 2026-06-25  
**范围：** `server.py`（仅此文件）  
**目标：** 为 FastAPI 后端添加访问日志（B）和业务请求追踪日志（A）

---

## 背景

现有后端（`server.py` + `store.py`）已有基础 `logging` 配置，记录启动信息和未捕获异常，但缺少：

- 每个 HTTP 请求的访问记录（方法、路径、状态码、耗时）
- `/ask` / `/ask_stream` 的业务级追踪（场景、会话、turns、cost、是否出错）

---

## 设计

### 1. 访问日志 — `LoggingMiddleware`

**位置：** `server.py`，`app = FastAPI(...)` 之后注册。

**实现方式：** `@app.middleware("http")`

**Logger 名称：** `access`（与业务 logger `code-qa` 分开，方便独立过滤）

**日志格式（复用现有 basicConfig 格式）：**
```
2026-06-25 10:00:01 INFO  access: POST /ask 200 1234ms
2026-06-25 10:00:02 INFO  access: GET  /health 200 2ms
```

字段：`METHOD PATH STATUS_CODE ELAPSEDms`

**SSE 说明：** `/ask_stream` 的访问日志耗时为"首字节时间"（`call_next` 在 headers 发出后即返回），总业务耗时由业务日志负责。

---

### 2. 业务追踪日志 — handler 内部

**Logger 名称：** `code-qa`（现有 logger，无需新建）

**触发位置：**
- `/ask`：`try` 块结束后，成功或错误均写一条
- `/ask_stream`：`event_generator` 内，`done` 事件处写成功，`error` 事件处写错误

**日志格式：**
```
# 成功
INFO  code-qa: ask scenario=code-qa conv=abc12345 turns=3 cost=$0.0042 ok
# 出错
ERROR code-qa: ask scenario=code-qa conv=abc12345 turns=1 cost=$0.0000 error=Agent 返回错误
```

字段：
| 字段 | 说明 |
|------|------|
| `scenario` | 场景名 |
| `conv` | `conversation_id` 前 8 位 |
| `turns` | `num_turns` |
| `cost` | `cost_usd` 格式化为 `$0.0000` |
| 结果 | `ok` 或 `error=<detail>` |

---

### 3. 错误处理覆盖

| 情形 | 访问日志 | 业务日志 |
|------|---------|---------|
| Agent 正常返回 | `200` | `INFO … ok` |
| Agent 返回 error（502） | `502` | `ERROR … error=<detail>` |
| 配置缺失 ValueError（500） | `500` | 现有 `logger.exception`（不重复） |
| 未知异常（500） | `500` | 现有 `logger.exception`（不重复） |
| 场景/会话不存在（400/404） | `400/404` | 无（Agent 未启动，无需追踪） |

---

## 改动范围

- **`server.py`**：新增 `LoggingMiddleware`；在 `/ask` 和 `/ask_stream` handler 末尾插入业务日志
- **`store.py`**：不改动
- **`config.json`**：不改动（日志级别已由 `log_level` 字段控制）

---

## 不在范围内

- 结构化 JSON 日志
- 日志文件输出
- `store.py` 的存储层日志
