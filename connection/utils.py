import re
import time
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class ConnectionUtils:
    """连接工具类"""
    
    @staticmethod
    def is_large_output_command(command: str) -> bool:
        """判断是否为大数据量命令"""
        large_patterns = [
            'display current-configuration',
            'show running-config', 
            'show configuration',
            'display diagnostic-information',
            'show tech-support',
            'display interface',
            'show interface',
            'display ip interface',
            'show ip interface',
            'display version',
            'show version'
        ]
        
        cmd_lower = command.lower()
        return any(pattern in cmd_lower for pattern in large_patterns)
    
    @staticmethod
    def has_command_prompt(output: str) -> bool:
        """检测命令提示符"""
        prompt_patterns = [
            r'[\r\n][\w-]+[>#]\s*$',
            r'[\r\n][\w-]+\([\w-]+\)[>#]\s*$', 
            r'[\r\n]\[[\w-]+\][>#]\s*$',
            r'[\r\n]\S+[>#]\s*$',
            r'[\r\n]\[y/n\]\?\s*$',
            r'[\r\n]--More--\s*$',
            r'[\r\n]Press any key to continue\s*$',
        ]
        
        lines = output.split('\n')
        last_few_lines = lines[-5:] if len(lines) > 5 else lines
        
        for line in last_few_lines:
            line = line.strip()
            for pattern in prompt_patterns:
                if re.search(pattern, line):
                    return True
        
        return False
    
    @staticmethod
    def validate_connection_params(protocol: str, ip: str, port: int, 
                                  username: str, password: str) -> Dict[str, Any]:
        """验证连接参数"""
        errors = []
        
        if protocol not in ['ssh', 'telnet']:
            errors.append("协议必须是 'ssh' 或 'telnet'")
        
        if not ip or not isinstance(ip, str):
            errors.append("IP地址不能为空")
        elif not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
            errors.append("IP地址格式不正确")
        
        if not isinstance(port, int) or port < 1 or port > 65535:
            errors.append("端口号必须在1-65535之间")
        
        if not username or not isinstance(username, str):
            errors.append("用户名不能为空")
        
        if not password or not isinstance(password, str):
            errors.append("密码不能为空")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    @staticmethod
    def format_command_output(command: str, output: str, success: bool = True) -> str:
        """格式化命令输出（去除设备回显中的命令回显，统一换行，确保SSH/Telnet一致）"""
        cmd = (command or "").strip()
        out = output if output is not None else ""
        # 1) 统一换行与无效字符
        out = out.replace("\x00", "")
        # 将 CRLF / CR 统一为 LF，避免平台差异导致逻辑异常
        out = out.replace("\r\n", "\n").replace("\r", "\n")
        # 2) 去掉开头的命令回显行（例如 "<R1>display device" 或 "display device"）
        lines = out.splitlines()
        # 丢弃前导空行
        while lines and lines[0].strip() == "":
            lines.pop(0)
        if lines:
            head = lines[0].strip()
            # 完全相同或以命令结尾（前面可能是提示符/主机名）
            if head == cmd or head.endswith(cmd):
                lines = lines[1:]
        out = "\n".join(lines)
        # 3) 统一块间分隔：命令行 + 回显 + 空行
        return f"{cmd}\n{out}\n\n"
    
    @staticmethod
    def calculate_timeout(command: str, base_timeout: int = 300) -> int:
        """根据命令计算超时时间"""
        if ConnectionUtils.is_large_output_command(command):
            return base_timeout * 2  # 大数据命令双倍超时
        return base_timeout
    
    @staticmethod
    def parse_command_file(file_path: str) -> List[str]:
        """解析命令文件"""
        commands = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):  # 跳过空行和注释
                        commands.append(line)
            return commands
        except Exception as e:
            logger.error(f"解析命令文件失败: {e}")
            return []
    
    @staticmethod
    def generate_filename(mode: str, ip: str, extension: str = "txt") -> str:
        """生成输出文件名"""
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        return f"{mode}-{ip}-{timestamp}.{extension}"
    
    @staticmethod
    def get_performance_stats(start_time: float, total_bytes: int, 
                            completed_commands: int, total_commands: int) -> Dict[str, Any]:
        """获取性能统计信息"""
        duration = time.time() - start_time
        speed = total_bytes / duration / 1024 if duration > 0 else 0
        
        return {
            'duration': round(duration, 2),
            'speed_kb_s': round(speed, 2),
            'total_bytes': total_bytes,
            'completed_commands': completed_commands,
            'total_commands': total_commands,
            'success_rate': round(completed_commands / total_commands * 100, 2) if total_commands > 0 else 0
        }
    
    @staticmethod
    def log_preprocess(protocol: str, step: str, status: str, extra: str = "") -> None:
        """
        统一输出 SSH/Telnet 预处理相关日志，保持一致风格。
        - protocol: 'ssh' 或 'telnet'
        - step: 预处理步骤标识，如 'send_newline'
        - status: 'start' | 'ok' | 'fail'
        - extra: 额外描述信息
        日志格式: "[{PROTOCOL}][PREP][{STEP}][{STATUS}] {extra}"
        """
        proto = (protocol or "").strip().lower()
        proto_tag = proto.upper() if proto in ("ssh", "telnet") else "CONN"
        msg = f"[{proto_tag}][PREP][{step}][{status}] {extra}".rstrip()
        if status == "fail":
            logger.warning(msg)
        else:
            logger.info(msg)
    
    @staticmethod
    def send_newline_before_commands(conn: Any, protocol: str, encoding: str = "utf-8", wait: float = 0.1) -> bool:
        """
        在执行采集命令前，先发送一次换行以唤醒设备提示符/清空残留回显。
        - 通用于 SSH(Paramiko channel/transport) 与 Telnet(telnetlib) 等常见会话对象
        - 自动尝试 send / sendall / write / sendline 等方法，优先发送 str，其次尝试 bytes
        - 统一输出预处理日志，保证 SSH 与 Telnet 的操作日志一致
        返回: True 表示发送成功；False 表示尝试失败（但不抛异常）
        使用示例:
            ConnectionUtils.send_newline_before_commands(ssh_channel, 'ssh')
            ConnectionUtils.send_newline_before_commands(tn, 'telnet')
        """
        ConnectionUtils.log_preprocess(protocol, "send_newline", "start", "发送换行以唤醒提示符")
        if conn is None:
            ConnectionUtils.log_preprocess(protocol, "send_newline", "fail", "连接对象为 None")
            return False
        
        methods = ("send", "sendall", "write", "sendline")
        payload_str = "\n"
        payload_bytes = b"\n"
        errors: List[str] = []
        sent = False
        
        for name in methods:
            if not hasattr(conn, name):
                continue
            try:
                meth = getattr(conn, name)
                # sendline: 部分实现允许 sendline('') 或 sendline() 发送换行
                if name == "sendline":
                    try:
                        meth("")  # 优先尝试空字符串 -> 换行
                    except TypeError:
                        try:
                            meth()  # 无参也可能表示发送换行
                        except Exception as e:
                            errors.append(f"{name}(): {e}")
                            continue
                    sent = True
                else:
                    # 优先发送 str
                    try:
                        meth(payload_str)
                        sent = True
                    except TypeError:
                        # 再尝试 bytes
                        try:
                            meth(payload_bytes)
                            sent = True
                        except Exception as e2:
                            errors.append(f"{name}(bytes): {e2}")
                    except Exception as e1:
                        # 有的实现要求 bytes，再试一次 bytes
                        try:
                            meth(payload_bytes)
                            sent = True
                        except Exception as e2:
                            errors.append(f"{name}: {e1}; bytes: {e2}")
                if sent:
                    break
            except Exception as e:
                errors.append(f"{name}: {e}")
        
        if sent:
            if wait and wait > 0:
                try:
                    time.sleep(wait)
                except Exception:
                    pass
            ConnectionUtils.log_preprocess(protocol, "send_newline", "ok", "已发送换行")
            return True
        
        ConnectionUtils.log_preprocess(protocol, "send_newline", "fail", f"未能发送换行; 尝试错误: {', '.join(errors) if errors else '无'}")
        return False