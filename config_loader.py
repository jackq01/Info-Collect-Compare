import os
import configparser

def load_config():
    """加载或创建配置文件"""
    config = configparser.ConfigParser()
    if os.path.exists('config.ini'):
        config.read('config.ini', encoding='utf-8')
    else:
        config['DEFAULT'] = {
            'beyond_compare_path': 'C:\\Program Files\\Beyond Compare 4\\BCompare.exe'
        }
        with open('config.ini', 'w', encoding='utf-8') as configfile:
            config.write(configfile)
    return config

def get_commands():
    """从command.txt读取命令列表"""
    if not os.path.exists('command.txt'):
        return None, "找不到command.txt文件"
    
    with open('command.txt', 'r', encoding='utf-8') as f:
        commands = [line.strip() for line in f if line.strip()]
        
    if not commands:
        return None, "command.txt文件中没有有效的命令"
        
    return commands, None
