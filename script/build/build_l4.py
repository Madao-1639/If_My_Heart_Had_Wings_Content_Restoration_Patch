"""L4 后日谈（After Story）还原构建器 —— 路线 A2 精简复刻。

从 backup/（Steam 基线，只读）与原版发行版起底构建 L4 交付：

  G1  Script.arc/LegacyGame.lua   解除 PatchFlag 硬置 false（0x234b0，4 B）
  G2  Script.arc/LegacyGame.lua   字符串常量 openSceneSelect → openAfter（0x2a18）
  G4  Rio.arc/start.ws2           SetFlag 1000 = 1（解码后偏移 5，00 → 01）
  G5  zh-CN/Rio.arc               追加 4 个 SL_*.lng：构建时从主产物
                                  resource/fan_cn/SL_*.json（idx → 中文）现做
                                  （XOR 0x88），不留档
  G10 zh-CN/Rio.arc               NameTable.txt 合并 L2 的
                                  resource/fan_cn/NameTable.json 补充条目
                                  （官方表只有英文键；还原脚本的日文名牌串
                                  %LC小鳥 等需补键，否则说话人名牌裸显日文；
                                  L4 侧不维护条目，只校验 SL_* 用到的 8 键）
  G6  Script.arc/ArcFileName.lua  注入 flag 126 归档路由分支（A2：不含 bgm 子块）
  G7  PVOICE.arc / PCHIP.arc      从原版整档复制（裸归档，放游戏根目录）
  G8  SE.arc                      追加 3 个 PSE 独有 SE（T_se91 / pw129_4 / se43b）
  G9  GRAPHIC.arc                 **不随 L4 交付**：33 张后日谈 PNA 分层立绘全部
                                  被原版主线脚本引用 ⇒ 由 L1–L3 的缺失资源工序
                                  并入 GRAPHIC.arc，L4 只按名端到端验收
                                  （`--verify <产物目录|GRAPHIC.arc>`）

G3（裸 RIO/SL_*.ws2 的 Steam 编码校验/转换）不在本脚本范围内，另行处理。
机制依据：doc/afterstory-mechanics.md §9。

G6 的注入原理（纯字节，无需 Lua 编译器）：
  1. 常量表追加在末尾 ⇒ 已有指令的 Bx/RK 索引不变；
  2. 插入块内部 JMP 全为块内相对跳转 ⇒ sBx 原样复制；
  3. 插入点前后无需要修正的跳转（全为 sBx=+2 局部短跳）；
  4. Steam 侧 lineinfo 已 strip（nli==0）⇒ 无需同步插入。
插入点：graphics = Steam main.1 pc 18（66 条）；sound = Steam main.3 pc 27（34 条，
A2 精简：截掉末尾 bgm→PBgm.arc 子块，只修块首 JMP 的 sBx 42→28）。

产出：默认写入 tmp/_l4/asset/（L4 独立测试层；与主线合并顺序由 L1–L3 线协调）。
幂等：每次从 backup/ 重新构建，输出确定 —— 跑两次逐字节一致（可复现性验收）。
"""
import argparse
import struct
import sys
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'script' / 'build'))

from tool import arcbuild, fancn, lng, scriptext, ws2  # noqa: E402
from build_nametable import build as build_nametable  # noqa: E402

STEAM_BACKUP = BASE / 'backup'
OUT_DIR = BASE / 'tmp' / '_l4' / 'asset'
FAN_TEXT_DIR = BASE / 'resource' / 'fan_cn'
# 原版发行目录不进版本库，路径由 --orig-dir 或环境变量 IFMH_ORIG_DIR 给出
# （口径同 tool/scriptext.py 与 doc/restoration-targets.md §素材来源）。

