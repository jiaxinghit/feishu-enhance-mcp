"""
消息处理器模块 - 负责异步处理飞书消息

将消息接收和业务处理解耦，确保消息监听不被阻塞
"""

import os
import json
import logging
import threading
import time
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from queue import Queue, Empty
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import *

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """消息处理结果"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class MessageProcessor:
    """
    消息处理器
    
    职责：
    1. 从队列中获取待处理消息
    2. 调用业务逻辑处理消息
    3. 发送处理结果
    4. 标记消息为已处理
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._initialized = True
            self._handlers: Dict[str, Callable] = {}
            self._processing = False
            self._worker_thread: Optional[threading.Thread] = None
            self._message_queue = Queue()
            self._lark_client = None
    
    def set_lark_client(self, client):
        """设置飞书客户端"""
        self._lark_client = client
    
    def register_handler(self, msg_type: str, handler: Callable):
        """注册消息处理器"""
        self._handlers[msg_type] = handler
        logger.info(f"注册消息处理器: {msg_type}")
    
    def submit_message(self, message: Dict[str, Any]):
        """提交消息到处理队列"""
        self._message_queue.put(message)
        logger.info(f"消息已提交到处理队列: {message.get('message_id', 'unknown')}")
    
    def start(self):
        """启动消息处理器"""
        if self._processing:
            logger.warning("消息处理器已在运行")
            return
        
        self._processing = True
        self._worker_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._worker_thread.start()
        logger.info("消息处理器已启动")
    
    def stop(self):
        """停止消息处理器"""
        self._processing = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logger.info("消息处理器已停止")
    
    def _process_loop(self):
        """消息处理主循环"""
        logger.info("消息处理循环已启动")
        
        while self._processing:
            try:
                # 从队列获取消息，超时1秒
                message = self._message_queue.get(timeout=1)
                self._handle_message(message)
            except Empty:
                continue
            except Exception as e:
                logger.error(f"处理消息异常: {e}")
    
    def _handle_message(self, message: Dict[str, Any]):
        """处理单条消息"""
        message_id = message.get('message_id')
        chat_id = message.get('chat_id')
        content = message.get('content', '')
        msg_type = message.get('msg_type', 'text')
        
        logger.info(f"开始处理消息: {message_id}")
        
        try:
            # 查找对应的处理器
            handler = self._handlers.get(msg_type)
            
            if handler:
                # 调用业务处理器
                result = handler(message)
            else:
                # 默认处理：直接回复
                result = ProcessingResult(
                    success=True,
                    message=f"收到消息: {content}",
                    data={"original_content": content}
                )
            
            # 发送回复
            if result and self._lark_client:
                self._send_reply(message_id, chat_id, result)
            
            logger.info(f"消息处理完成: {message_id}")
            
        except Exception as e:
            logger.error(f"处理消息失败 {message_id}: {e}")
            # 发送错误回复
            if self._lark_client:
                error_result = ProcessingResult(
                    success=False,
                    message="处理消息时出错",
                    error=str(e)
                )
                self._send_reply(message_id, chat_id, error_result)
    
    def _send_reply(self, message_id: str, chat_id: str, result: ProcessingResult):
        """发送处理结果回复"""
        try:
            if result.success:
                text = result.message
                if result.data:
                    text += f"\n\n详细信息: {json.dumps(result.data, ensure_ascii=False, indent=2)}"
            else:
                text = f"❌ {result.message}"
                if result.error:
                    text += f"\n错误: {result.error}"
            
            # 使用reply_message回复原消息
            reply_result = self._lark_client.reply_message(message_id, text)
            
            if reply_result.get('success'):
                logger.info(f"回复发送成功: {message_id}")
            else:
                logger.error(f"回复发送失败: {reply_result.get('error')}")
                
        except Exception as e:
            logger.error(f"发送回复异常: {e}")
    
    def get_queue_size(self) -> int:
        """获取待处理消息数量"""
        return self._message_queue.qsize()
    
    def is_running(self) -> bool:
        """检查处理器是否运行中"""
        return self._processing and self._worker_thread and self._worker_thread.is_alive()


# 全局消息处理器实例
message_processor = MessageProcessor()
