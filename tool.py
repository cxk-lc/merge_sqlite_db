import os
import sys


def get_path(config_file="config.ini"):
    """获取配置文件的绝对路径"""
    # 如果是以exe方式运行
    if getattr(sys, 'frozen', False):
        # 如果是打包后的exe，使用exe所在目录
        base_path = os.path.dirname(sys.executable)
    else:
        # 如果是脚本运行，使用脚本所在目录
        base_path = os.path.dirname(os.path.abspath(__file__))

    config_path = os.path.join(base_path, config_file)
    return config_path