# 原版 PSE.arc 独有、Steam SE.arc 缺失的 3 个 SE（G8）
EXTRA_SE = ['T_se91.ogg', 'pw129_4.ogg', 'se43b.ogg']
# G5 的 FD 文本（主产物是 resource/fan_cn/<脚本>.json，.lng 构建时现做）
SL_SCRIPTS = ['SL_KOT_001', 'SL_AGE_001', 'SL_AMA_001', 'SL_HUT_001']
# G9 的验收名单：4 条 SL_* 引用、Steam GRAPHIC.arc 缺失的后日谈 PNA 分层立绘
# （5 位女主 × L/M/W 服装差分）。名字为 Shift-JIS 语义的 UTF-16LE 归档成员名。
# L4 不搬运这些文件（全部被原版主线脚本引用 ⇒ 本体线交付），只逐名断言产物含它，
# 并复核「原版有、Steam 基线无」，防止名单漂移。
SL_PNA = [
    'A小鳥_01L.pna', 'A小鳥_01M.pna', 'A小鳥_01W.pna',
    'A小鳥_02L.pna', 'A小鳥_02M.pna', 'A小鳥_02W.pna', 'A小鳥_03M.pna',
    'Bあげは_01L.pna', 'Bあげは_01M.pna', 'Bあげは_01W.pna',
    'Bあげは_02L.pna', 'Bあげは_02M.pna', 'Bあげは_03L.pna', 'Bあげは_03M.pna',
    'C天音_01L.pna', 'C天音_01M.pna', 'C天音_01W.pna',
    'C天音_02L.pna', 'C天音_02M.pna', 'C天音_02W.pna',
    'D亜紗_01L.pna', 'D亜紗_01M.pna', 'D亜紗_01W.pna',
    'D亜紗_02L.pna', 'D亜紗_02M.pna', 'D亜紗_02W.pna',
    'E夜瑠_01L.pna', 'E夜瑠_01M.pna', 'E夜瑠_01W.pna',
    'E夜瑠_02L.pna', 'E夜瑠_02M.pna', 'E夜瑠_02W.pna', 'E夜瑠_03M.pna',
]

# G10 校验名单：4 个 SL_*.ws2 实测引用的全部 %LC 日文名牌键（7 个与主线共用、
# 1 个后日谈专属）。条目本身来自 L2 的 resource/fan_cn/NameTable.json，L4 不再
# 自带名牌；这里逐一断言合并表含该键，防止上游产物漏名导致名牌裸显日文。
SL_NAME_KEYS = [
    '%LC小鳥', '%LCあげは', '%LC天音', '%LC亜紗', '%LC依瑠', '%LC碧',
    '%LC亜紗・依瑠', '%LC碧・小鳥・亜紗・依瑠',
]

# ---------------- Lua 5.1 undump 解析（带偏移记录，自原型移植） ----------------


class R:
    def __init__(self, b):
        self.b = b
        self.i = 0

    def u8(self):
        v = self.b[self.i]
        self.i += 1
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.b, self.i)[0]
        self.i += 4
        return v

    def num(self, sz):
        v = struct.unpack_from('<d' if sz == 8 else '<f', self.b, self.i)[0]
        self.i += sz
        return v

    def string(self, sz):
        st = self.i
        n = self.u32()
        if n == 0:
            return None, st, self.i
        s = self.b[self.i:self.i + n - 1]
        self.i += n
        return s, st, self.i


class P:
    pass


def parse_func(r, sz, nsz):
    p = P()
    p.src, _, _ = r.string(sz)
    p.line = r.u32()
    p.lastline = r.u32()
    p.nups = r.u8()
    p.nparams = r.u8()
    p.vararg = r.u8()
    p.maxstack = r.u8()
    n = r.u32()
    p.ncode = n
    p.code_off = r.i
    p.code = [r.u32() for _ in range(n)]
    p.code_end = r.i
    n = r.u32()
    p.nconst_off = r.i - 4
    p.nconst = n
    p.consts = []
    for _ in range(n):
        t = r.u8()
        if t == 0:
            p.consts.append(('nil', None))
        elif t == 1:
            p.consts.append(('bool', r.u8()))
        elif t == 3:
            p.consts.append(('num', r.num(nsz)))
        elif t == 4:
            p.consts.append(('str', r.string(sz)[0]))
        else:
            raise ValueError('bad const tag %d' % t)
    p.consts_end = r.i
    n = r.u32()
    p.nprotos = n
    p.protos = [parse_func(r, sz, nsz) for _ in range(n)]
    n = r.u32()
    p.nli_off = r.i - 4
    p.nli = n
    p.lineinfo_off = r.i
    p.lineinfo = [r.u32() for _ in range(n)]
    p.lineinfo_end = r.i
    n = r.u32()
    p.locvars = []
    for _ in range(n):
        s, _, _ = r.string(sz)
        a = r.u32()
        b = r.u32()
        p.locvars.append((s, a, b))
    p.locvars_end = r.i
    n = r.u32()
    p.upvals = [r.string(sz)[0] for _ in range(n)]
    p.upvals_end = r.i
    return p


