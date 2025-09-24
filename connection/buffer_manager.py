import os
import time
from datetime import datetime
from typing import List
import logging

logger = logging.getLogger(__name__)

class BufferManager:
    """缓冲区管理类"""
    
    def __init__(self, output_dir: str, mode: str, ip: str):
        self.output_dir = output_dir
        self.mode = mode
        self.ip = ip
        
        # 缓冲区配置
        self.output_buffer: List[str] = []
        self.buffer_size = 0
        self.max_buffer_size = 5 * 1024 * 1024  # 5MB
        self.max_output_size = 50 * 1024 * 1024  # 50MB
        
        # 统计信息
        self.total_bytes = 0
        self.start_time = time.time()
        self._last_filepath = ""  # 最后创建的文件路径
        
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
    
    def add_data(self, data: str) -> bool:
        """添加数据到缓冲区"""
        data_size = len(data.encode('utf-8'))
        
        # 检查总输出大小限制
        if self.total_bytes + data_size > self.max_output_size:
            logger.warning(f"总输出大小超过{self.max_output_size//1024//1024}MB限制")
            return False
        
        # 检查缓冲区大小，必要时刷新
        if self.buffer_size + data_size > self.max_buffer_size:
            self.flush_buffer()
        
        self.output_buffer.append(data)
        self.buffer_size += data_size
        self.total_bytes += data_size
        
        return True
    
    def flush_buffer(self) -> bool:
        """刷新缓冲区到文件，返回是否成功创建文件"""
        if not self.output_buffer:
            return False
            
        try:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"{self.mode}-{self.ip}-{timestamp}.txt"
            filepath = os.path.join(self.output_dir, filename)
            
            mode = 'a' if os.path.exists(filepath) else 'w'
            with open(filepath, mode, encoding='utf-8', buffering=8192) as f:
                for data in self.output_buffer:
                    f.write(data)
            
            # 清空缓冲区
            self.output_buffer.clear()
            self.buffer_size = 0
            
            logger.debug(f"缓冲区已刷新到文件: {filepath}")
            self._last_filepath = filepath  # 保存最后创建的文件路径
            return True
            
        except Exception as e:
            logger.error(f"文件写入错误: {str(e)}")
            return False
    
    def finalize(self) -> dict:
        """最终处理，返回统计信息和文件路径"""
        # 确保所有数据都写入文件
        self.flush_buffer()
        
        duration = time.time() - self.start_time
        speed = self.total_bytes / duration / 1024 if duration > 0 else 0
        
        # 获取文件路径
        filepath = self._get_last_filepath()
        
        # 确保文件确实存在
        if not os.path.exists(filepath):
            # 如果文件不存在，尝试创建空文件
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("")
            except:
                filepath = ""
        
        return {
            'duration': round(duration, 2),
            'speed_kb_s': round(speed, 2),
            'total_bytes': self.total_bytes,
            'output_dir': self.output_dir,
            'filepath': filepath
        }
    
    def _get_last_filepath(self) -> str:
        """获取最后创建的文件路径"""
        # 如果已经有保存的文件路径，直接返回
        if hasattr(self, '_last_filepath') and self._last_filepath:
            return self._last_filepath
            
        # 否则生成一个新的文件路径
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{self.mode}-{self.ip}-{timestamp}.txt"
        return os.path.join(self.output_dir, filename)
    
    def get_stats(self) -> dict:
        """获取当前统计信息"""
        duration = time.time() - self.start_time
        speed = self.total_bytes / duration / 1024 if duration > 0 else 0
        
        return {
            'duration': round(duration, 2),
            'speed_kb_s': round(speed, 2),
            'total_bytes': self.total_bytes,
            'buffer_size': self.buffer_size,
            'buffered_items': len(self.output_buffer)
        }
    
    def __del__(self):
        """析构时自动刷新缓冲区"""
        try:
            self.flush_buffer()
        except:
            pass