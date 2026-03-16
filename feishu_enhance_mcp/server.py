"""FeiShu Enhance MCP Server - 飞书消息监控与文档处理MCP服务器

提供飞书消息监控、消息收发、文档上传等功能
"""

import os
import json
import asyncio
import logging
import threading
import time
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict
from collections import deque
from queue import Queue, Empty
from pathlib import Path
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore

import lark_oapi as lark
from lark_oapi.api.im.v1 import *

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import mcp.types as types

from .message_processor import message_processor, ProcessingResult

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

APP_ID = os.getenv("APP_ID", "")
APP_SECRET = os.getenv("APP_SECRET", "")

# 主监听群聊ID配置
PRIMARY_CHAT_ID = os.getenv("PRIMARY_CHAT_ID", "oc_6f4c530bae7484efa8f6d193db0a7df4")


@dataclass
class LarkMessage:
    message_id: str
    chat_id: str
    sender_id: str
    sender_name: str
    content: str
    msg_type: str
    timestamp: str
    processed: bool = False
    task_id: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


class MessageQueue:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._messages: deque = deque(maxlen=100)
            cls._instance._message_index: Dict[str, LarkMessage] = {}
        return cls._instance
    
    def add_message(self, message: LarkMessage):
        with self._lock:
            self._messages.append(message)
            self._message_index[message.message_id] = message
    
    def get_unprocessed(self, limit: int = 10) -> List[LarkMessage]:
        with self._lock:
            return [msg for msg in self._messages if not msg.processed][:limit]
    
    def mark_processed(self, message_id: str, task_id: str = ""):
        with self._lock:
            if message_id in self._message_index:
                self._message_index[message_id].processed = True
                self._message_index[message_id].task_id = task_id
    
    def get_all(self, limit: int = 20) -> List[LarkMessage]:
        with self._lock:
            return list(self._messages)[-limit:]
    
    def clear(self):
        with self._lock:
            self._messages.clear()
            self._message_index.clear()
    
    def get_by_id(self, message_id: str) -> Optional[LarkMessage]:
        with self._lock:
            return self._message_index.get(message_id)


class MessageWaitQueue:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._waiters: List[Queue] = []
            cls._instance._active = True
        return cls._instance
    
    def wait_for_message(self, timeout: float = 0, chat_id_filter: str = None) -> Optional[LarkMessage]:
        waiter = Queue()
        with self._lock:
            if not self._active:
                return None
            self._waiters.append(waiter)
        
        try:
            start_time = time.time()
            while True:
                if timeout > 0:
                    remaining = timeout - (time.time() - start_time)
                    if remaining <= 0:
                        return None
                    wait_time = min(remaining, 1)
                else:
                    wait_time = 1
                
                try:
                    message = waiter.get(timeout=wait_time)
                    if chat_id_filter and message.chat_id != chat_id_filter:
                        continue
                    return message
                except Empty:
                    if timeout == 0:
                        continue
                    remaining = timeout - (time.time() - start_time)
                    if remaining <= 0:
                        return None
        finally:
            with self._lock:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
    
    def notify_new_message(self, message: LarkMessage):
        with self._lock:
            for waiter in self._waiters[:]:
                try:
                    waiter.put_nowait(message)
                except:
                    pass