def parse_lua(data):
    r = R(data)
    assert r.b[:4] == b'\x1bLua', 'not lua bytecode'
    r.i = 4
    hdr = dict(ver=r.u8(), fmt=r.u8(), endian=r.u8(), szint=r.u8(), size_t=r.u8(),
               szins=r.u8(), sznum=r.u8(), integral=r.u8())
    assert hdr['endian'] == 1
    main = parse_func(r, hdr['size_t'], hdr['sznum'])
    assert r.i == len(data), 'trailing bytes %d/%d' % (r.i, len(data))
    return main, hdr


def collect(p, acc, path='main'):
    acc.append((path, p))
    for i, sp in enumerate(p.protos):
        collect(sp, acc, '%s.%d' % (path, i))


def proto_by_path(acc, path):
    for p, x in acc:
        if p == path:
            return x
    raise KeyError(path)


# ---------------- 指令重映射（自原型移植） ----------------

OP_LOADK, OP_GETGLOBAL, OP_SETGLOBAL, OP_CLOSURE = 1, 5, 7, 36
RK_OPS = {6, 9, 11, 12, 13, 14, 15, 16, 17, 23, 24, 25}   # GETTABLE SETTABLE SELF arith EQ LT LE


def enc_abc(op, a, b, c):
    return (op & 0x3f) | ((a & 0xff) << 6) | ((c & 0x1ff) << 14) | ((b & 0x1ff) << 23)


def enc_abx(op, a, bx):
    return (op & 0x3f) | ((a & 0xff) << 6) | ((bx & 0x3ffff) << 14)


def enc_asbx(op, a, sbx):
    return enc_abx(op, a, sbx + 131071)


def enc_const(t):
    k, v = t
    if k == 'nil':
        return b'\x00'
    if k == 'bool':
        return b'\x01' + bytes([v])
    if k == 'num':
        return b'\x03' + struct.pack('<d', v)
    if k == 'str':
        if v is None:
            return b'\x04' + struct.pack('<I', 0)
        return b'\x04' + struct.pack('<I', len(v) + 1) + v + b'\x00'
    raise ValueError(k)


def cval(t):
    k, v = t
    if k == 'num':
        return ('num', round(v, 12))
    if k == 'str':
        return ('str', v)
    return (k, v)


def const_refs(w):
    op = w & 0x3f
    Bx = (w >> 14) & 0x3ffff
    B = (w >> 23) & 0x1ff
    C = (w >> 14) & 0x1ff
    if op in (OP_LOADK, OP_GETGLOBAL, OP_SETGLOBAL, OP_CLOSURE):
        return [Bx]
    if op in RK_OPS:
        return [x & 0xff for x in (B, C) if x & 0x100]
    return []


def remap(w, cmap):
    op = w & 0x3f
    A = (w >> 6) & 0xff
    C = (w >> 14) & 0x1ff
    B = (w >> 23) & 0x1ff
    Bx = (w >> 14) & 0x3ffff
    if op in (OP_LOADK, OP_GETGLOBAL, OP_SETGLOBAL, OP_CLOSURE):
        return enc_abx(op, A, cmap[Bx])
    if op in RK_OPS:
        def rk(x):
            return (0x100 | cmap[x & 0xff]) if (x & 0x100) else x
        return enc_abc(op, A, rk(B), rk(C))
    return w   # JMP / CALL / MOVE / RETURN 等原样复制（块内 sBx 与原版一致）


