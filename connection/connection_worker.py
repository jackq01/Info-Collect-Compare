import time
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional
import re
from PyQt5.QtCore import QThread, pyqtSignal

from .ssh_connection import SSHConnection
from .telnet_connection import TelnetConnection
from .buffer_manager import BufferManager
from .utils import ConnectionUtils

logger = logging.getLogger(__name__)

class HighPerformanceConnectionWorker(QThread):
    """高性能连接工作线程"""
    
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(str, bool, str, dict)
    error_signal = pyqtSignal(str, str)
    data_chunk_signal = pyqtSignal(str, int)

    def __init__(self, protocol: str, ip: str, port: int, username: str, 
                 password: str, commands: List[str], mode: str, output_dir: str):
        super().__init__()
        self.protocol = protocol
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
        self.commands = commands
        self.mode = mode
        self.output_dir = output_dir
        self.is_running = True
        
        # 性能参数
        self.command_timeout = 300
        self.large_command_timeout = 600
        
        # 连接对象
        self.connection = None
        self.buffer_manager = None
        
        # 统计信息
        self.stats = {
            'total_commands': len(commands),
            'completed_commands': 0,
            'failed_commands': 0,
            'total_bytes': 0,
            'start_time': None,
            'end_time': None
        }

    def run(self):
        """主运行方法"""
        self.stats['start_time'] = time.time()
        
        # 验证参数
        validation = ConnectionUtils.validate_connection_params(
            self.protocol, self.ip, self.port, self.username, self.password
        )
        if not validation['valid']:
            self.error_signal.emit("validation", "; ".join(validation['errors']))
            return
        
        try:
            # 初始化缓冲区管理器
            self.buffer_manager = BufferManager(self.output_dir, self.mode, self.ip)
            
            # 建立连接
            if self.protocol == 'ssh':
                self._run_ssh()
            elif self.protocol == 'telnet':
                self._run_telnet()
                
        except Exception as e:
            self.error_signal.emit("runtime", f"运行错误: {str(e)}")
        finally:
            self.stats['end_time'] = time.time()
            self._finalize()

    def _run_ssh(self):
        """运行SSH连接"""
        try:
            self.connection = SSHConnection(self.ip, self.port, self.username, self.password)
            self.progress_signal.emit(5, f"SSH连接中 {self.ip}:{self.port}...")
            
            if not self.connection.connect():
                raise Exception("SSH连接失败")
                
            self.progress_signal.emit(10, "SSH连接成功")
            self._prepare_ssh_terminal()
            self._execute_commands()
            
        except Exception as e:
            self.error_signal.emit("ssh", f"SSH错误: {str(e)}")

    def _prepare_ssh_terminal(self):
        """SSH连接后预处理：关闭分页/扩展宽度，避免输出被分页截断"""
        pre_commands = [
            "terminal length 0",
            "screen-length 0",
            "screen-length disable",
            "terminal width 512",
            "set cli screen-length 0",
        ]
        # 发日志：开始预处理
        # self.progress_signal.emit(12, "SSH预处理：设置无分页/宽度...")
        for cmd in pre_commands:
            try:
                # 发送每条预处理命令并记录到操作日志
                # self.progress_signal.emit(12, f"SSH预处理执行: {cmd}")
                # 对SSH，execute_command(command, timeout)
                self.connection.execute_command(cmd, timeout=10)
            except Exception:
                # 某些设备不支持命令，忽略错误，继续尝试下一条
                continue
        # 发日志：预处理完成
        # self.progress_signal.emit(15, "SSH预处理完成")
    
    def _run_telnet(self):
        """运行Telnet连接"""
        try:
            self.connection = TelnetConnection(self.ip, self.port, self.username, self.password)
            self.progress_signal.emit(5, f"Telnet连接中 {self.ip}:{self.port}...")
            
            if not self.connection.connect():
                raise Exception("Telnet连接失败")
                
            self.progress_signal.emit(15, "Telnet连接成功")
            self._execute_commands()
            
        except Exception as e:
            self.error_signal.emit("telnet", f"Telnet错误: {str(e)}")

    def _sanitize_command(self, cmd: str) -> str:
        """移除BOM/零宽/控制字符与提示符片段，标准化空白，避免SSH下发异常拼接"""
        if cmd is None:
            return ""
        # 去BOM
        cmd = cmd.replace("\\ufeff", "")
        # 去零宽与非常见不可见字符
        zero_width = r"[\\u200B-\\u200F\\u202A-\\u202E\\u2060-\\u206F\\uFEFF]"
        cmd = re.sub(zero_width, "", cmd)
        # 去控制字符（除制表与常规空格外）
        cmd = re.sub(r"[\\x00-\\x08\\x0B-\\x1F\\x7F]", "", cmd)
        # 去设备提示符前缀，如 <R1>
        cmd = re.sub(r"^<[^>]*>\\s*", "", cmd)
        # 标准化空白
        cmd = re.sub(r"\\s+", " ", cmd).strip()
        return cmd

    def _execute_commands(self):
        """执行所有命令"""
        for i, cmd in enumerate(self.commands):
            if not self.is_running:
                break
                
            progress = 10 + int(80 * i / len(self.commands))
            self.progress_signal.emit(progress, f"执行: {cmd[:50]}...")
            
            try:
                # 计算超时时间
                is_large_output = ConnectionUtils.is_large_output_command(cmd)
                timeout = self.large_command_timeout if is_large_output else self.command_timeout
                
                # 执行命令
                if isinstance(self.connection, SSHConnection):
                    success, output = self.connection.execute_command(cmd, timeout)
                elif isinstance(self.connection, TelnetConnection):
                    success, output = self.connection.execute_command(cmd, timeout, is_large_output)
                else:
                    success, output = False, "连接类型不支持"
                
                # 格式化并保存输出
                formatted_output = ConnectionUtils.format_command_output(cmd, output, success)
                if self.buffer_manager.add_data(formatted_output):
                    self.stats['completed_commands'] += 1
                else:
                    self.stats['failed_commands'] += 1
                    
            except Exception as e:
                self.stats['failed_commands'] += 1
                error_output = ConnectionUtils.format_command_output(cmd, f"错误: {str(e)}", False)
                self.buffer_manager.add_data(error_output)
                logger.error(f"命令执行失败: {cmd}, 错误: {e}")

    def _finalize(self):
        """最终处理"""
        if self.connection:
            self.connection.close()
        
        if self.buffer_manager:
            final_stats = self.buffer_manager.finalize()
            
            # 合并统计信息
            stats_info = {
                'duration': round(self.stats['end_time'] - self.stats['start_time'], 2),
                'total_commands': self.stats['total_commands'],
                'completed_commands': self.stats['completed_commands'],
                'failed_commands': self.stats['failed_commands'],
                'total_bytes': final_stats['total_bytes'],
                'speed_kb_s': final_stats['speed_kb_s']
            }
            
            # 使用完整的文件路径而不是仅文件名
            filepath = final_stats.get('filepath', '')
            if not filepath:
                # 如果无法获取文件路径，回退到生成文件名
                filepath = os.path.join(
                    self.output_dir,
                    ConnectionUtils.generate_filename(self.mode, self.ip)
                )
            
            self.finished_signal.emit(
                filepath,  # 传递完整文件路径
                True,
                self.mode,
                stats_info
            )

    def stop(self):
        """停止采集"""
        self.is_running = False
        if self.connection:
            self.connection.close()