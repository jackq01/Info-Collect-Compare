import sys
from PyQt5.QtWidgets import QApplication
from ui import NetworkCutoverTool

def main():
    """程序主入口"""
    app = QApplication(sys.argv)
    window = NetworkCutoverTool()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