def inject_route_branches(arc_lua, orig_legacy):
    """把原版 LegacyGame.lua（main.41/main.42）的 flag 126 分支注入 Steam
    ArcFileName.lua 字节码，返回补丁后的字节串。"""
    omain, _ = parse_lua(orig_legacy)
    smain, _ = parse_lua(arc_lua)
    oacc, sacc = [], []
    collect(omain, oacc)
    collect(smain, sacc)
    o_g = proto_by_path(oacc, 'main.41')   # 原版 getGraphicsArcFileName
    o_s = proto_by_path(oacc, 'main.42')   # 原版 getSoundArcFileName
    s_g = proto_by_path(sacc, 'main.1')    # Steam getGraphicsArcFileName
    s_s = proto_by_path(sacc, 'main.3')    # Steam getSoundArcFileName

    def make_cmap(oblock, o_consts, s_consts):
        smap = {}
        for i, t in enumerate(s_consts):
            smap.setdefault(cval(t), i)
        cmap = {}
        refs = set()
        for w in oblock:
            refs.update(const_refs(w))
        for oi in sorted(refs):
            t = o_consts[oi]
            key = cval(t)
            if key in smap:
                cmap[oi] = smap[key]
            else:
                cmap[oi] = len(s_consts)
                smap[key] = len(s_consts)
                s_consts.append(t)
        return cmap

    def patch(proto, oblock, o_consts, ins_at):
        sc = list(proto.consts)
        cmap = make_cmap(oblock, o_consts, sc)
        newblk = [remap(w, cmap) for w in oblock]
        proto.code = proto.code[:ins_at] + newblk + proto.code[ins_at:]
        proto.ncode = len(proto.code)
        if proto.nli:
            fill = proto.lineinfo[ins_at - 1] if ins_at > 0 else 0
            proto.lineinfo = proto.lineinfo[:ins_at] + [fill] * len(newblk) + proto.lineinfo[ins_at:]
            proto.nli = len(proto.lineinfo)
        proto.consts = sc
        proto.nconst = len(sc)
        return cmap, len(newblk)

    # graphics：原版 main.41 pc75..140 共 66 条（flag 检查 + age/ama/hut/kot 4 条），插 pc18
    cm_g, nb_g = patch(s_g, o_g.code[75:141], o_g.consts, 18)

    # sound：原版 main.42 pc45..92 共 48 条 = 6 条 flag 检查 + char/bgv/bgm 各 14 条。
    # A2：截掉末尾 bgm→PBgm.arc 子块（PBGM 15 个与主线 BGM.arc md5 全同 ⇒ 等价），
    # 只修块首那条 JMP 的 sBx（42 → 34-5-1 = 28），插 pc27。
    sblk = list(o_s.code[45:93])
    assert len(sblk) == 48
    sblk = sblk[:34]
    w = sblk[5]
    op = w & 0x3f
    A = (w >> 6) & 0xff
    sblk[5] = enc_asbx(op, A, len(sblk) - 5 - 1)
    cm_s, nb_s = patch(s_s, sblk, o_s.consts, 27)
    assert 'PBgm.arc' not in [t[1] for t in s_s.consts if t[0] == 'str']
    assert b'PChip.arc' in b''.join(enc_const(t) for t in s_g.consts)
    assert b'PVoice.arc' in b''.join(enc_const(t) for t in s_s.consts)

    # 序列化：只重写被改动的 code / consts / lineinfo 区段
    edits = []
    for p in (s_g, s_s):
        edits.append((p.code_off - 4, p.code_end,
                      struct.pack('<I', p.ncode) + b''.join(struct.pack('<I', x) for x in p.code)))
        edits.append((p.nconst_off, p.consts_end,
                      struct.pack('<I', p.nconst) + b''.join(enc_const(t) for t in p.consts)))
        edits.append((p.nli_off, p.lineinfo_end,
                      struct.pack('<I', p.nli) + b''.join(struct.pack('<I', v) for v in p.lineinfo)))
    out = bytearray(arc_lua)
    for st, en, nb in sorted(edits, key=lambda e: -e[0]):
        out[st:en] = nb
    patched = bytes(out)
    # 回读校验：整体可完整解析
    parse_lua(patched)
    return patched, nb_g, nb_s


# ---------------- 各项改动 ----------------


