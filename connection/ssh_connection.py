import paramiko
import time
import logging
import re
import socket
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

        self.last_error = ""
        self.last_error_code = ""  # 机器可读错误码：如 'NETWORK_TIMEOUT'、'AUTH_FAILED'

        # 连接参数
        self.connect_timeout = 10
        self.banner_timeout = 10
        self.auth_timeout = 10

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
            code, msg = self._classify_connect_error(e)
            self.last_error_code = code
            self.last_error = msg
            logger.error(f"SSH连接失败[{code}]: {self.last_error}", exc_info=True)
            self.connected = False
            self._cleanup()
            return False

    def _classify_connect_error(self, e: Exception) -> Tuple[str, str]:
        """
        将连接异常分类为清晰的错误码与人性化消息。
        错误码示例：
        - NETWORK_TIMEOUT
        - CONNECTION_REFUSED
        - HOST_UNREACHABLE
        - DNS_RESOLUTION_FAILED
        - AUTH_FAILED
        - HOSTKEY_MISMATCH
        - SSH_PROTOCOL_ERROR
        - CONNECTION_RESET
        - UNKNOWN
        """
        try:
            from paramiko.ssh_exception import (
                AuthenticationException,
                BadAuthenticationType,
                SSHException,
                NoValidConnectionsError,
                BadHostKeyException,
                PartialAuthentication,
                PasswordRequiredException,
                SSHException as _SSHException,
            )
        except Exception:
            AuthenticationException = BadAuthenticationType = SSHException = NoValidConnectionsError = BadHostKeyException = PartialAuthentication = PasswordRequiredException = tuple()  # type: ignore

        err = str(e) or e.__class__.__name__
        el = err.lower()
        et = e.__class__.__name__

        # Windows 常见 WSA 错误码/Posix errno
        errno_val = getattr(e, "errno", None)
        win_err = getattr(e, "winerror", None)
        # socket.error 里有 args[0] 可能是 errno
        arg0 = None
        if hasattr(e, "args") and e.args:
            arg0 = e.args[0]

        def build(code: str, hint: str) -> Tuple[str, str]:
            return code, f"{hint} 原始错误[{et}]：{err}"

        # DNS 解析失败
        if isinstance(e, socket.gaierror) or "name or service not known" in el or "nodename nor servname provided" in el or "temporary failure in name resolution" in el:
            return build("DNS_RESOLUTION_FAILED", f"主机名解析失败：无法解析 {self.ip}。请检查域名拼写与DNS/DNS服务器可达。")

        # 连接超时 / 无可用连接
        if isinstance(e, TimeoutError) or "timed out" in el or "timeout" in el:
            return build("NETWORK_TIMEOUT", f"连接超时：{self.ip}:{self.port} 可能网络不可达、端口未开放或被防火墙/安全组拦截。请检查连通性与端口策略。")
        if isinstance(e, NoValidConnectionsError):
            return build("NETWORK_TIMEOUT", f"无法建立到 {self.ip}:{self.port} 的网络连接：端口未开放或不可达。")

        # 被拒绝
        if isinstance(e, ConnectionRefusedError) or "refused" in el or win_err in (10061,) or errno_val in (111,):
            return build("CONNECTION_REFUSED", f"连接被拒绝：{self.ip}:{self.port} 未监听或被防火墙拦截。请确认 SSH 服务是否运行、端口是否正确。")

        # 主机不可达/网络不可达
        if "no route to host" in el or errno_val in (113,) or win_err in (1231, 1232):
            return build("HOST_UNREACHABLE", f"主机不可达：到 {self.ip} 路由不可达或被网络策略阻断。")
        if "network is unreachable" in el:
            return build("HOST_UNREACHABLE", f"网络不可达：请检查本机网络与路由。")

        # 重置/中断
        if "reset by peer" in el or errno_val in (104,) or win_err in (10054,):
            return build("CONNECTION_RESET", f"连接被对端重置：可能服务端限流/安全策略或中间设备干预。")
        if "connection aborted" in el or win_err in (10053,):
            return build("CONNECTION_RESET", f"连接被中止：网络不稳定或安全设备干预。")

        # 认证问题
        if isinstance(e, (AuthenticationException, BadAuthenticationType)) or "authentication" in el or "auth" in el:
            return build("AUTH_FAILED", "认证失败：用户名/密码/密钥不正确、被禁用或策略限制。请核对凭据与服务端认证策略。")
        if "permission denied" in el:
            return build("AUTH_FAILED", "认证失败：Permission denied。请检查用户名/密码/密钥权限。")
        if "publickey" in el and "denied" in el:
            return build("AUTH_FAILED", "公钥认证失败：公钥未在服务端授权或权限不正确。")

        # 密码需要/密钥口令缺失
        if isinstance(e, PasswordRequiredException) or "private key file is encrypted" in el:
            return build("AUTH_FAILED", "密钥受密码保护但未提供口令。请提供正确的私钥口令或使用可用凭据。")
        if "not a valid rsa private key file" in el:
            return build("AUTH_FAILED", "无效的私钥文件：格式不正确或文件损坏。")

        # HostKey/指纹问题
        if "host key" in el or "fingerprint" in el:
            return build("HOSTKEY_MISMATCH", "主机密钥验证失败：服务器指纹与记录不一致，可能存在中间人风险。请核实并更新已知主机记录。")
        try:
            from paramiko.ssh_exception import BadHostKeyException
            if isinstance(e, BadHostKeyException):
                return build("HOSTKEY_MISMATCH", "主机密钥验证失败：服务器指纹变化。")
        except Exception:
            pass

        # SSH 协议/握手
        if isinstance(e, SSHException) or "protocol" in el or "handshake" in el or "kex" in el or "banner" in el:
            return build("SSH_PROTOCOL_ERROR", "SSH握手/协议错误：协议不匹配、算法受限或服务异常。建议检查服务端SSH版本/算法配置，必要时重启SSH服务。")

        # Socket 超时（更细）
        if isinstance(e, socket.timeout):
            return build("NETWORK_TIMEOUT", f"网络读写超时：{self.ip}:{self.port} 通信迟滞或被限速。")

        # 其他未知
        return build("UNKNOWN", "无法建立SSH连接：请检查网络、端口、凭据与服务状态。")

    # 为兼容旧调用保留原方法名（内部转发）
    def _make_connect_error_message(self, e: Exception) -> str:
        return self._classify_connect_error(e)[1]

    def get_last_error(self) -> str:
        """获取最近一次连接相关的人性化错误消息"""
        return self.last_error or ""

    def get_last_error_detail(self) -> Tuple[str, str]:
        """
        获取最近一次错误的 (错误码, 人性化消息)。
        错误码示例：NETWORK_TIMEOUT / AUTH_FAILED / HOSTKEY_MISMATCH / SSH_PROTOCOL_ERROR / CONNECTION_REFUSED / UNKNOWN
        """
        return self.last_error_code or "", self.last_error or ""

    def get_user_friendly_message(self) -> str:
        """
        面向UI的简短提示，突出最常见且可理解的场景。
        优先根据 last_error_code 映射到简洁中文信息，不暴露敏感细节。
        """
        code = self.last_error_code or ""
        mapping = {
            "AUTH_FAILED": "认证失败：用户名或密码错误，或密钥未授权",
            "DNS_RESOLUTION_FAILED": "设备不可达：无法解析主机名",
            "HOST_UNREACHABLE": "设备不可达：无路由/被网络策略阻断",
            "NETWORK_TIMEOUT": "连接超时：设备不可达或端口未开放/被拦截",
            "CONNECTION_REFUSED": "连接被拒绝：端口未开放或被防火墙拦截",
            "HOSTKEY_MISMATCH": "安全警告：主机指纹变化，请核实后再继续",
            "SSH_PROTOCOL_ERROR": "SSH协议错误：版本/算法不兼容或服务异常",
            "CONNECTION_RESET": "连接中断：对端重置或中间设备干预",
            "UNKNOWN": "连接失败：请检查网络、端口与凭据",
        }
        # 命中映射则返回，未命中则回退更详细的人性化消息
        if code in mapping:
            return mapping[code]
        # 回退：已有的人性化消息（不含敏感信息）
        return self.last_error or "连接失败：请检查网络、端口与凭据"

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
            et = e.__class__.__name__
            msg = str(e) or et
            el = msg.lower()

            # 会话/通道断开
            if "channel closed" in el or "session not active" in el or "closed" in el:
                hint = "会话已断开或通道已关闭：请重新连接后再试。"
            # 超时
            elif "timed out" in el or "timeout" in el:
                hint = "命令执行超时：输出量大或目标阻塞。可提高超时时间，或检查目标主机负载与命令可用性。"
            # 权限/命令不存在
            elif "permission denied" in el or "not found" in el or "command not found" in el:
                hint = "命令权限不足或命令不存在：请检查命令是否正确、当前用户权限及PATH设置。"
            else:
                hint = "命令执行失败：可能原因包括会话断开、网络异常、权限不足、命令不存在或超时等。"

            return False, f"{hint} 原始错误[{et}]：{msg}"

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