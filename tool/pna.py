"""PNAP (.pna) 图层容器读写。

结构（均为小端）：
  头部：magic b'PNAP', unknown(i32)=44*layer_count+12, canvas_w(i32), canvas_h(i32), layer_count(i32)
  layer_count 个条目，每个 10 x i32：
    [0] u0        -- 真实图层为 0；分组哨兵标记为其他值（尚未逐一确认语义，见 doc/pna-resources.md）
    [1] layer_id  -- 位置量，用于 0x33/0x34 类显示指令引用；等于 layer_count-1-index
                      （已对 SysGraphic.arc 全部 28 个 pna 与角色立绘 pna 验证 unknown 字段公式，
                      并对 A小鳥_01L.pna 验证 layer_id 随索引递减）
    [2] box_x, [3] box_y, [4] box_w, [5] box_h  -- 图层在画布中的位置与尺寸
    [6] reserved  -- 已观察样本中恒为 0
    [7],[8]       -- IEEE754 double 1.0 标记（低/高 i32）
    [9] size      -- 该图层内嵌 PNG 的字节长度
  图层 PNG 数据紧跟条目表之后，按表内顺序排列。

layer_id 是纯位置量而非稳定身份标识——如果两个版本的同名 PNA 文件图层数量/顺序
不同，直接替换整份文件会导致引用错位。替换前应先解析并比对图层结构。
"""
import struct

HEADER = struct.Struct('<4siiii')
ENTRY = struct.Struct('<iiiiiiiiii')


def load(data):
    magic, unknown, canvas_w, canvas_h, layer_count = HEADER.unpack_from(data, 0)
    if magic != b'PNAP':
        raise ValueError('not a PNAP file (magic=%r)' % magic)
    off = HEADER.size
    entries = []
    for _ in range(layer_count):
        entries.append(list(ENTRY.unpack_from(data, off)))
        off += ENTRY.size
    images = []
    for e in entries:
        size = e[9]
        if size > 0:
            images.append(data[off:off + size])
            off += size
        else:
            images.append(None)
    if off != len(data):
        raise ValueError('trailing %d bytes after last layer image' % (len(data) - off))
    return {
        'unknown': unknown,
        'canvas_w': canvas_w,
        'canvas_h': canvas_h,
        'layer_count': layer_count,
        'entries': entries,
        'images': images,
    }


def dump(p):
    out = bytearray()
    out += HEADER.pack(b'PNAP', p['unknown'], p['canvas_w'], p['canvas_h'], p['layer_count'])
    for e in p['entries']:
        out += ENTRY.pack(*e)
    for img in p['images']:
        if img is not None:
            out += img
    return bytes(out)


def find_by_layer_id(p, layer_id):
    """返回 layer_id 匹配且含图像数据的表索引。"""
    matches = [i for i, e in enumerate(p['entries'])
               if e[1] == layer_id and p['images'][i] is not None]
    if not matches:
        raise ValueError('layer_id %d not found (or has no image)' % layer_id)
    if len(matches) > 1:
        raise ValueError('layer_id %d is ambiguous: table indices %r' % (layer_id, matches))
    return matches[0]


def get_box(p, idx):
    return tuple(p['entries'][idx][2:6])


def replace_layer(p, layer_id, png_bytes, box):
    """就地覆盖 layer_id 对应图层的图像数据与放置框。"""
    idx = find_by_layer_id(p, layer_id)
    e = p['entries'][idx]
    e[2], e[3], e[4], e[5] = box
    e[9] = len(png_bytes)
    p['images'][idx] = png_bytes
