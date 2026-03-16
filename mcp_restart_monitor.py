"""
MCP 服务自动重启监控脚本
独立进程，监控 MCP 服务状态，支持自动重启
"""
import os
import sys
import time
import signal
import subprocess
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MCPServiceManager:
    """MCP 服务管理器"""
    
    def __init__(self, config_file: str = "mcp_restart_config.json"):
        self.config_file = Path(config_file)
        self.process: Optional[subprocess.Popen] = None
        self.running = True
        self.restart_count = 0
        self.max_restarts = 10
        self.last_restart_time = 0
        self.min_restart_interval = 10
        
        self.config = self._load_config()
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _load_config(self) -> dict:
        """加载配置"""
        default_config = {
            "mcp_command": "python lark_mcp_server.py",
            "working_dir": str(Path(__file__).parent),
            "auto_restart": True,
            "max_restarts": 10,
            "min_restart_interval": 10,
            "health_check_interval": 30,
            "log_file": "mcp_restart.log"
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
        
        return default_config
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        logger.info(f"收到信号 {signum}，准备停止...")
        self.running = False
        if self.process:
            self.process.terminate()
    
    def start_mcp(self):
        """启动 MCP 服务"""
        try:
            logger.info("正在启动 MCP 服务...")
            
            self.process = subprocess.Popen(
                self.config["mcp_command"],
                shell=True,
                cwd=self.config["working_dir"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            logger.info(f"MCP 服务已启动，PID: {self.process.pid}")
            return True
            
        except Exception as e:
            logger.error(f"启动 MCP 服务失败: {e}")
            return False
    
    def stop_mcp(self):
        """停止 MCP 服务"""
        if self.process:
            try:
                logger.info("正在停止 MCP 服务...")
                self.process.terminate()
                self.process.wait(timeout=10)
                logger.info("MCP 服务已停止")
            except subprocess.TimeoutExpired:
                logger.warning("MCP 服务未响应，强制终止...")
                self.process.kill()
            except Exception as e:
                logger.error(f"停止 MCP 服务失败: {e}")
            finally:
                self.process = None
    
    def restart_mcp(self):
        """重启 MCP 服务"""
        current_time = time.time()
        
        if current_time - self.last_restart_time < self.min_restart_interval:
            wait_time = self.min_restart_interval - (current_time - self.last_restart_time)
            logger.info(f"重启间隔过短，等待 {wait_time:.1f} 秒...")
            time.sleep(wait_time)
        
        if self.restart_count >= self.max_restarts:
            logger.error(f"已达到最大重启次数 ({self.max_restarts})，停止重启")
            return False
        
        logger.info(f"正在重启 MCP 服务 (第 {self.restart_count + 1} 次)...")
        
        self.stop_mcp()
        time.sleep(2)
        
        if self.start_mcp():
            self.restart_count += 1
            self.last_restart_time = time.time()
            return True
        
        return False
    
    def check_health(self) -> bool:
        """检查 MCP 服务健康状态"""
        if not self.process:
            return False
        
        return_code = self.process.poll()
        if return_code is not None:
            logger.warning(f"MCP 服务已退出，返回码: {return_code}")
            return False
        
        return True
    
    def run(self):
        """运行监控循环"""
        logger.info("="*60)
        logger.info("MCP 服务自动重启监控器启动")
        logger.info("="*60)
        logger.info(f"工作目录: {self.config['working_dir']}")
        logger.info(f"MCP 命令: {self.config['mcp_command']}")
        logger.info(f"最大重启次数: {self.config['max_restarts']}")
        logger.info(f"健康检查间隔: {self.config['health_check_interval']}秒")
        logger.info("="*60)
        
        if not self.start_mcp():
            logger.error("初始启动失败，退出监控")
            return
        
        health_check_interval = self.config["health_check_interval"]
        last_check_time = time.time()
        last_signal_check_time = 0
        
        while self.running:
            try:
                current_time = time.time()
                
                # 检查重启信号文件
                if current_time - last_signal_check_time >= 5:
                    if check_restart_signal():
                        logger.info("检测到重启信号，正在重启 MCP 服务...")
                        self.restart_mcp()
                    last_signal_check_time = current_time
                
                if current_time - last_check_time >= health_check_interval:
                    if not self.check_health():
                        if self.config["auto_restart"]:
                            if not self.restart_mcp():
                                logger.error("重启失败，停止监控")
                                break
                    else:
                        logger.debug("MCP 服务运行正常")
                    
                    last_check_time = current_time
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("收到中断信号，准备停止...")
                break
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
                time.sleep(5)
        
        self.stop_mcp()
        logger.info("MCP 服务自动重启监控器已停止")


def create_restart_signal_file():
    """创建重启信号文件"""
    signal_file = Path("mcp_restart.signal")
    signal_file.write_text(datetime.now().isoformat())
    logger.info(f"已创建重启信号文件: {signal_file}")


def check_restart_signal() -> bool:
    """检查是否有重启信号"""
    signal_file = Path("mcp_restart.signal")
    if signal_file.exists():
        signal_file.unlink()
        return True
    return False


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP 服务自动重启监控器")
    parser.add_argument("--config", default="mcp_restart_config.json", help="配置文件路径")
    parser.add_argument("--signal", action="store_true", help="发送重启信号")
    
    args = parser.parse_args()
    
    if args.signal:
        create_restart_signal_file()
        return
    
    manager = MCPServiceManager(config_file=args.config)
    manager.run()


if __name__ == "__main__":
    main()