def patch_legacy_game(data):
    """G1 + G2：LegacyGame.lua 就地字节改。"""
    # G1：main.133 pc 90 的 C 操作数 K27(false) → K36(true)，解除 PatchFlag 硬置 false
    assert data[0x234b0:0x234b4] == bytes.fromhex('49c0c68b'), data[0x234b0:0x234b4].hex()
    data = data[:0x234b0] + bytes.fromhex('4900c98b') + data[0x234b4:]
    # G2：全局名改名 openSceneSelect(16B 含 NUL) → openAfter(10B 含 NUL)，
    # 接上 mainmenu.ws2 的 ExecuteFunction "openAfter"。字符串自带长度前缀、
    # 跳转全为相对偏移 ⇒ 改长度无需修正任何偏移。
    old = b'\x04' + struct.pack('<I', 16) + b'openSceneSelect\x00'
    new = b'\x04' + struct.pack('<I', 10) + b'openAfter\x00'
    assert data.count(old) == 1, 'openSceneSelect 常量应全库唯一'
    data = data.replace(old, new)
    # 回读校验：整体可完整解析
    parse_lua(data)
    return data


def patch_start_ws2(data):
    """G4：start.ws2 的 SetFlag 1000 值 0 → 1（解码偏移 5）。"""
    d = bytearray(ws2.decode(data))
    assert d[:7] == bytes([0xfb, 0x01, 0x0b, 0xe8, 0x03, 0x00, 0x64]), d[:7].hex(' ')
    assert d[5] == 0
    d[5] = 1
    out = ws2.encode(bytes(d))
    assert len(out) == len(data)
    diff = [i for i in range(len(data)) if out[i] != data[i]]
    assert diff == [5], diff
    return out


def members_dict(members):
    return {nb.decode('utf-16-le'): d for nb, d in members}


def resolve_orig_dir(cli=None):
    """原版发行目录：--orig-dir 优先，否则取环境变量 IFMH_ORIG_DIR。"""
    d = Path(cli) if cli else scriptext.DEFAULT_ORIG_DIR
    if not d or not Path(d).is_dir():
        sys.exit('原版目录未提供或不存在：传 --orig-dir 或设环境变量 %s'
                 % scriptext.IFMH_ORIG_DIR)
    return Path(d)


