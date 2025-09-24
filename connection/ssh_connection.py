import paramiko
import time
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

class SSHConnection:
    """SSH连接管理类（交互式通道版，禁用分页/加宽在同一会话内生效）"""

    def __init__(self, ip: str, port: int, username: str, password: str):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password

        self.ssh: Optional[paramiko.SSHClient] = None
        self.channel: Optional[paramiko.Channel] = None
        self.connected = False

        # 连接参数
        self.connect_timeout = 30
        self.banner_timeout = 30
        self.auth_timeout = 30

        # 提示符模式（字节级高性能匹配）
        self.prompt_pattern_bytes: Optional[re.Pattern[bytes]] = None

        # 读写与限速参数
        self.chunk_size = 16384
        self.max_output_size = 48 * 1024 * 1024  # 48MB，给上层50MB留余量
        self.idle_probe_window = 0.6  # 静默探测窗口

    def connect(self) -> bool:
        """建立SSH连接并打开交互式shell"""
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(
                hostname=self.ip,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.connect_timeout,
                banner_timeout=self.banner_timeout,
                auth_timeout=self.auth_timeout,
                compress=True,
                look_for_keys=False,
                allow_agent=False
            )

            # 打开交互式shell，确保有PTY，设置较宽宽度
            self.channel = self.ssh.invoke_shell(term='vt100', width=512, height=1000)
            self.channel.settimeout(2.0)  # 基础读超时，逐步轮询

            # 读掉banner与初始回显
            time.sleep(0.3)
            self._drain_channel_nonblocking()

            # 探测提示符
            self._detect_prompt()

            self.connected = True
            logger.info(f"SSH连接成功: {self.ip}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"SSH连接失败: {e}")
            self.connected = False
            self._cleanup()
            return False

    def _drain_channel_nonblocking(self):
        """非阻塞清空当前通道缓冲"""
        if not self.channel:
            return
        try:
            while self.channel.recv_ready():
                _ = self.channel.recv(self.chunk_size)
            # 串行设备一般stderr已合并，此处无需单独处理
        except Exception:
            pass

    def _detect_prompt(self):
        """发送空行并从尾部推断提示符，构建字节级正则"""
        if not self.channel:
            return
        try:
            self.channel.send(b'\n')
            time.sleep(0.3)
            buf = bytearray()
            end_time = time.time() + 2.0
            while time.time() < end_time:
                if self.channel.recv_ready():
                    buf.extend(self.channel.recv(self.chunk_size))
                    time.sleep(0.02)
                else:
                    time.sleep(0.02)

            lines = [ln.strip() for ln in bytes(buf).splitlines() if ln.strip()]
            prompt_bytes = lines[-1] if lines else b''
            if prompt_bytes:
                escaped = re.escape(prompt_bytes)
                self.prompt_pattern_bytes = re.compile(escaped + rb'\s*$')
            else:
                # 通用回退
                self.prompt_pattern_bytes = re.compile(rb'[\r\n][\w\-\.:/@]+[#>$%]\s*$')
        except Exception as e:
            logger.warning(f"SSH提示符检测失败: {e}")
            self.prompt_pattern_bytes = re.compile(rb'[\r\n][\w\-\.:/@]+[#>$%]\s*$')

    def execute_command(self, command: str, timeout: int = 300) -> Tuple[bool, str]:
        """执行单个命令（交互式）：发送命令+换行，读取直到提示符出现"""
        if not self.connected or not self.ssh or not self.channel:
            return False, "SSH连接未建立"

        try:
            # 清空残留
            self._drain_channel_nonblocking()

            # 发送命令（确保独立一行）
            to_send = ((command or "").strip() + "\n").encode("utf-8", "ignore")
            self.channel.send(to_send)

            # 读取直到提示符
            output = self._read_until_prompt(timeout=timeout)
            return True, output
        except Exception as e:
            return False, f"命令执行错误: {str(e)}"

    def _read_until_prompt(self, timeout: int = 300) -> str:
        """读取通道输出直到匹配提示符或达到超时/上限"""
        if not self.channel:
            return "通道不可用"

        buf = bytearray()
        tail = bytearray()
        tail_keep = 8192

        total = 0
        start = time.time()
        last_data_ts = time.time()

        try:
            while time.time() - start < timeout:
                if self.channel.recv_ready():
                    data = self.channel.recv(self.chunk_size)
                    if not data:
                        time.sleep(0.02)
                        continue
                    buf.extend(data)
                    tail.extend(data)
                    if len(tail) > tail_keep:
                        del tail[:len(tail) - tail_keep]

                    total += len(data)
                    last_data_ts = time.time()

                    if total >= self.max_output_size:
                        # 超限直接停止，避免占用过大内存
                        break

                    if self.prompt_pattern_bytes and self.prompt_pattern_bytes.search(bytes(tail)):
                        # 轻微等待收集提示符行残余
                        time.sleep(0.05)
                        try:
                            while self.channel.recv_ready():
                                residue = self.channel.recv(self.chunk_size)
                                if not residue:
                                    break
                                buf.extend(residue)
                                tail.extend(residue)
                                if len(tail) > tail_keep:
                                    del tail[:len(tail) - tail_keep]
                        except Exception:
                            pass
                        break
                else:
                    # 静默探测：轻回车一次拉取提示符
                    if time.time() - last_data_ts >= self.idle_probe_window:
                        try:
                            self.channel.send(b'\r')
                        except Exception:
                            pass
                        time.sleep(0.08)
                        # 继续下一轮读取
                        last_data_ts = time.time()
                    else:
                        time.sleep(0.02)

            text = bytes(buf).decode('utf-8', errors='ignore')
            # 规范化换行
            text = text.replace('\x00', '')
            text = re.sub(r'\r+\n', '\n', text).replace('\r', '')
            if total >= self.max_output_size:
                text += "\n[输出截断，超过48MB限制]"
            return text
        except Exception as e:
            return f"读取错误: {str(e)}"

    def _cleanup(self):
        try:
            if self.channel:
                try:
                    self.channel.close()
                except Exception:
                    pass
        finally:
            self.channel = None
        try:
            if self.ssh:
                self.ssh.close()
        except Exception:
            pass
        finally:
            self.ssh = None

    def close(self):
        """关闭SSH连接"""
        self._cleanup()
        self.connected = False
        logger.info(f"SSH连接已关闭: {self.ip}:{self.port}")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass