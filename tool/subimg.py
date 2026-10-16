# -*- coding: utf-8 -*-
"""PNA 子图表：从 `.pna` 成员解出「每个图层的子图指纹」，供演出同步的**子图级**判据使用。

为什么要子图层粒度
------------------
Steam 不只换过立绘成员，还把**差分（表情）层的编排**改过：同一条显示指令里
`0x39`（建层）列的**图层 id 列表**不同（实测 AGE_010 p560 列 `{46,29}`、原版 o560 列
`{50,39}`），且 Steam 的 PNA 把部分差分槽位填成了**重复图**。⇒ 引擎按**脚本给的 id**
读图，所以「只把成员字节换成原版」会拼出**错配组合**（实机验证：换了字节画面依旧不对）。

判据只比**被脚本引用的子图**（不看未调用的部分）：
- 逐位比「当前加载的 PNA 在该 id 的子图」与「原版对应子图」：**字节级相同**或**像素相同**
  （＝仅重编码噪声）⇒ 这一位不动；
- 不同 ⇒ 若原版那张在当前 PNA 里另有相同子图，也只是**脚本 id 要改**；否则＝**原版独有**，
  该槽须整段换成原版行（顺带把被引用的原版成员补入交付）。
本模块只负责把 PNA 解成指纹表；比较逻辑在 `tool/perfsync.py`，与判定表生成器/闸共用。
"""
import hashlib
import os
import struct
import zlib

from tool import pna

__all__ = ['subimage_table', 'ARCHIVES', 'index_pna', 'resolve']

# 立绘（.pna）分布在这几个归档里（两版相同）
ARCHIVES = ('GRAPHIC.arc', 'CHIP2.arc', 'CHIP3.arc', 'CHIP4.arc', 'CHIP5.arc',
            'CHIP6.arc', 'Chip1.arc')


def index_pna(root, archives=ARCHIVES, cache={}):
    """把某侧（Steam 基线 / 原版 / 产物）所有 `.pna` 成员读成一个 {小写名: 字节} 表（带缓存）。"""
    key = (os.path.abspath(root), tuple(archives))
    if key in cache:
        return cache[key]
    from tool import arcbuild
    out = {}
    for a in archives:
        p = os.path.join(root, a)
        if not os.path.exists(p):
            continue
        for nb, d in arcbuild.read_raw(p):
            n = nb.decode('utf-16le', 'replace')
            if n.lower().endswith('.pna'):
                out.setdefault(n.lower(), d)
    cache[key] = out
    return out


def resolve(steam_index, orig_index, name):
    """**当前加载的那个 PNA**：Steam 归档里有这个名就用 Steam 的，否则用原版的。

    产物也是这个规则（Steam 缺的成员由 `resources.copy` 从原版补入）。
    """
    low = (name or '').lower()
    if low in steam_index:
        return steam_index[low]
    return orig_index.get(low)


def subimage_table(blob):
    """→ {条目表下标: (成员内嵌图片的 sha256, 解压后像素的 sha256)}。

    **键＝条目表下标（表内位置），不是 `entry[1]`（`layer_id`）**：引擎反汇编实证
    `0x39` 里那串 u16 是「位置量」，引擎直接 `layers[u16]` 取图（`entry[1]` 只用于判空槽，
    `entry[0]` 只作分组哨兵）——见 tmp/todoB2_model.md §0／§3（pefile+capstone 复算）。
    先前按 `entry[1]` 建键是**镜像键**：会把差异对到镜像位置（往往恰好相同）而静默放过
    （实测 73 条对齐判定被放过）。

    - 图片字节 sha：判「字节级相同」；
    - 像素 sha：判「仅重编码噪声」（PNA 会被重编码，字节必然不同，比字节无意义）。
    """
    out = {}
    if not blob:
        return out
    try:
        p = pna.load(blob)
    except Exception:
        return out
    for idx, (e, im) in enumerate(zip(p['entries'], p['images'])):
        if not im:
            continue
        pix = b'ERR'
        try:
            idat = b''
            off = 8
            while off < len(im):
                ln = struct.unpack('>I', im[off:off + 4])[0]
                typ = im[off + 4:off + 8]
                if typ == b'IDAT':
                    idat += im[off + 8:off + 8 + ln]
                off += 12 + ln
            pix = hashlib.sha256(zlib.decompress(idat)).digest()
        except Exception:
            pass
        out[idx] = (hashlib.sha256(im).digest(), pix)
    return out