def build(orig_dir):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ===== Script.arc：G1 + G2 + G6 =====
    script_members = arcbuild.read_raw(STEAM_BACKUP / 'Script.arc')
    names = [nb.decode('utf-16-le') for nb, _ in script_members]
    assert 'LegacyGame.lua' in names and 'ArcFileName.lua' in names, names
    orig_script = arcbuild.read_raw(orig_dir / 'Script.arc')
    orig_legacy = members_dict(orig_script)['LegacyGame.lua']
    sm = members_dict(script_members)
    legacy = patch_legacy_game(sm['LegacyGame.lua'])
    arcfile, nb_g, nb_s = inject_route_branches(sm['ArcFileName.lua'], orig_legacy)
    print('[G1+G2] LegacyGame.lua: %d -> %d B' % (len(sm['LegacyGame.lua']), len(legacy)))
    print('[G6]    ArcFileName.lua: %d -> %d B (graphics +%d 条 / sound +%d 条)'
          % (len(sm['ArcFileName.lua']), len(arcfile), nb_g, nb_s))
    out_members = []
    for nb, d in script_members:
        n = nb.decode('utf-16-le')
        if n == 'LegacyGame.lua':
            out_members.append((nb, legacy))
        elif n == 'ArcFileName.lua':
            out_members.append((nb, arcfile))
        else:
            out_members.append((nb, d))
    out_script = OUT_DIR / 'Script.arc'
    arcbuild.write_arc(out_members, out_script)
    arcbuild.verify(out_script, expect_count=len(out_members))
    # 零替换核查：除两个被改成员外逐一相同
    got = members_dict(arcbuild.read_raw(out_script))
    for n, d in sm.items():
        if n in ('LegacyGame.lua', 'ArcFileName.lua'):
            continue
        assert got[n] == d, 'member changed unexpectedly: %s' % n
    print('[G1+G2+G6] Script.arc -> %s (%d members)' % (out_script, len(out_members)))

    # ===== Rio.arc：G4 =====
    rio_members = arcbuild.read_raw(STEAM_BACKUP / 'Rio.arc')
    out_rio = []
    for nb, d in rio_members:
        if nb.decode('utf-16-le') == 'start.ws2':
            out_rio.append((nb, patch_start_ws2(d)))
        else:
            out_rio.append((nb, d))
    out_rioarc = OUT_DIR / 'Rio.arc'
    arcbuild.write_arc(out_rio, out_rioarc)
    arcbuild.verify(out_rioarc, expect_count=len(out_rio))
    got = members_dict(arcbuild.read_raw(out_rioarc))
    for nb, d in rio_members:
        n = nb.decode('utf-16-le')
        expect = patch_start_ws2(d) if n == 'start.ws2' else d
        assert got[n] == expect, 'member changed unexpectedly: %s' % n
    print('[G4] Rio.arc -> %s (%d members, start.ws2 flag 1000 = 1)' % (out_rioarc, len(out_rio)))

    # ===== zh-CN/Rio.arc：G5（按需生成 SL_*.lng）+ G10（NameTable 补日文名键） =====
    zh_members = arcbuild.read_raw(STEAM_BACKUP / 'zh-CN' / 'Rio.arc')
    zh_names = [nb.decode('utf-16-le') for nb, _ in zh_members]
    # G5 的文本源是 resource/fan_cn/<脚本>.json（idx → 中文，主产物）；
    # .lng 只是引擎装载形态，构建时按当前文本现做，不留档、也不读旧档。
    sl_blobs = []
    for s in SL_SCRIPTS:
        texts = fancn.load_texts(s, root=FAN_TEXT_DIR)
        blob = lng.encode_lng(texts, key=lng.KEY_STEAM_ZHCN)
        assert lng.parse_lng(blob, key=lng.KEY_STEAM_ZHCN) == texts, \
            '%s: lng round-trip mismatch' % s
        sl_blobs.append((s + '.lng', blob, len(texts)))
    add = []
    for name, blob, _size in sl_blobs:
        assert name not in zh_names, 'already present: %s' % name
        add.append((name.encode('utf-16-le'), blob))
    # G10：官方 NameTable 只覆盖英文键（Steam 底本 %LCKotori）；还原脚本的
    # 日文名牌串（%LC小鳥）查不到 ⇒ 名牌裸显日文。补充条目来自 L2 的
    # resource/fan_cn/NameTable.json（组合名中点在读取时归一为官方用字），
    # L4 侧只断言这张表覆盖 SL_* 用到的名牌键，然后整体替换该成员。
    nt_bytes, nt_official, nt_overrides = build_nametable()
    nt_map = dict(nt_overrides)
    for key in SL_NAME_KEYS:
        assert key in nt_map, 'FD nameplate key missing from NameTable: %s' % key
        assert nt_map[key].strip(), 'empty nameplate value: %s' % key
    zh_out = []
    for nb, d in zh_members:
        if nb.decode('utf-16-le') == 'NameTable.txt':
            zh_out.append((nb, nt_bytes))
        else:
            zh_out.append((nb, d))
    out_zh = OUT_DIR / 'zh-CN'
    out_zh.mkdir(exist_ok=True)
    out_zharc = out_zh / 'Rio.arc'
    arcbuild.write_arc(zh_out + add, out_zharc)
    arcbuild.verify(out_zharc, expect_count=len(zh_members) + len(add))
    got = members_dict(arcbuild.read_raw(out_zharc))
    for nb, d in zh_members:
        n = nb.decode('utf-16-le')
        expect = nt_bytes if n == 'NameTable.txt' else d
        assert got[n] == expect, 'member changed unexpectedly: %s' % n
    for name, blob, _size in sl_blobs:
        assert got[name] == blob, 'SL lng differs after arc round-trip: %s' % name
    print('[G5] zh-CN/Rio.arc -> %s (%d + %d members)'
          % (out_zharc, len(zh_members), len(add)))
    for name, blob, size in sl_blobs:
        print('       %s: %d slots, %d B' % (name, size, len(blob)))
    print('[G10] NameTable.txt: official %d + supplement %d entries '
          '(%d -> %d B), FD nameplate keys asserted: %d'
          % (len(nt_official), len(nt_overrides),
             len(members_dict(zh_members)['NameTable.txt']), len(nt_bytes),
             len(SL_NAME_KEYS)))

    # ===== SE.arc：G8 =====
    se_members = arcbuild.read_raw(STEAM_BACKUP / 'SE.arc')
    se_names = [nb.decode('utf-16-le') for nb, _ in se_members]
    pse = members_dict(arcbuild.read_raw(orig_dir / 'PSE.arc'))
    add = []
    for n in EXTRA_SE:
        assert n not in se_names, 'Steam SE.arc already has: %s' % n
        assert n in pse, 'missing in original PSE.arc: %s' % n
        add.append((n.encode('utf-16-le'), pse[n]))
    out_searc = OUT_DIR / 'SE.arc'
    arcbuild.write_arc(list(se_members) + add, out_searc)
    arcbuild.verify(out_searc, expect_count=len(se_members) + len(add))
    got = members_dict(arcbuild.read_raw(out_searc))
    for nb, d in se_members:
        n = nb.decode('utf-16-le')
        assert got[n] == d, 'member changed unexpectedly: %s' % n
    for n in EXTRA_SE:
        assert got[n] == pse[n]
    print('[G8] SE.arc -> %s (%d + %d members)' % (out_searc, len(se_members), len(add)))

    # G9（33 张后日谈分层立绘）不在此搬运：全部被原版主线脚本引用，由 L1–L3
    # 的缺失资源工序并入 GRAPHIC.arc，L4 侧只做端到端验收（见 verify_g9）。

    # ===== G7：PVOICE.arc / PCHIP.arc 整档复制 =====
    for n in ('PVOICE.arc', 'PCHIP.arc'):
        src = orig_dir / n
        dst = OUT_DIR / n
        shutil.copyfile(src, dst)
        arcbuild.verify(dst)
        print('[G7] %s -> %s (%.1f MB)' % (n, dst, dst.stat().st_size / 1048576))

    print('\nL4 构建完成 -> %s' % OUT_DIR)


