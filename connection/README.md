# Connection 模块说明

## 模块拆分结构

原始 `connection.py` 文件已按照功能模块拆分为以下文件：

### 核心模块

1. **`connection_worker.py`** - 主工作线程类
   - `HighPerformanceConnectionWorker`: 继承自 QThread 的主工作线程
   - 负责协调 SSH/Telnet 连接、命令执行和结果处理

2. **`ssh_connection.py`** - SSH 连接管理
   - `SSHConnection`: SSH 连接和命令执行类
   - 包含连接建立、命令执行、输出读取等功能

3. **`telnet_connection.py`** - Telnet 连接管理  
   - `TelnetConnection`: Telnet 连接和命令执行类
   - 包含登录流程、终端设置、大数据量读取等功能

### 辅助模块

4. **`buffer_manager.py`** - 缓冲区管理
   - `BufferManager`: 内存缓冲区和文件输出管理
   - 处理大数据量的内存缓冲和文件写入

5. **`utils.py`** - 工具函数
   - `ConnectionUtils`: 包含各种工具方法
   - 命令类型判断、提示符检测、参数验证等

### 入口模块

6. **`__init__.py`** - 包初始化
   - 导出所有公共类和函数
   - 提供统一的导入接口

## 功能保持

所有原始功能都得到了完整保留：

- ✅ SSH 连接和执行命令
- ✅ Telnet 连接和执行命令  
- ✅ 大数据量处理（50MB限制）
- ✅ 内存缓冲区管理（5MB缓冲区）
- ✅ 实时进度和状态更新
- ✅ 错误处理和重试机制
- ✅ 统计信息收集
- ✅ Qt 信号机制

## 使用方式

### 原始方式（兼容）
```python
from connection import HighPerformanceConnectionWorker
```

### 新方式（模块化）
```python
from connection.ssh_connection import SSHConnection
from connection.telnet_connection import TelnetConnection
from connection.buffer_manager import BufferManager
from connection.utils import ConnectionUtils
```

## 优势

1. **代码清晰**: 每个文件职责单一，便于维护
2. **可测试性**: 各模块可以独立测试
3. **可扩展性**: 易于添加新的连接类型或功能
4. **复用性**: 各模块可以在其他项目中复用

## 测试验证

运行 `test_connection_modules.py` 可以验证所有模块功能正常。

## 注意事项

- 保持向后兼容，原有代码无需修改
- 所有公共接口保持不变
- 错误处理和日志机制保持一致