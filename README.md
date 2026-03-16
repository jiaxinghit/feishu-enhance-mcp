# FeiShu Enhance MCP Server

飞书消息监控与文档处理MCP服务器，提供完整的飞书消息收发、监控、文件上传、异步任务功能。

## 功能特性

- **消息监听**：实时接收飞书消息，支持主群聊自动处理和@触发
- **消息发送**：发送文本消息、回复消息、上传文件
- **异步任务**：支持耗时任务异步处理，不阻塞消息接收
- **定时任务**：支持Cron和Interval定时任务
- **文档处理**：上传文件到飞书云文档

## 安装

### 方式一：从GitHub克隆安装（推荐）

```bash
# 克隆仓库
git clone https://github.com/jiaxinghit/feishu-enhance-mcp.git
cd feishu-enhance-mcp

# 安装依赖
pip install -e .
```

### 方式二：直接从GitHub安装

```bash
# 从GitHub直接安装
pip install git+https://github.com/jiaxinghit/feishu-enhance-mcp.git

# 如果需要指定分支（如main分支）
pip install git+https://github.com/jiaxinghit/feishu-enhance-mcp.git@main

# 如果需要更新到最新版本
pip install --upgrade git+https://github.com/jiaxinghit/feishu-enhance-mcp.git
```

## 配置

### 1. 获取飞书应用凭证

1. 访问 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 在应用详情页获取 `App ID` 和 `App Secret`
4. 配置应用权限（见下方权限要求）

### 2. 配置MCP客户端

将以下配置添加到 MCP 客户端配置文件中：

**Claude Desktop 配置文件位置：**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**标准配置（安装后直接使用）：**

```json
{
  "mcpServers": {
    "feishu-enhance": {
      "command": "python",
      "args": ["-m", "feishu_enhance_mcp.server"],
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
    "feishu-enhance": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "feishu_enhance_mcp.server"],
      "env": {
        "APP_ID": "your_app_id",
        "APP_SECRET": "your_app_secret",
        "PRIMARY_CHAT_ID": "oc_xxx"
      }
    }
  }
}
```

**Windows虚拟环境示例：**

```json
{
  "mcpServers": {
    "feishu-enhance": {
      "command": "C:\\Users\\YourName\\.venv\\Scripts\\python.exe",
      "args": ["-m", "feishu_enhance_mcp.server"],
      "env": {
        "APP_ID": "cli_xxxxxxxxxxxxxxxx",
        "APP_SECRET": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "PRIMARY_CHAT_ID": "oc_xxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

### 3. 环境变量说明

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `APP_ID` | 是 | 飞书应用的 App ID |
| `APP_SECRET` | 是 | 飞书应用的 App Secret |
| `PRIMARY_CHAT_ID` | 否 | 主监听群聊ID（可选，也可通过工具动态设置） |

**注意：** 从GitHub安装后，无需设置 `cwd` 参数，因为 `pip install -e .` 会将模块安装到Python环境中，可以直接通过 `python -m feishu_enhance_mcp.server` 启动。

## 消息监听策略

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

## 工具列表

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
| `lark_get_processor_status` | 获取消息处理器状态 |

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

### 定时任务示例

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
| `im:message:receive_as_bot` | 以应用身份接收消息 | 是 |
| `drive:file:upload` | 文件上传 | 否 |
| `im:file` | IM文件发送 | 否 |

## 目录结构

```
feishu-enhance-mcp/
├── feishu_enhance_mcp/     # 主模块
│   ├── __init__.py
│   ├── message_processor.py  # 消息处理器（解耦架构）
│   └── server.py          # MCP服务器
├── pyproject.toml         # 项目配置
├── README.md              # 说明文档
├── start_mcp.bat          # Windows启动脚本
└── start_mcp.sh           # Linux/Mac启动脚本
```

## 依赖

- `mcp>=1.0.0` - Model Context Protocol SDK
- `lark-oapi>=1.0.0` - 飞书开放平台SDK
- `python-dotenv>=1.0.0` - 环境变量管理
- `apscheduler>=3.10.0` - 定时任务调度

## 架构说明

本项目采用解耦架构设计：

- **消息接收层**：WebSocket长连接接收消息，立即存入队列
- **业务处理层**：后台异步线程处理消息，发送回复
- **两者互不阻塞**，确保消息接收的实时性

```
消息接收层: 收到消息 → 存入队列 → 立即返回 → 继续监听
                ↓
业务处理层: 异步处理 → 发送回复 (不阻塞接收层)
```

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

## 更新日志

### v0.1.0
- 初始版本发布
- 支持消息收发、监控
- 支持文件上传
- 支持异步任务和定时任务
- 采用解耦架构，消息接收与业务处理分离
