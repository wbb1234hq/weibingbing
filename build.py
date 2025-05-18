import PyInstaller.__main__
import os

# 当前目录
current_dir = os.path.dirname(os.path.abspath(__file__))

PyInstaller.__main__.run([
    'main.py',                            # 主程序文件
    '--name=自动文字巡检工具',             # 打包后的程序名称
    '--windowed',                         # 使用窗口模式，不显示控制台
    '--onefile',                          # 打包成单个EXE文件
    # '--icon=icon.ico',                  # 图标文件(如果有)
    '--add-data=config.json;.',           # 添加配置文件
    '--clean',                            # 清理临时文件
    '--noupx',                            # 不使用UPX压缩
    '--noconfirm',                        # 不显示确认对话框
]) 