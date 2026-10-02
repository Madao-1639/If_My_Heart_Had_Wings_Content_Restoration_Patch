"""逐脚本中文产物的读取口径（`resource/fan_cn/{SCRIPT}.json`，idx → 中文文本）。

主产物不是 `.lng`：原版脚本不消费 lng，Steam 版也要先按官方改动改造才能装载，
所以持久存储用扁平 JSON（只写有行的槽位，缺失 key = 该槽无行）。`.lng` 由
`script/build_fan_translations.py --emit-lng` 按需派生。

`load_texts` 刻意与 `tool.lng.parse_lng` 同形（按 idx 展开的列表，空洞为空串），
复检脚本换读取源不必改判定逻辑。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / 'resource' / 'fan_cn'
NOT_SCRIPT_FILES = {'manifest', 'NameTable'}


def script_names(root=DEFAULT_DIR):
    return sorted(p.stem for p in Path(root).glob('*.json')
                  if p.stem not in NOT_SCRIPT_FILES)


def load_map(name, root=DEFAULT_DIR):
    """单脚本 → {idx: 文本}。"""
    d = json.loads((Path(root) / f'{name}.json').read_text('utf-8'))
    return {int(k): v for k, v in d.items()}


def load_texts(name, root=DEFAULT_DIR):
    """单脚本 → 按 idx 展开的文本列表，空洞为空串。"""
    m = load_map(name, root)
    size = (max(m) + 1) if m else 0
    return [m.get(i, '') for i in range(size)]


def load_name_table(root=DEFAULT_DIR):
    """%LC<日文名> → 中文显示名。"""
    return json.loads((Path(root) / 'NameTable.json').read_text('utf-8'))
