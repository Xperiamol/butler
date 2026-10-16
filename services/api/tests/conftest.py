import os
os.environ.setdefault("BUTLER_DEMO_WORLD", "tiny")   # 单元测试用早期的小型示例资料；公司世界有专门的集成测试
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