class MonitorSession:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: Dict[str, Dict] = {}
        return cls._instance
    
    def create_session(self, session_name: str = "") -> str:
        session_id = f"monitor_{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._sessions[session_id] = {
                "id": session_id,
                "name": session_name or session_id,
                "created_at": datetime.now().isoformat(),
                "message_count": 0,
                "active": True
            }
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        with self._lock:
            return self._sessions.get(session_id)
    
    def list_sessions(self) -> List[Dict]:
        with self._lock:
            return list(self._sessions.values())
    
    def stop_session(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["active"] = False
                return True
            return False


class AsyncTaskManager:
    """异步任务管理器"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tasks: Dict[str, Dict] = {}
        return cls._instance
    
    def create_task(self, task_type: str, description: str, 
                    chat_id: str, message_id: str = None) -> str:
        """创建异步任务"""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "type": task_type,
                "description": description,
                "chat_id": chat_id,
                "message_id": message_id,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "started_at": None,
                "completed_at": None,
                "result": None,
                "error": None
            }
        return task_id
    
    def start_task(self, task_id: str) -> bool:
        """开始执行任务"""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "running"
                self._tasks[task_id]["started_at"] = datetime.now().isoformat()
                return True
            return False
    
    def complete_task(self, task_id: str, result: Any = None, error: str = None) -> bool:
        """完成任务"""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "completed" if not error else "failed"
                self._tasks[task_id]["completed_at"] = datetime.now().isoformat()
                self._tasks[task_id]["result"] = result
                self._tasks[task_id]["error"] = error
                return True
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务信息"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def list_tasks(self, status: str = None) -> List[Dict]:
        """列出任务"""
        with self._lock:
            tasks = list(self._tasks.values())
            if status:
                tasks = [t for t in tasks if t["status"] == status]
            return tasks
    
    def clear_completed(self) -> int:
        """清理已完成的任务"""
        with self._lock:
            completed_ids = [tid for tid, t in self._tasks.items() 
                           if t["status"] in ("completed", "failed")]
            for tid in completed_ids:
                del self._tasks[tid]
            return len(completed_ids)


class ConnectionStatus:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._connected = False
            cls._instance._last_message_time = None
            cls._instance._reconnect_count = 0
            cls._instance._message_count = 0
        return cls._instance
    
    def set_connected(self, connected: bool):
        with self._lock:
            self._connected = connected
    
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected
    
    def update_message_time(self):
        with self._lock:
            self._last_message_time = datetime.now()
            self._message_count += 1
    
    def get_status(self) -> Dict:
        with self._lock:
            return {
                "connected": self._connected,
                "last_message_time": self._last_message_time.isoformat() if self._last_message_time else None,
                "reconnect_count": self._reconnect_count,
                "message_count": self._message_count
            }
    
    def increment_reconnect(self):
        with self._lock:
            self._reconnect_count += 1


class MonitorConfig:
    """监控配置管理器"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._primary_chat_id = PRIMARY_CHAT_ID
            cls._instance._config_file = Path(__file__).parent.parent / "monitor_config.json"
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """从配置文件加载配置"""
        try:
            if self._config_file.exists():
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self._primary_chat_id = config.get("primary_chat_id", PRIMARY_CHAT_ID)
                    logger.info(f"已加载监控配置，主群聊ID: {self._primary_chat_id}")
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}，使用默认配置")
    
    def _save_config(self):
        """保存配置到文件"""
        try:
            config = {
                "primary_chat_id": self._primary_chat_id,
                "updated_at": datetime.now().isoformat()
            }
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"配置已保存，主群聊ID: {self._primary_chat_id}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
    
    def get_primary_chat_id(self) -> str:
        """获取主群聊ID"""
        with self._lock:
            return self._primary_chat_id
    
    def set_primary_chat_id(self, chat_id: str):
        """设置主群聊ID"""
        with self._lock:
            self._primary_chat_id = chat_id
            self._save_config()
    
    def is_primary_chat(self, chat_id: str) -> bool:
        """判断是否为主群聊"""
        with self._lock:
            return chat_id == self._primary_chat_id


