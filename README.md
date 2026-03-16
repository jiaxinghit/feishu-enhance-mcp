# Lark MCP Server

飞书消息监控与文档处理MCP服务器，提供完整的飞书消息收发、监控、文件上传、异步任务功能。

## 安装

```bash
cd lark-mcp
pip install -e .
```

## 功能

### 消息监听策略（B方案）

本服务采用智能消息过滤策略：

- **主群聊**：直接处理所有消息，无需@
- **其他群聊**：只有@机器人的消息才会被处理

**配置主群聊：**
```python
# 设置主群聊ID
lark_set_primary_chat(chat_id="oc_xxx")

# 获取当前主群聊ID
result = lark_get_primary_chat()
```

主群聊ID会自动保存到 `monitor_config.json` 文件中，重启后自动加载。

### 核心工具
| 工具名称 | 描述 |
|---------|------|
| `lark_get_messages` | 获取未处理消息列表 |
| `lark_send_message` | 发送文本消息 |
| `lark_reply_message` | 回复消息并标记已处理 |
| `lark_wait_for_message` | 阻塞等待新消息（推荐） |

### 会话管理工具
| 工具名称 | 描述 |
|---------|------|
| `lark_start_monitor` | 启动监控会话 |
| `lark_stop_monitor` | 停止监控会话 |
| `lark_list_monitors` | 列出所有监控会话 |
| `lark_get_connection_status` | 获取飞书长连接状态 |

### 辅助工具
| 工具名称 | 描述 |
|---------|------|
| `lark_get_chat_list` | 获取群聊列表 |
| `lark_get_chat_info` | 获取聊天详情 |
| `lark_mark_processed` | 标记消息已处理 |
| `lark_clear_queue` | 清空消息队列 |
| `lark_set_primary_chat` | 设置主监听群聊ID |
| `lark_get_primary_chat` | 获取当前主群聊ID |

### 文档工具
| 工具名称 | 描述 |
|---------|------|
| `lark_upload_file` | 上传本地文件到飞书云文档 |
| `lark_send_file_to_chat` | 上传文件并发送到聊天 |

### 异步任务工具
| 工具名称 | 描述 |
|---------|------|
| `lark_create_async_task` | 创建异步任务 |
| `lark_get_task_status` | 查询任务状态 |
| `lark_list_tasks` | 列出所有任务 |

### 定时任务工具
| 工具名称 | 描述 |
|---------|------|
| `lark_add_schedule_task` | 添加定时任务 |
| `lark_remove_schedule_task` | 删除定时任务 |
| `lark_list_schedule_tasks` | 列出所有定时任务 |
| `lark_enable_schedule_task` | 启用/禁用定时任务 |

**定时任务示例：**

```python
# 每天早上9点发送消息
lark_add_schedule_task(
    name="每日提醒",
    trigger_type="cron",
    trigger_config={"hour": 9, "minute": 0},
    chat_id="oc_xxx",
    message="早上好！新的一天开始了！"
)

# 每小时发送一次
lark_add_schedule_task(
    name="每小时提醒",
    trigger_type="interval",
    trigger_config={"hours": 1},
    chat_id="oc_xxx",
    message="整点报时"
)
```

**触发器配置说明：**

- **cron 触发器**：支持标准 cron 表达式参数
  - `hour`: 小时 (0-23)
  - `minute`: 分钟 (0-59)
  - `day`: 日期 (1-31)
  - `month`: 月份 (1-12)
  - `day_of_week`: 星期几 (0-6, 0=周一)

- **interval 触发器**：支持间隔时间参数
  - `weeks`: 周数
  - `days`: 天数
  - `hours`: 小时数
  - `minutes`: 分钟数
  - `seconds`: 秒数

## 配置

### MCP客户端配置

将以下配置添加到 MCP 客户端配置文件中：

**Claude Desktop 配置文件位置：**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**配置示例：**

```json
{
  "mcpServers": {
    "lark": {
      "command": "python",
      "args": ["-m", "lark_mcp.server"],
      "cwd": "D:\\IDEA\\lark-trae-bridge\\lark-mcp",
      "env": {
        "APP_ID": "your_app_id",
        "APP_SECRET": "your_app_secret",
        "PRIMARY_CHAT_ID": "oc_xxx"
      }
    }
  }
}
```

**使用虚拟环境的配置：**

```json
{
  "mcpServers": {
    "lark": {
      "command": "D:\\IDEA\\lark-trae-bridge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "lark_mcp.server"],
      "cwd": "D:\\IDEA\\lark-trae-bridge\\lark-mcp",
      "env": {
        "APP_ID": "your_app_id",
        "APP_SECRET": "your_app_secret",
        "PRIMARY_CHAT_ID": "oc_xxx"
      }
    }
  }
}
```

**配置说明：**
- `PRIMARY_CHAT_ID` 为可选参数，用于设置主监听群聊
- 如果不设置，可以通过 `lark_set_primary_chat` 工具动态设置
- 主群聊中的消息会被直接处理，其他群聊需要@机器人才会处理

### 配置参数说明

| 参数 | 必填 | 说明 |
|-----|------|------|
| `command` | 是 | 执行命令，可以是 `python` 或虚拟环境的 Python 路径 |
| `args` | 是 | 命令参数，模块路径 `["-m", "lark_mcp.server"]` |
| `cwd` | 是 | 工作目录，确保模块能被正确找到 |
| `env.APP_ID` | 是 | 飞书应用的 App ID |
| `env.APP_SECRET` | 是 | 飞书应用的 App Secret |
| `env.PRIMARY_CHAT_ID` | 否 | 主群聊ID（可选，也可通过工具设置） |

### 获取飞书应用凭证

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 在应用详情页获取 `App ID` 和 `App Secret`
4. 配置应用权限（见下方权限要求）

## 使用示例

### 启动监控并等待消息

```python
# 1. 启动监控会话
lark_start_monitor(session_name="my-monitor")

# 2. 循环等待消息
while True:
    result = lark_wait_for_message(timeout=0)
    if result["success"]:
        message = result["message"]
        # 处理消息...
        lark_reply_message(message["message_id"], "收到！")
```

### 上传文件到云文档

```python
# 上传Excel文件
result = lark_upload_file(
    file_path="/path/to/file.xlsx",
    file_name="报表.xlsx"
)
# 返回: {"success": True, "file_token": "...", "file_name": "报表.xlsx"}
```

### 异步任务处理

```python
# 创建异步任务
result = lark_create_async_task(
    task_type="generate_report",
    description="生成复杂报告",
    chat_id="oc_xxx"
)
# 返回: {"success": True, "task": {"id": "task_xxx", ...}}

# 查询任务状态
status = lark_get_task_status(task_id="task_xxx")
```

## 权限要求

需要在飞书开放平台开通以下权限：

| 权限 | 说明 | 必需 |
|-----|------|------|
| `im:message` | 消息操作 | 是 |
| `im:message:send_as_bot` | 以应用身份发消息 | 是 |
| `drive:file:upload` | 文件上传 | 否 |
| `im:file` | IM文件发送 | 否 |

## 目录结构

```
lark-mcp/
├── lark_mcp/              # 主模块
│   ├── __init__.py
│   └── server.py          # MCP服务器（包含所有功能）
├── pyproject.toml         # 项目配置
├── README.md              # 说明文档
├── start_mcp.bat          # Windows启动脚本
└── start_mcp.sh           # Linux/Mac启动脚本
```

## 依赖

- mcp>=1.0.0 - Model Context Protocol SDK
- lark-oapi>=1.0.0 - 飞书开放平台SDK
- python-dotenv>=1.0.0 - 环境变量管理