def verify_g9(target, orig_dir):
    """G9 的端到端验收：产物 GRAPHIC.arc 含 `SL_PNA` 全部 33 名。

    L4 不再搬运这些立绘，因此验收对象是最终产物（主线 `asset/` 或游戏目录），
    不是 L4 的输出树。同时复核名单未漂移（原版有、Steam 基线无）。
    """
    path = Path(target)
    arc = path if path.suffix.lower() == '.arc' else path / 'GRAPHIC.arc'
    assert arc.is_file(), 'GRAPHIC.arc 不存在: %s' % arc
    prod = {nb.decode('utf-16-le').lower() for nb, _ in arcbuild.read_raw(arc)}
    missing = [n for n in SL_PNA if n.lower() not in prod]
    assert not missing, '产物缺 %d/%d 张后日谈立绘: %s' % (
        len(missing), len(SL_PNA),
        ' / '.join(n.encode('unicode_escape').decode() for n in missing))
    steam = {nb.decode('utf-16-le').lower()
             for nb, _ in arcbuild.read_raw(STEAM_BACKUP / 'GRAPHIC.arc')}
    orig = {nb.decode('utf-16-le').lower()
            for nb, _ in arcbuild.read_raw(orig_dir / 'GRAPHIC.arc')}
    for n in SL_PNA:
        assert n.lower() in orig, '名单漂移：原版 GRAPHIC.arc 无 %s' % n
        assert n.lower() not in steam, '名单漂移：Steam 基线已有 %s' % n
    print('[G9] %s: 后日谈立绘 %d/%d 在位，名单未漂移'
          % (arc, len(SL_PNA), len(SL_PNA)))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='L4 后日谈构建 / 端到端验收')
    ap.add_argument('--orig-dir',
                    help='原版发行目录（含 Script.arc/PSE.arc/PVOICE.arc/PCHIP.arc），'
                         '缺省取环境变量 IFMH_ORIG_DIR')
    ap.add_argument('--verify', metavar='产物目录|GRAPHIC.arc',
                    help='不构建，只断言产物 GRAPHIC.arc 含 33 张后日谈立绘')
    a = ap.parse_args()
    orig_dir = resolve_orig_dir(a.orig_dir)
    if a.verify:
        verify_g9(a.verify, orig_dir)
    else:
        build(orig_dir)