class ScheduleTaskManager:
    """定时任务管理器"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.scheduler = BackgroundScheduler()
            cls._instance.scheduler.start()
            cls._instance._tasks: Dict[str, Dict] = {}
            cls._instance._task_file = Path(__file__).parent.parent / "schedule_tasks.json"
            cls._instance._load_tasks()
        return cls._instance
    
    def _load_tasks(self):
        """从文件加载任务"""
        try:
            if self._task_file.exists():
                with open(self._task_file, 'r', encoding='utf-8') as f:
                    tasks = json.load(f)
                    for task_id, task_info in tasks.items():
                        self._restore_task(task_info)
                logger.info(f"已加载 {len(self._tasks)} 个定时任务")
        except Exception as e:
            logger.warning(f"加载定时任务失败: {e}")
    
    def _save_tasks(self):
        """保存任务到文件"""
        try:
            tasks_to_save = {}
            for task_id, task_info in self._tasks.items():
                tasks_to_save[task_id] = {
                    "id": task_info["id"],
                    "name": task_info["name"],
                    "trigger_type": task_info["trigger_type"],
                    "trigger_config": task_info["trigger_config"],
                    "chat_id": task_info["chat_id"],
                    "message": task_info["message"],
                    "enabled": task_info["enabled"],
                    "created_at": task_info["created_at"]
                }
            
            with open(self._task_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_to_save, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存 {len(tasks_to_save)} 个定时任务")
        except Exception as e:
            logger.error(f"保存定时任务失败: {e}")
    
    def _restore_task(self, task_info: Dict):
        """恢复任务"""
        try:
            task_id = task_info["id"]
            trigger_type = task_info["trigger_type"]
            trigger_config = task_info["trigger_config"]
            
            if trigger_type == "cron":
                trigger = CronTrigger(**trigger_config)
            elif trigger_type == "interval":
                trigger = IntervalTrigger(**trigger_config)
            else:
                return
            
            job = self.scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                id=task_id,
                args=[task_id],
                replace_existing=True
            )
            
            self._tasks[task_id] = {
                **task_info,
                "job": job
            }
        except Exception as e:
            logger.error(f"恢复任务失败: {e}")
    
    def _execute_task(self, task_id: str):
        """执行任务"""
        try:
            task_info = self._tasks.get(task_id)
            if not task_info or not task_info.get("enabled", True):
                return
            
            chat_id = task_info["chat_id"]
            message = task_info["message"]
            
            # 发送消息
            lark_client.send_message(chat_id, message)
            logger.info(f"定时任务执行成功: {task_info['name']}")
            
        except Exception as e:
            logger.error(f"执行定时任务失败: {e}")
    
    def add_task(self, name: str, trigger_type: str, trigger_config: Dict,
                 chat_id: str, message: str) -> str:
        """添加定时任务"""
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        
        try:
            if trigger_type == "cron":
                trigger = CronTrigger(**trigger_config)
            elif trigger_type == "interval":
                trigger = IntervalTrigger(**trigger_config)
            else:
                raise ValueError(f"不支持的触发器类型: {trigger_type}")
            
            job = self.scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                id=task_id,
                args=[task_id],
                replace_existing=True
            )
            
            task_info = {
                "id": task_id,
                "name": name,
                "trigger_type": trigger_type,
                "trigger_config": trigger_config,
                "chat_id": chat_id,
                "message": message,
                "enabled": True,
                "created_at": datetime.now().isoformat(),
                "job": job
            }
            
            with self._lock:
                self._tasks[task_id] = task_info
                self._save_tasks()
            
            logger.info(f"添加定时任务: {name} ({task_id})")
            return task_id
            
        except Exception as e:
            logger.error(f"添加定时任务失败: {e}")
            raise
    
    def remove_task(self, task_id: str) -> bool:
        """删除定时任务"""
        with self._lock:
            if task_id in self._tasks:
                self.scheduler.remove_job(task_id)
                del self._tasks[task_id]
                self._save_tasks()
                logger.info(f"删除定时任务: {task_id}")
                return True
            return False
    
    def enable_task(self, task_id: str, enabled: bool = True) -> bool:
        """启用/禁用任务"""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["enabled"] = enabled
                self._save_tasks()
                status = "启用" if enabled else "禁用"
                logger.info(f"{status}定时任务: {task_id}")
                return True
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务信息"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return {
                    "id": task["id"],
                    "name": task["name"],
                    "trigger_type": task["trigger_type"],
                    "trigger_config": task["trigger_config"],
                    "chat_id": task["chat_id"],
                    "message": task["message"],
                    "enabled": task["enabled"],
                    "created_at": task["created_at"],
                    "next_run_time": task["job"].next_run_time.isoformat() if task.get("job") else None
                }
            return None
    
    def list_tasks(self) -> List[Dict]:
        """列出所有任务"""
        with self._lock:
            tasks = []
            for task_id, task in self._tasks.items():
                tasks.append({
                    "id": task["id"],
                    "name": task["name"],
                    "trigger_type": task["trigger_type"],
                    "trigger_config": task["trigger_config"],
                    "chat_id": task["chat_id"],
                    "message": task["message"],
                    "enabled": task["enabled"],
                    "created_at": task["created_at"],
                    "next_run_time": task["job"].next_run_time.isoformat() if task.get("job") else None
                })
            return tasks


class LarkClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.client = lark.Client.builder() \
                .app_id(APP_ID) \
                .app_secret(APP_SECRET) \
                .log_level(lark.LogLevel.INFO) \
                .build()
        return cls._instance
    
    def send_message(self, receive_id: str, text: str, receive_id_type: str = "chat_id") -> Dict:
        try:
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()) \
                .build()
            
            response = self.client.im.v1.message.create(request)
            
            if response.success():
                return {"success": True, "message_id": response.data.message_id}
            else:
                return {"success": False, "error": f"{response.code} - {response.msg}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def reply_message(self, message_id: str, text: str) -> Dict:
        try:
            request = ReplyMessageRequest.builder() \
                .message_id(message_id) \
                .request_body(ReplyMessageRequestBody.builder()
                    .msg_type("text")
                    .content(json.dumps({"text": text}))
                    .build()) \
                .build()
            
            response = self.client.im.v1.message.reply(request)
            
            if response.success():
                return {"success": True, "message_id": response.data.message_id}
            else:
                return {"success": False, "error": f"{response.code} - {response.msg}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_chat_list(self, page_size: int = 50) -> Dict:
        try:
            request = GetUserOrBotGroupListReq.builder().page_size(page_size).build()
            response = self.client.im.v1.chat.getUserOrBotGroupList(request)
            
            if response.success():
                chats = []
                if response.data and hasattr(response.data, 'items') and response.data.items:
                    for item in response.data.items:
                        chats.append({
                            "chat_id": item.chat_id,
                            "name": item.name,
                        })
                return {"success": True, "chats": chats}
            else:
                return {"success": False, "error": f"{response.code} - {response.msg}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_chat_info(self, chat_id: str) -> Dict:
        try:
            request = GetChatReq.builder().chat_id(chat_id).build()
            response = self.client.im.v1.chat.get(request)
            
            if response.success():
                chat = response.data.chat
                return {
                    "success": True,
                    "chat_info": {
                        "chat_id": chat.chat_id,
                        "name": chat.name,
                        "description": chat.description if hasattr(chat, 'description') else "",
                        "owner_id": chat.owner_id if hasattr(chat, 'owner_id') else "",
                        "member_count": chat.member_count if hasattr(chat, 'member_count') else 0
                    }
                }
            else:
                return {"success": False, "error": f"{response.code} - {response.msg}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def upload_file(self, file_path: str, folder_token: str = None, 
                    file_name: str = None) -> Dict[str, Any]:
        """上传文件到飞书云文档"""
        try:
            if not os.path.exists(file_path):
                return {"success": False, "error": f"文件不存在: {file_path}"}
            
            path_obj = Path(file_path)
            actual_name = file_name or path_obj.name
            file_ext = path_obj.suffix.lower()
            
            file_type_map = {
                '.docx': 'docx', '.doc': 'doc',
                '.xlsx': 'xlsx', '.xls': 'xls',
                '.pptx': 'pptx', '.ppt': 'ppt',
                '.pdf': 'pdf', '.txt': 'txt', '.csv': 'csv'
            }
            
            if file_ext not in file_type_map:
                return {"success": False, "error": f"不支持的文件类型: {file_ext}"}
            
            from lark_oapi.api.drive.v1 import UploadAllFileRequest, UploadAllFileRequestBody
            
            with open(file_path, 'rb') as f:
                request = UploadAllFileRequest.builder() \
                    .request_body(
                        UploadAllFileRequestBody.builder()
                        .file_name(actual_name)
                        .parent_node(folder_token or "")
                        .parent_type("folder" if folder_token else "ccm")
                        .file(f)
                        .build()
                    ) \
                    .build()
                
                response = self.client.drive.v1.file.upload_all(request)
            
            if not response.success():
                return {"success": False, "error": f"上传失败: {response.msg}", "code": response.code}
            
            return {
                "success": True,
                "message": f"文件上传成功: {actual_name}",
                "file_token": response.data.file_token,
                "file_name": actual_name,
                "file_type": file_type_map[file_ext]
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def upload_to_chat(self, file_path: str, chat_id: str, 
                       file_name: str = None) -> Dict[str, Any]:
        """上传文件并发送到聊天"""
        try:
            if not os.path.exists(file_path):
                return {"success": False, "error": f"文件不存在: {file_path}"}
            
            path_obj = Path(file_path)
            actual_name = file_name or path_obj.name
            
            with open(file_path, 'rb') as f:
                request = CreateFileRequest.builder() \
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type("stream")
                        .file_name(actual_name)
                        .file(f)
                        .build()
                    ) \
                    .build()
                
                response = self.client.im.v1.file.create(request)
            
            if not response.success():
                return {"success": False, "error": f"上传文件失败: {response.msg}"}
            
            file_key = response.data.file_key
            
            content = json.dumps({"file_key": file_key})
            
            msg_request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("file")
                    .content(content)
                    .build()
                ) \
                .build()
            
            msg_response = self.client.im.v1.message.create(msg_request)
            
            if not msg_response.success():
                return {"success": False, "error": f"发送文件消息失败: {msg_response.msg}"}
            
            return {
                "success": True,
                "message": "文件已发送到聊天",
                "file_key": file_key,
                "file_name": actual_name,
                "message_id": msg_response.data.message_id
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}


message_queue = MessageQueue()
wait_queue = MessageWaitQueue()
monitor_session = MonitorSession()
connection_status = ConnectionStatus()
lark_client = LarkClient()
async_task_manager = AsyncTaskManager()
monitor_config = MonitorConfig()
schedule_manager = ScheduleTaskManager()


def handle_message_received(data: P2ImMessageReceiveV1) -> None:
    """
    处理接收到的飞书消息
    
    采用解耦架构：
    1. 消息接收层：快速接收消息，存入队列
    2. 业务处理层：异步处理消息（在message_processor中）
    
    这样可以确保消息接收不被业务处理阻塞
    """
    try:
        event = data.event
        message = event.message
        
        content = json.loads(message.content)
        msg_type = message.message_type
        
        if msg_type != "text":
            return
        
        text = content.get("text", "").strip()
        if not text:
            return
        
        # 判断是否应该处理消息
        chat_id = message.chat_id
        
        if monitor_config.is_primary_chat(chat_id):
            # 主群聊，直接处理
            logger.info(f"主群聊消息: {text}")
        else:
            # 其他群聊，检查是否@了机器人
            if "<at" in text and "</at>" in text:
                logger.info(f"其他群聊@消息: {text}")
            else:
                logger.info(f"忽略非主群聊且未@的消息: {text}")
                return
        
        sender_id = event.sender.sender_id.open_id or event.sender.sender_id.user_id
        sender_name = "未知用户"
        
        # 创建消息对象
        lark_message = LarkMessage(
            message_id=message.message_id,
            chat_id=message.chat_id,
            sender_id=sender_id,
            sender_name=sender_name,
            content=text,
            msg_type=msg_type,
            timestamp=datetime.now().isoformat()
        )
        
        # 添加到消息队列（用于查询）
        message_queue.add_message(lark_message)
        connection_status.update_message_time()
        connection_status.set_connected(True)
        wait_queue.notify_new_message(lark_message)
        
        # 提交到消息处理器进行异步处理
        # 这样业务处理不会阻塞消息接收
        message_processor.submit_message(lark_message.to_dict())
        
    except Exception as e:
        logger.error(f"处理消息异常: {e}")


def create_event_handler() -> lark.EventDispatcherHandler:
    return lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(handle_message_received) \
        .build()


app = Server("lark-mcp-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="lark_get_messages",
            description="获取飞书中接收到的未处理消息列表",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "number", "description": "最多返回的消息数量", "default": 10},
                    "include_processed": {"type": "boolean", "description": "是否包含已处理的消息", "default": False}
                }
            }
        ),
        Tool(
            name="lark_send_message",
            description="向指定的飞书聊天发送文本消息",
            inputSchema={
                "type": "object",
                "required": ["chat_id", "text"],
                "properties": {
                    "chat_id": {"type": "string", "description": "目标聊天的ID"},
                    "text": {"type": "string", "description": "要发送的文本内容"}
                }
            }
        ),
        Tool(
            name="lark_reply_message",
            description="回复指定的飞书消息",
            inputSchema={
                "type": "object",
                "required": ["message_id", "text"],
                "properties": {
                    "message_id": {"type": "string", "description": "要回复的消息ID"},
                    "text": {"type": "string", "description": "回复的文本内容"}
                }
            }
        ),
        Tool(
            name="lark_wait_for_message",
            description="阻塞等待新的飞书消息",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout": {"type": "number", "description": "最长等待时间（秒），0表示无限等待", "default": 0},
                    "chat_id": {"type": "string", "description": "可选，只监听特定聊天的消息"}
                }
            }
        ),
        Tool(
            name="lark_start_monitor",
            description="启动飞书消息监控会话",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_name": {"type": "string", "description": "可选，监控会话名称"}
                }
            }
        ),
        Tool(
            name="lark_get_connection_status",
            description="获取飞书长连接状态信息",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="lark_get_chat_list",
            description="获取机器人所在的群聊列表",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "number", "description": "最多返回的群聊数量", "default": 20}
                }
            }
        ),
        Tool(
            name="lark_clear_queue",
            description="清空消息队列",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="lark_list_monitors",
            description="列出所有监控会话",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="lark_stop_monitor",
            description="停止指定的监控会话",
            inputSchema={
                "type": "object",
                "required": ["session_id"],
                "properties": {
                    "session_id": {"type": "string", "description": "要停止的监控会话ID"}
                }
            }
        ),
        Tool(
            name="lark_mark_processed",
            description="将指定消息标记为已处理",
            inputSchema={
                "type": "object",
                "required": ["message_id"],
                "properties": {
                    "message_id": {"type": "string", "description": "要标记的消息ID"}
                }
            }
        ),
        Tool(
            name="lark_get_chat_info",
            description="获取指定聊天的详细信息",
            inputSchema={
                "type": "object",
                "required": ["chat_id"],
                "properties": {
                    "chat_id": {"type": "string", "description": "聊天ID"}
                }
            }
        ),
        Tool(
            name="lark_upload_file",
            description="上传本地文件到飞书云文档，支持 Word/Excel/PPT/PDF 等格式",
            inputSchema={
                "type": "object",
                "required": ["file_path"],
                "properties": {
                    "file_path": {"type": "string", "description": "本地文件路径"},
                    "folder_token": {"type": "string", "description": "目标文件夹 token（可选）"},
                    "file_name": {"type": "string", "description": "文件名（可选）"}
                }
            }
        ),
        Tool(
            name="lark_send_file_to_chat",
            description="上传文件并发送到指定聊天",
            inputSchema={
                "type": "object",
                "required": ["file_path", "chat_id"],
                "properties": {
                    "file_path": {"type": "string", "description": "本地文件路径"},
                    "chat_id": {"type": "string", "description": "目标聊天 ID"},
                    "file_name": {"type": "string", "description": "文件名（可选）"}
                }
            }
        ),
        Tool(
            name="lark_create_async_task",
            description="创建异步任务，用于长时间运行的操作",
            inputSchema={
                "type": "object",
                "required": ["task_type", "description", "chat_id"],
                "properties": {
                    "task_type": {"type": "string", "description": "任务类型"},
                    "description": {"type": "string", "description": "任务描述"},
                    "chat_id": {"type": "string", "description": "结果发送到的聊天ID"},
                    "message_id": {"type": "string", "description": "关联的消息ID（可选）"}
                }
            }
        ),
        Tool(
            name="lark_get_task_status",
            description="查询异步任务状态",
            inputSchema={
                "type": "object",
                "required": ["task_id"],
                "properties": {
                    "task_id": {"type": "string", "description": "任务ID"}
                }
            }
        ),
        Tool(
            name="lark_list_tasks",
            description="列出所有异步任务",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "筛选状态: pending/running/completed/failed"}
                }
            }
        ),
        Tool(
            name="lark_set_primary_chat",
            description="设置主监听群聊ID",
            inputSchema={
                "type": "object",
                "required": ["chat_id"],
                "properties": {
                    "chat_id": {"type": "string", "description": "主群聊ID"}
                }
            }
        ),
        Tool(
            name="lark_get_primary_chat",
            description="获取当前主监听群聊ID",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="lark_add_schedule_task",
            description="添加定时任务",
            inputSchema={
                "type": "object",
                "required": ["name", "trigger_type", "trigger_config", "chat_id", "message"],
                "properties": {
                    "name": {"type": "string", "description": "任务名称"},
                    "trigger_type": {"type": "string", "description": "触发器类型: cron 或 interval"},
                    "trigger_config": {"type": "object", "description": "触发器配置"},
                    "chat_id": {"type": "string", "description": "目标聊天ID"},
                    "message": {"type": "string", "description": "要发送的消息内容"}
                }
            }
        ),
        Tool(
            name="lark_remove_schedule_task",
            description="删除定时任务",
            inputSchema={
                "type": "object",
                "required": ["task_id"],
                "properties": {
                    "task_id": {"type": "string", "description": "任务ID"}
                }
            }
        ),
        Tool(
            name="lark_list_schedule_tasks",
            description="列出所有定时任务",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="lark_enable_schedule_task",
            description="启用或禁用定时任务",
            inputSchema={
                "type": "object",
                "required": ["task_id", "enabled"],
                "properties": {
                    "task_id": {"type": "string", "description": "任务ID"},
                    "enabled": {"type": "boolean", "description": "是否启用"}
                }
            }
        ),
        Tool(
            name="lark_get_processor_status",
            description="获取消息处理器状态",
            inputSchema={"type": "object", "properties": {}}
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "lark_get_messages":
            limit = arguments.get("limit", 10)
            include_processed = arguments.get("include_processed", False)
            
            if include_processed:
                messages = message_queue.get_all(limit)
            else:
                messages = message_queue.get_unprocessed(limit)
            
            result = {"success": True, "count": len(messages), "messages": [msg.to_dict() for msg in messages]}
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        
        elif name == "lark_send_message":
            chat_id = arguments.get("chat_id")
            text = arguments.get("text")
            result = lark_client.send_message(chat_id, text)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        
        elif name == "lark_reply_message":
            message_id = arguments.get("message_id")
            text = arguments.get("text")
            result = lark_client.reply_message(message_id, text)
            if result.get("success"):
                message_queue.mark_processed(message_id)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        
        elif name == "lark_wait_for_message":
            timeout = arguments.get("timeout", 0)
            chat_id_filter = arguments.get("chat_id")
            
            messages = message_queue.get_unprocessed(limit=1)
            if messages:
                msg = messages[0]
                if not chat_id_filter or msg.chat_id == chat_id_filter:
                    return [TextContent(type="text", text=json.dumps({"success": True, "message": msg.to_dict()}, ensure_ascii=False, indent=2))]
            
            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(None, lambda: wait_queue.wait_for_message(timeout, chat_id_filter))
            
            if message:
                return [TextContent(type="text", text=json.dumps({"success": True, "message": message.to_dict()}, ensure_ascii=False, indent=2))]
            else:
                return [TextContent(type="text", text=json.dumps({"success": False, "timeout": True, "message": "等待超时"}, ensure_ascii=False))]
        
        elif name == "lark_start_monitor":
            session_name = arguments.get("session_name", "")
            session_id = monitor_session.create_session(session_name)
            session_info = monitor_session.get_session(session_id)
            return [TextContent(type="text", text=json.dumps({"success": True, "session": session_info}, ensure_ascii=False, indent=2))]
        
        elif name == "lark_get_connection_status":
            status = connection_status.get_status()
            return [TextContent(type="text", text=json.dumps({"success": True, "connection": status}, ensure_ascii=False, indent=2))]
        
        elif name == "lark_get_chat_list":
            limit = arguments.get("limit", 20)
            result = lark_client.get_chat_list(page_size=limit)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        
        elif name == "lark_clear_queue":
            message_queue.clear()
            return [TextContent(type="text", text=json.dumps({"success": True, "message": "消息队列已清空"}, ensure_ascii=False))]
        
        elif name == "lark_list_monitors":
            sessions = monitor_session.list_sessions()
            return [TextContent(type="text", text=json.dumps({"success": True, "count": len(sessions), "sessions": sessions}, ensure_ascii=False, indent=2))]
        
        elif name == "lark_stop_monitor":
            session_id = arguments.get("session_id")
            result = monitor_session.stop_session(session_id)
            return [TextContent(type="text", text=json.dumps({"success": result, "message": f"会话 {session_id} 已停止" if result else f"会话 {session_id} 不存在"}, ensure_ascii=False))]
        
        elif name == "lark_mark_processed":
            message_id = arguments.get("message_id")
            message_queue.mark_processed(message_id)
            return [TextContent(type="text", text=json.dumps({"success": True}, ensure_ascii=False))]
        
        elif name == "lark_get_chat_info":
            chat_id = arguments.get("chat_id")
            result = lark_client.get_chat_info(chat_id)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        
        elif name == "lark_upload_file":
            file_path = arguments.get("file_path")
            folder_token = arguments.get("folder_token")
            file_name = arguments.get("file_name")
            result = lark_client.upload_file(file_path, folder_token, file_name)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        
        elif name == "lark_send_file_to_chat":
            file_path = arguments.get("file_path")
            chat_id = arguments.get("chat_id")
            file_name = arguments.get("file_name")
            result = lark_client.upload_to_chat(file_path, chat_id, file_name)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        
        elif name == "lark_create_async_task":
            task_type = arguments.get("task_type")
            description = arguments.get("description")
            chat_id = arguments.get("chat_id")
            message_id = arguments.get("message_id")
            task_id = async_task_manager.create_task(task_type, description, chat_id, message_id)
            task_info = async_task_manager.get_task(task_id)
            return [TextContent(type="text", text=json.dumps({"success": True, "task": task_info}, ensure_ascii=False, indent=2))]
        
        elif name == "lark_get_task_status":
            task_id = arguments.get("task_id")
            task_info = async_task_manager.get_task(task_id)
            if task_info:
                return [TextContent(type="text", text=json.dumps({"success": True, "task": task_info}, ensure_ascii=False, indent=2))]
            else:
                return [TextContent(type="text", text=json.dumps({"success": False, "error": f"任务不存在: {task_id}"}, ensure_ascii=False))]
        
        elif name == "lark_list_tasks":
            status = arguments.get("status")
            tasks = async_task_manager.list_tasks(status)
            return [TextContent(type="text", text=json.dumps({"success": True, "count": len(tasks), "tasks": tasks}, ensure_ascii=False, indent=2))]
        
        elif name == "lark_set_primary_chat":
            chat_id = arguments.get("chat_id")
            monitor_config.set_primary_chat_id(chat_id)
            return [TextContent(type="text", text=json.dumps({
                "success": True, 
                "message": f"主群聊已设置为: {chat_id}",
                "primary_chat_id": chat_id
            }, ensure_ascii=False))]
        
        elif name == "lark_get_primary_chat":
            chat_id = monitor_config.get_primary_chat_id()
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "primary_chat_id": chat_id
            }, ensure_ascii=False))]
        
        elif name == "lark_add_schedule_task":
            name_param = arguments.get("name")
            trigger_type = arguments.get("trigger_type")
            trigger_config = arguments.get("trigger_config")
            chat_id = arguments.get("chat_id")
            message = arguments.get("message")
            
            try:
                task_id = schedule_manager.add_task(
                    name=name_param,
                    trigger_type=trigger_type,
                    trigger_config=trigger_config,
                    chat_id=chat_id,
                    message=message
                )
                task_info = schedule_manager.get_task(task_id)
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "task": task_info
                }, ensure_ascii=False, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": str(e)
                }, ensure_ascii=False))]
        
        elif name == "lark_remove_schedule_task":
            task_id = arguments.get("task_id")
            result = schedule_manager.remove_task(task_id)
            return [TextContent(type="text", text=json.dumps({
                "success": result,
                "message": f"任务 {task_id} 已删除" if result else f"任务 {task_id} 不存在"
            }, ensure_ascii=False))]
        
        elif name == "lark_list_schedule_tasks":
            tasks = schedule_manager.list_tasks()
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "count": len(tasks),
                "tasks": tasks
            }, ensure_ascii=False, indent=2))]
        
        elif name == "lark_enable_schedule_task":
            task_id = arguments.get("task_id")
            enabled = arguments.get("enabled")
            result = schedule_manager.enable_task(task_id, enabled)
            return [TextContent(type="text", text=json.dumps({
                "success": result,
                "message": f"任务 {task_id} 已{'启用' if enabled else '禁用'}" if result else f"任务 {task_id} 不存在"
            }, ensure_ascii=False))]
        
        elif name == "lark_get_processor_status":
            # 获取消息处理器状态
            status = {
                "processor_running": message_processor.is_running(),
                "queue_size": message_processor.get_queue_size(),
                "websocket_connected": connection_status.is_connected(),
                "message_count": connection_status.get_status().get("message_count", 0),
                "timestamp": datetime.now().isoformat()
            }
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "status": status
            }, ensure_ascii=False, indent=2))]
        
        else:
            return [TextContent(type="text", text=json.dumps({"success": False, "error": f"未知工具: {name}"}, ensure_ascii=False))]
    
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))]


def run_lark_websocket():
    if not APP_ID or not APP_SECRET:
        logger.error("请配置 APP_ID 和 APP_SECRET 环境变量")
        return
    
    max_retries = 10
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            if retry_count > 0:
                delay = min(1 * (2 ** retry_count), 60)
                logger.info(f"第 {retry_count} 次重连，等待 {delay} 秒...")
                connection_status.increment_reconnect()
                time.sleep(delay)
            
            logger.info("正在启动飞书长连接客户端...")
            connection_status.set_connected(False)
            
            event_handler = create_event_handler()
            
            ws_client = lark.ws.Client(
                APP_ID,
                APP_SECRET,
                event_handler=event_handler,
                log_level=lark.LogLevel.INFO
            )
            
            logger.info("飞书长连接客户端已启动，等待消息...")
            connection_status.set_connected(True)
            retry_count = 0
            ws_client.start()
            
        except Exception as e:
            retry_count += 1
            logger.error(f"飞书长连接异常: {e}，尝试重连 ({retry_count}/{max_retries})")
    
    logger.info("飞书长连接已停止")


async def run_mcp_server():
    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())


async def main():
    # 设置消息处理器的飞书客户端
    message_processor.set_lark_client(lark_client)
    
    # 启动消息处理器（后台异步处理消息）
    message_processor.start()
    logger.info("消息处理器已启动")
    
    # 启动飞书WebSocket连接（接收消息）
    ws_thread = threading.Thread(target=run_lark_websocket, daemon=True)
    ws_thread.start()
    
    await asyncio.sleep(2)
    
    logger.info("MCP Server 启动中...")
    await run_mcp_server()


def run():
    import anyio
    anyio.run(main)


if __name__ == "__main__":
    run()
