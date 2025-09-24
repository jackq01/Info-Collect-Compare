import os
import subprocess
import winreg
import chardet
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QRadioButton, QButtonGroup,
                             QTextEdit, QProgressBar, QMessageBox, QFileDialog,
                             QListWidget, QListWidgetItem, QGroupBox, QGridLayout, QDesktopWidget)
from PyQt5.QtCore import Qt
from datetime import datetime

from connection.connection_worker import HighPerformanceConnectionWorker
from config_loader import load_config, get_commands

class NetworkCutoverTool(QMainWindow):
    """主窗口类，负责UI的创建和事件处理"""
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.connection_worker = None
        self.before_files = []
        self.after_files = []
        self.init_ui()
        
    def init_ui(self):
        """初始化UI界面"""
        self.setWindowTitle("网络变更信息采集工具")
        self.resize(1400, 900)
        self.center_on_screen()
        
        self.setStyleSheet(self.load_stylesheet())
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 在最顶端添加命令文件选择
        self.create_command_file_panel(main_layout)
        self.create_control_panel(main_layout)
        self.create_progress_panel(main_layout)
        self.create_files_panel(main_layout)
        self.create_log_panel(main_layout)
        self.create_footer(main_layout)

    def center_on_screen(self):
        """将窗口居中显示"""
        qr = self.frameGeometry()
        cp = QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def create_command_file_panel(self, parent_layout):
        """创建命令文件选择面板（位于最顶端）"""
        file_group = QGroupBox("命令文件")
        file_layout = QHBoxLayout(file_group)
        
        self.command_file_input = QLineEdit("command.txt")
        self.command_file_input.setReadOnly(True)
        file_layout.addWidget(self.command_file_input)
        
        self.select_file_btn = QPushButton("选择文件")
        self.select_file_btn.clicked.connect(self.select_command_file)
        file_layout.addWidget(self.select_file_btn)
        
        parent_layout.addWidget(file_group)

    def create_control_panel(self, parent_layout):
        """创建控制面板"""
        control_layout = QHBoxLayout()
        control_layout.setSpacing(20)
        
        # 设备信息
        device_group = QGroupBox("登录信息")
        device_layout = QGridLayout(device_group)
        
        protocol_layout = QHBoxLayout()
        protocol_layout.addStretch()
        self.ssh_radio = QRadioButton("SSH")
        self.ssh_radio.setChecked(True)
        self.telnet_radio = QRadioButton("Telnet")
        self.protocol_group = QButtonGroup()
        self.protocol_group.addButton(self.ssh_radio)
        self.protocol_group.addButton(self.telnet_radio)
        protocol_layout.addWidget(self.ssh_radio)
        protocol_layout.addWidget(self.telnet_radio)
        protocol_layout.addStretch()
        device_layout.addLayout(protocol_layout, 0, 0, 1, 2)
        
        device_layout.addWidget(QLabel("IP地址:"), 1, 0)
        # self.ip_input = QLineEdit("192.168.56.10")
        self.ip_input.setPlaceholderText("192.168.1.1 或 192.168.1.1:2222")
        device_layout.addWidget(self.ip_input, 1, 1)
        
        device_layout.addWidget(QLabel("用户名:"), 2, 0)
        # self.user_input = QLineEdit("admin")
        device_layout.addWidget(self.user_input, 2, 1)
        
        device_layout.addWidget(QLabel("密   码:"), 3, 0)
        # self.pass_input = QLineEdit("admin")
        self.pass_input.setEchoMode(QLineEdit.Password)
        device_layout.addWidget(self.pass_input, 3, 1)
        
        control_layout.addWidget(device_group, 3)

        # 采集模式
        mode_group = QGroupBox("采集模式")
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setAlignment(Qt.AlignCenter)
        self.mode_before = QRadioButton("变更前")
        self.mode_before.setMinimumHeight(40)
        self.mode_before.setChecked(True)
        self.mode_after = QRadioButton("变更后")
        self.mode_after.setMinimumHeight(40)
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.mode_before)
        self.mode_group.addButton(self.mode_after)
        mode_layout.addWidget(self.mode_before)
        mode_layout.addWidget(self.mode_after)
        control_layout.addWidget(mode_group, 1)

        # 操作控制
        button_group = QGroupBox("执行操作")
        button_layout = QVBoxLayout(button_group)
        button_layout.setAlignment(Qt.AlignCenter)
        self.start_btn = QPushButton("开始采集")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self.start_collection)
        self.compare_btn = QPushButton("文件比对")
        self.compare_btn.setObjectName("compareBtn")
        self.compare_btn.setMinimumHeight(40)
        self.compare_btn.clicked.connect(self.compare_files)
        self.compare_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.compare_btn)
        control_layout.addWidget(button_group, 1)
        
        parent_layout.addLayout(control_layout)

    def create_progress_panel(self, parent_layout):
        """创建进度显示面板"""
        progress_group = QGroupBox("采集进度")
        progress_layout = QVBoxLayout(progress_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("就绪")
        self.status_label.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.status_label)
        parent_layout.addWidget(progress_group)

    def create_files_panel(self, parent_layout):
        """创建文件列表面板"""
        files_group = QGroupBox("文件列表")
        files_layout = QHBoxLayout(files_group)
        
        before_widget = QWidget()
        before_layout = QVBoxLayout(before_widget)
        before_layout.addWidget(QLabel("变更前文件", alignment=Qt.AlignCenter))
        self.before_list = QListWidget()
        self.before_list.itemDoubleClicked.connect(lambda item: self.view_file(item))
        before_layout.addWidget(self.before_list)
        files_layout.addWidget(before_widget)
        
        after_widget = QWidget()
        after_layout = QVBoxLayout(after_widget)
        after_layout.addWidget(QLabel("变更后文件", alignment=Qt.AlignCenter))
        self.after_list = QListWidget()
        self.after_list.itemDoubleClicked.connect(lambda item: self.view_file(item))
        after_layout.addWidget(self.after_list)
        files_layout.addWidget(after_widget)
        
        parent_layout.addWidget(files_group, 1)

    def create_log_panel(self, parent_layout):
        """创建日志显示面板"""
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        parent_layout.addWidget(log_group)

    def create_footer(self, parent_layout):
        """创建底部信息栏"""
        note_label = QLabel("说明：软件用于信息采集和比对，请勿用于配置下发。")
        note_label.setStyleSheet("color: red; font-size: 12px; font-weight: bold; padding: 5px;")
        note_label.setAlignment(Qt.AlignRight)
        parent_layout.addWidget(note_label)

        developer_label = QLabel("开发者：运营商服务部 任富强（如有问题，请帮忙反馈）")
        developer_label.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        developer_label.setAlignment(Qt.AlignLeft)
        parent_layout.addWidget(developer_label)

    def show_styled_message_box(self, icon, title, text):
        """显示自定义样式的消息框"""
        msg_box = QMessageBox(self)
        msg_box.setIcon(icon)
        msg_box.setWindowTitle(title)
        msg_box.setText(text)
        # 应用与主窗口类似的样式
        msg_box.setStyleSheet(self.load_stylesheet() + """
            QMessageBox {
                background-color: #f5f5f5;
                border: 2px solid #cccccc;
                border-radius: 8px;
            }
            QMessageBox QLabel {
                color: #2c3e50;
                font-size: 14px;
            }
            QMessageBox QPushButton {
                background-color: #3498db;
                border: none;
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                min-width: 80px;
            }
            QMessageBox QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        msg_box.exec_()

    def select_command_file(self):
        """选择命令文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择命令文件", "", 
            "文本文件 (*.txt *.log *.cfg *.conf *.ini);;所有文件 (*)"
        )
        if file_path:
            self.command_file_input.setText(file_path)
            self.log_message(f"选择命令文件: {file_path}")

    def get_commands_from_file(self, file_path):
        """从指定文件读取命令列表，支持多种文本格式和编码检测"""
        if not os.path.exists(file_path):
            return None, f"找不到文件: {file_path}"
        
        try:
            # 检测文件编码
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                encoding_result = chardet.detect(raw_data)
                encoding = encoding_result['encoding'] or 'utf-8'
            
            # 使用检测到的编码读取文件
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                commands = []
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释行（以#开头的行）
                    if line and not line.startswith('#'):
                        commands.append(line)
                
            if not commands:
                return None, f"文件 {file_path} 中没有有效的命令"
                
            self.log_message(f"成功读取文件: {file_path} (编码: {encoding}, 命令数: {len(commands)})")
            return commands, None
            
        except UnicodeDecodeError:
            # 如果自动检测的编码失败，尝试常见编码
            encodings = ['utf-8', 'gbk', 'gb2312', 'ascii', 'latin-1']
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                        commands = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
                    
                    if commands:
                        self.log_message(f"使用编码 {encoding} 成功读取文件: {file_path}")
                        return commands, None
                except:
                    continue
            return None, f"无法解码文件: {file_path}，请检查文件编码"
            
        except Exception as e:
            return None, f"读取文件失败: {str(e)}"

    def log_message(self, message):
        """记录日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def start_collection(self):
        """开始采集信息"""
        ip_str = self.ip_input.text().strip()
        username = self.user_input.text().strip()
        password = self.pass_input.text().strip()
        protocol = 'ssh' if self.ssh_radio.isChecked() else 'telnet'

        if not all([ip_str, username]):
            self.show_styled_message_box(QMessageBox.Warning, "警告", "请填写IP地址和用户名")
            return

        if ':' in ip_str:
            parts = ip_str.split(':')
            ip = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                self.show_styled_message_box(QMessageBox.Warning, "警告", "端口号无效，请输入一个数字。")
                return
        else:
            ip = ip_str
            port = 22 if protocol == 'ssh' else 23
        
        # 获取选择的命令文件路径
        command_file = self.command_file_input.text().strip()
        commands, error = self.get_commands_from_file(command_file)
        if error:
            self.show_styled_message_box(QMessageBox.Warning, "警告", error)
            return
        
        mode = "变更前" if self.mode_before.isChecked() else "变更后"
        date_str = datetime.now().strftime("%Y%m%d")
        output_dir = f"变更-{date_str}"
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.connection_worker = HighPerformanceConnectionWorker(protocol, ip, port, username, password, commands, mode, output_dir)
        self.connection_worker.progress_signal.connect(self.update_progress)
        self.connection_worker.finished_signal.connect(self.collection_finished)
        self.connection_worker.error_signal.connect(self.handle_error)
        self.connection_worker.start()
    
    def update_progress(self, value, message):
        """更新进度条和状态标签"""
        self.progress_bar.setValue(value)
        self.status_label.setText(message)
        self.log_message(message)
    
    def collection_finished(self, filepath, success, mode):
        """采集完成后的处理"""
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if success:
            if mode == "变更前":
                self.before_files.append(filepath)
                self.refresh_file_list(self.before_list, self.before_files)
            else:
                self.after_files.append(filepath)
                self.refresh_file_list(self.after_list, self.after_files)
            
            self.compare_btn.setEnabled(len(self.before_files) > 0 and len(self.after_files) > 0)
            self.log_message(f"采集完成（{mode}），文件已保存到: {filepath}")
            self.show_styled_message_box(QMessageBox.Information, "完成", f"采集完成，文件已保存到: {filepath}")
        else:
            self.log_message("采集失败")
            self.show_styled_message_box(QMessageBox.Warning, "失败", "采集失败")
    
    def handle_error(self, error_message):
        """处理采集过程中的错误"""
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.log_message(f"错误: {error_message}")
        self.show_styled_message_box(QMessageBox.Critical, "错误", error_message)
    
    def refresh_file_list(self, list_widget, files):
        """刷新文件列表"""
        list_widget.clear()
        for filepath in files:
            filename = os.path.basename(filepath)
            item = QListWidgetItem(filename)
            item.setData(Qt.UserRole, filepath)
            list_widget.addItem(item)
    
    def view_file(self, item):
        """查看文件内容"""
        filepath = item.data(Qt.UserRole)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 使用一个非模态对话框来显示文件内容
            dialog = QTextEdit()
            dialog.setWindowTitle(f"查看文件 - {os.path.basename(filepath)}")
            dialog.setPlainText(content)
            dialog.setReadOnly(True)
            dialog.resize(800, 600)
            dialog.setAttribute(Qt.WA_DeleteOnClose) # 关闭时自动删除
            dialog.show()
        except Exception as e:
            self.show_styled_message_box(QMessageBox.Warning, "错误", f"无法读取文件: {str(e)}")
    
    def compare_files(self):
        """使用Beyond Compare比对文件"""
        before_item = self.before_list.currentItem()
        after_item = self.after_list.currentItem()

        # 如果未选择，但列表中只有一个文件，则自动选择该文件
        if not before_item and self.before_list.count() == 1:
            before_item = self.before_list.item(0)
            self.before_list.setCurrentItem(before_item)
            self.log_message(f"自动选择变更前唯一文件: {before_item.text()}")
        if not after_item and self.after_list.count() == 1:
            after_item = self.after_list.item(0)
            self.after_list.setCurrentItem(after_item)
            self.log_message(f"自动选择变更后唯一文件: {after_item.text()}")

        if not before_item or not after_item:
            self.show_styled_message_box(QMessageBox.Warning, "警告", "请在“变更前”和“变更后”文件列表中各选择一个文件进行比对。")
            return

        before_file = before_item.data(Qt.UserRole)
        after_file = after_item.data(Qt.UserRole)
        
        bc_path = self._get_bc_path()
        
        if bc_path and os.path.exists(bc_path):
            try:
                cmd = f'"{bc_path}" "{before_file}" "{after_file}"'
                subprocess.Popen(cmd, shell=True)
                self.log_message(f"启动Beyond Compare比对: {os.path.basename(before_file)} 和 {os.path.basename(after_file)}")
            except Exception as e:
                self.log_message(f"Beyond Compare启动失败: {str(e)}")
                self.show_styled_message_box(QMessageBox.Warning, "错误", f"Beyond Compare启动失败: {str(e)}")
        else:
            self.show_styled_message_box(QMessageBox.Warning, "配置错误", "找不到Beyond Compare程序。\n请在config.ini中配置正确路径，或确保已安装Beyond Compare。")

    def _get_bc_path(self):
        """获取Beyond Compare路径，优先从配置读取，失败则自动查找"""
        # 1. 优先从config.ini获取
        config_path = self.config.get('DEFAULT', 'beyond_compare_path', fallback='').strip('"')
        if config_path and os.path.exists(config_path):
            self.log_message(f"从配置文件加载Beyond Compare路径: {config_path}")
            return config_path
        
        # 2. 如果配置无效，自动查找
        self.log_message("配置文件中未找到有效路径，开始自动查找Beyond Compare...")
        auto_path = self.__get_auto_bc_path()
        if auto_path:
            self.log_message(f"自动查找到Beyond Compare路径: {auto_path}")
            return auto_path
            
        return None

    def __get_auto_bc_path(self):
        """自动查找Beyond Compare路径"""
        # 2a. 从注册表查找
        reg_paths = [
            (winreg.HKEY_CURRENT_USER, r"Software\Scooter Software\Beyond Compare 4"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Scooter Software\Beyond Compare 4"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Scooter Software\Beyond Compare 4")
        ]
        for hkey, subkey in reg_paths:
            path = self.__query_registry(hkey, subkey)
            if path and os.path.exists(path):
                return path

        # 2b. 从常见路径查找
        default_paths = [
            r"D:\Program Files\Beyond Compare 4\BCompare.exe",
            r"C:\Program Files\Beyond Compare 4\BCompare.exe",
            os.path.expanduser(r"~\AppData\Roaming\Scooter Software\Beyond Compare 4\BCompare.exe")
        ]
        for path in default_paths:
            if os.path.exists(path):
                return path

        return None

    def __query_registry(self, hkey, subkey):
        """安全查询注册表，同时检查32位和64位视图"""
        for access_mask in [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]:
            try:
                access = winreg.KEY_READ | access_mask
                with winreg.OpenKey(hkey, subkey, 0, access) as key:
                    path, _ = winreg.QueryValueEx(key, "ExePath")
                    if path:
                        return path.strip('"')
            except WindowsError:
                continue # 找不到键，继续下一个视图
        return None

    def load_stylesheet(self):
        """加载QSS样式表"""
        return """
            * { font-family: "Microsoft YaHei", "微软雅黑"; font-size: 12px; }
            QMainWindow { background-color: #f5f5f5; }
            QGroupBox {
                font-weight: bold; border: 2px solid #cccccc; border-radius: 8px;
                margin-top: 1ex; padding-top: 10px; background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #2c3e50;
            }
            QPushButton {
                background-color: #3498db; border: none; color: white;
                padding: 8px 16px; border-radius: 6px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton:disabled { background-color: #bdc3c7; }
            QPushButton#startBtn { background-color: #27ae60; }
            QPushButton#startBtn:hover { background-color: #229954; }
            QPushButton#compareBtn { background-color: #e74c3c; }
            QPushButton#compareBtn:hover { background-color: #c0392b; }
            QLineEdit { padding: 6px; border: 2px solid #bdc3c7; border-radius: 4px; }
            QLineEdit:focus { border-color: #3498db; }
            QRadioButton { spacing: 8px; font-weight: bold; }
            QListWidget {
                border: 1px solid #cccccc; border-radius: 4px; background-color: white;
                alternate-background-color: #f8f9fa;
            }
            QListWidget::item:selected { background-color: #3498db; color: white; }
            QTextEdit {
                border: 1px solid #cccccc; border-radius: 4px; background-color: white;
                font-family: 'Consolas', 'Courier New', monospace;
            }
            QProgressBar {
                border: 2px solid #bdc3c7; border-radius: 6px; text-align: center;
                background-color: white;
            }
            QProgressBar::chunk { background-color: #3498db; border-radius: 4px; }
        """
