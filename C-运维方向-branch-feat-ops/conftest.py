"""pytest 根配置：确保项目根目录在模块搜索路径中，

使 `python -m pytest` 在任意解释器（含不自动添加 CWD 的精简版 Python）
下都能导入 sim 与 api 包；同时关闭 api 的自动步进定时器
（SIM_AUTO_LOOP=0），测试改用 STEP 指令逐步驱动，保证结果确定性。
"""

import os
import sys
from pathlib import Path

# 必须在导入 api.main 之前生效
os.environ.setdefault("SIM_AUTO_LOOP", "0")

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
