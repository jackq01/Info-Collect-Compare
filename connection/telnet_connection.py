import telnetlib
import time
import logging
import re
import socket
from typing import Optional, Tuple, List, Pattern
from datetime import datetime

logger = logging.getLogger(__name__)

class TelnetConnection:
    """Telnet连接管理类 - 优化版，支持大规模回显处理（高性能字节缓冲版）"""
    
    def __init__(self, ip: str, port: int, username: str, password: str):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
        self.tn: Optional[telnetlib.Telnet] = None
        self.connected = False

        # 既保留字符串模式以兼容原有逻辑，也新增字节级提示符模式用于高性能匹配
        self.prompt_pattern: Optional[Pattern] = None           # str 正则（兼容）
        self.prompt_pattern_bytes: Optional[Pattern] = None      # bytes 正则（高性能）

        # 连接参数
        self.connect_timeout = 10
        self.max_retries = 1
        self.read_timeout = 2.0
        self.command_timeout = 300
        self.large_command_timeout = 600
        
        # 登录模式匹配
        self.login_patterns = [
            b'login:', b'Login:', b'Username:', b'username:', 
            b'User Name:', b'user name:', b'User:'
        ]
        self.password_patterns = [
            b'Password:', b'password:', b'Passwd:', b'passwd:'
        ]
        self.prompt_patterns = [b'#', b'$', b'>', b'%']
        self.error_patterns = [b'incorrect', b'error', b'fail', b'invalid', b'denied']
        
    def connect(self) -> bool:
        """建立Telnet连接"""
        retry_count = 0
        
        while retry_count < self.max_retries and not self.connected:
            try:
                logger.info(f"尝试Telnet连接 {self.ip}:{self.port} (尝试 {retry_count + 1}/{self.max_retries})")
                
                # 创建Telnet连接
                self.tn = telnetlib.Telnet(
                    self.ip, 
                    port=self.port, 
                    timeout=self.connect_timeout
                )
                
                # 执行登录流程
                if self._perform_login():
                    self.connected = True
                    # 检测并设置终端参数
                    self._setup_terminal()
                    # 检测命令提示符模式
                    self._detect_prompt_pattern()
                    
                    logger.info(f"Telnet连接成功: {self.ip}:{self.port}")
                    return True
                else:
                    logger.error(f"Telnet登录失败：未检测到登录/密码提示或认证失败，可能端口错误或该端口非Telnet服务。目标 {self.ip}:{self.port}")
                    # 结束连接，避免陷入无限循环
                    self._cleanup_connection()
                    # 计一次重试并跳出当前循环（避免无休止尝试）
                    retry_count += 1
                    break
                    
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                retry_count += 1
                logger.warning(f"Telnet连接失败 (尝试 {retry_count}/{self.max_retries}): {e}")
                self._cleanup_connection()
                
                if retry_count < self.max_retries:
                    # 指数退避策略
                    wait_time = 2 ** retry_count
                    time.sleep(wait_time)
            except Exception as e:
                logger.error(f"意外的连接错误: {e}")
                retry_count += 1
                self._cleanup_connection()
        
        return False
    
    def _perform_login(self) -> bool:
        """执行完整的登录流程"""
        if not self.tn:
            logger.error("Telnet对象未初始化，无法执行登录")
            return False
        try:
            # 读取欢迎信息并等待登录提示
            login_prompt = self._wait_for_patterns(self.login_patterns, timeout=10)
            if not login_prompt:
                logger.error(f"未找到登录提示（等待 10s 超时）。目标 {self.ip}:{self.port} 可能不是Telnet服务或端口错误")
                return False
                
            # 发送用户名
            self.tn.write(self.username.encode('ascii') + b'\n')
            time.sleep(0.3)
            
            # 等待密码提示
            password_prompt = self._wait_for_patterns(self.password_patterns, timeout=10)
            if not password_prompt:
                logger.error(f"未找到密码提示（等待 10s 超时）。请检查登录流程与设备提示是否符合预期，目标 {self.ip}:{self.port}")
                return False
                
            # 发送密码
            self.tn.write(self.password.encode('ascii') + b'\n')
            time.sleep(0.6)
            
            # 验证登录是否成功
            return self._verify_login()
            
        except Exception as e:
            logger.error(f"登录过程出错: {e}")
            return False
    
    def _wait_for_patterns(self, patterns: List[bytes], timeout: int = 10) -> Optional[bytes]:
        """等待匹配指定的模式（字节级）"""
        if not self.tn:
            return None
        try:
            data = b''
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    chunk = self.tn.read_very_eager()
                    if chunk:
                        data += chunk
                        for pattern in patterns:
                            if pattern in data:
                                return pattern
                    else:
                        time.sleep(0.05)
                except (socket.timeout, EOFError):
                    continue
            return None
        except Exception as e:
            logger.warning(f"等待模式时出错: {e}")
            return None
    
    def _verify_login(self) -> bool:
        """验证登录是否成功（字节级）"""
        tn = self.tn
        if not tn:
            logger.error("Telnet对象未初始化，无法验证登录")
            return False
        try:
            start_time = time.time()
            login_data = b''
            
            while time.time() - start_time < 15:
                try:
                    chunk = tn.read_very_eager()
                    if chunk:
                        login_data += chunk
                        # 错误信息判定（小写以覆盖）
                        if any(error in login_data.lower() for error in self.error_patterns):
                            logger.error("登录认证失败")
                            return False
                        # 提示符存在判定
                        if any(prompt in login_data for prompt in self.prompt_patterns):
                            return True
                    else:
                        time.sleep(0.05)
                except (socket.timeout, EOFError):
                    continue
            
            # 最终检查一次
            try:
                final_check = tn.read_very_eager()
                login_data += final_check
            except:
                pass
            
            if any(prompt in login_data for prompt in self.prompt_patterns):
                return True
                
            logger.error("登录超时，未找到命令提示符")
            return False
        except Exception as e:
            logger.error(f"登录验证失败: {e}")
            return False
    
    def _setup_terminal(self):
        """设置终端参数（禁用分页/增宽）"""
        if not self.tn:
            return
        terminal_commands = [
            "terminal length 0",
            "screen-length 0",
            "screen-length disable",
            "terminal width 512",
            "set cli screen-length 0"
        ]
        
        for cmd in terminal_commands:
            try:
                self.tn.write(cmd.encode('ascii') + b'\n')
                time.sleep(0.15)
                # 快速清理响应避免干扰
                try:
                    self.tn.read_very_eager()
                except:
                    pass
            except Exception as e:
                logger.debug(f"执行终端命令 {cmd} 出错: {e}")
                continue
        
        # 清空缓冲区
        try:
            self.tn.read_very_eager()
        except:
            pass
    
    def _detect_prompt_pattern(self):
        """检测命令提示符模式（构建 str/bytes 双正则）"""
        if not self.tn:
            return
        try:
            # 发送空命令获取提示符
            self.tn.write(b'\n')
            time.sleep(0.3)
            
            # 聚合读取更多响应，增强稳定性
            buf = b''
            end_time = time.time() + 2.0
            while time.time() < end_time:
                try:
                    chunk = self.tn.read_very_eager()
                    if chunk:
                        buf += chunk
                        time.sleep(0.02)
                    else:
                        time.sleep(0.02)
                except (socket.timeout, EOFError):
                    break
            
            # 取最后一条非空行作为提示符候选（字节级）
            lines = [ln.strip() for ln in buf.splitlines() if ln.strip()]
            prompt_bytes = lines[-1] if lines else b''
            if prompt_bytes:
                escaped_b = re.escape(prompt_bytes)
                self.prompt_pattern_bytes = re.compile(escaped_b + rb'\s*$')
                # 同步构建字符串正则（兼容性）
                try:
                    prompt_str = prompt_bytes.decode('utf-8', errors='ignore')
                except Exception:
                    prompt_str = ''
                if prompt_str:
                    self.prompt_pattern = re.compile(re.escape(prompt_str) + r'\s*$')
                else:
                    self.prompt_pattern = re.compile(r'[\r\n][\w\-\.:/@]+[#>$%]\s*$')
            else:
                # 回退：通用提示符模式
                self.prompt_pattern_bytes = re.compile(rb'[\r\n][\w\-\.:/@]+[#>$%]\s*$')
                self.prompt_pattern = re.compile(r'[\r\n][\w\-\.:/@]+[#>$%]\s*$')
        except Exception as e:
            logger.warning(f"提示符检测失败: {e}")
            # 使用更宽泛的通用提示符模式作为后备
            self.prompt_pattern_bytes = re.compile(rb'[\r\n][\w\-\.:/@]+[#>$%]\s*$')
            self.prompt_pattern = re.compile(r'[\r\n][\w\-\.:/@]+[#>$%]\s*$')
    
    def execute_command(self, command: str, timeout: int = 300, is_large_output: bool = False) -> Tuple[bool, str]:
        """执行Telnet命令 - 优化版，支持大规模回显"""
        if not self.connected or not self.tn:
            return False, "Telnet连接未建立"
            
        try:
            # 清空输入缓冲区
            try:
                self.tn.read_very_eager()
            except:
                pass
            
            # 发送命令
            full_command = command.encode('ascii') + b'\n'
            self.tn.write(full_command)
            
            # 读取输出
            output = self._read_output(timeout, is_large_output)
            return True, output
        except Exception as e:
            logger.error(f"命令执行错误: {e}")
            return False, f"命令执行错误: {str(e)}"
    
    def _read_output(self, timeout: int, is_large: bool = False) -> str:
        """读取命令输出（高吞吐、低开销、超大回显）"""
        if not self.tn:
            return "Telnet连接未建立"
        import select

        buf = bytearray()
        total_size = 0
        start = time.time()
        # 提升单次命令输出上限到48MB（为BufferManager 50MB总上限留余量）
        max_size = 48 * 1024 * 1024

        # 静默窗口：在该时长内无数据则做轻量探测
        idle_window = 0.6 if not is_large else 1.2
        last_data_ts = time.time()

        # 用于提示符匹配的尾部滑动窗口（字节级）
        tail = bytearray()
        tail_keep = 8192  # 仅在尾部匹配提示符，避免整段扫描

        try:
            fileno = None
            try:
                fileno = self.tn.fileno()
            except Exception:
                fileno = None

            while time.time() - start < timeout:
                ready = []
                if fileno is not None:
                    try:
                        # 更短的select间隔，提升响应度
                        ready, _, _ = select.select([fileno], [], [], 0.1)
                    except Exception:
                        # 某些环境不支持，对齐回退为轮询
                        ready = []

                data = b''
                if ready or fileno is None:
                    # 优先使用更温和的 read_some
                    try:
                        data = self.tn.read_some()
                    except Exception:
                        try:
                            data = self.tn.read_very_eager()
                        except Exception:
                            data = b''

                if data:
                    last_data_ts = time.time()
                    buf.extend(data)
                    total_size += len(data)

                    # 维护尾部窗口用于提示符匹配
                    tail.extend(data)
                    if len(tail) > tail_keep:
                        del tail[:len(tail) - tail_keep]

                    # 输出上限控制
                    if total_size >= max_size:
                        # 超限则直接停止读取
                        break

                    # 字节级提示符检测（尾部窗口）
                    if self.prompt_pattern_bytes and self.prompt_pattern_bytes.search(bytes(tail)):
                        # 等待极短时间收集提示符行残余
                        time.sleep(0.05)
                        try:
                            residue = self.tn.read_very_eager()
                            if residue:
                                buf.extend(residue)
                                tail.extend(residue)
                                if len(tail) > tail_keep:
                                    del tail[:len(tail) - tail_keep]
                        except Exception:
                            pass
                        break
                else:
                    # 无数据，基于静默窗口进行轻量探测
                    if time.time() - last_data_ts >= idle_window:
                        try:
                            # 轻量回车，不高频注入
                            self.tn.write(b'\r')
                            time.sleep(0.08)
                            probe = self.tn.read_very_eager()
                            if probe:
                                buf.extend(probe)
                                total_size += len(probe)
                                tail.extend(probe)
                                if len(tail) > tail_keep:
                                    del tail[:len(tail) - tail_keep]
                                if self.prompt_pattern_bytes and self.prompt_pattern_bytes.search(bytes(tail)):
                                    break
                        except Exception:
                            # 探测失败继续等待直到超时
                            pass
                        # 重置静默计时，避免连续探测
                        last_data_ts = time.time()
                    else:
                        time.sleep(0.02)

            # 统一解码输出
            text = buf.decode('utf-8', errors='ignore')
            if total_size >= max_size:
                text += "\n[输出截断，超过48MB限制]"
            # 归一化：移除空行，使 Telnet 与 SSH 输出一致（每行之间无空行）
            try:
                lines = text.splitlines()
                non_empty = [ln for ln in lines if ln.strip() != '']
                if non_empty:
                    text = "\n".join(non_empty)
            except Exception:
                # 安全回退：如归一化异常则保持原始文本
                pass
            return text
        except Exception as e:
            return f"读取错误: {str(e)}"
    
    def _is_command_complete(self) -> bool:
        """检查命令是否完成（保守判断，作为回退）"""
        tn = self.tn
        if not tn:
            return False
        try:
            # 不主动注入字符，只尝试读取残留
            residual = b''
            try:
                residual = tn.read_very_eager()
            except Exception:
                residual = b''
            if residual:
                if self.prompt_pattern_bytes:
                    return bool(self.prompt_pattern_bytes.search(residual))
                if self.prompt_pattern:
                    # 兼容路径（必要时解码一次）
                    try:
                        text = residual.decode('utf-8', errors='ignore')
                    except Exception:
                        text = ''
                    return bool(self.prompt_pattern.search(text)) if text else False
            return False
        except Exception:
            # 出错时不影响主流程
            return False
    
    def _cleanup_connection(self):
        """清理连接资源"""
        try:
            if self.tn:
                self.tn.close()
        except:
            pass
        finally:
            self.tn = None
            self.connected = False
    
    def close(self):
        """关闭Telnet连接"""
        self._cleanup_connection()
        logger.info(f"Telnet连接已关闭: {self.ip}:{self.port}")
    
    def __del__(self):
        self.close()