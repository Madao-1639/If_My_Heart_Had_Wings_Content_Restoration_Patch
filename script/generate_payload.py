# -*- coding: utf-8 -*-
"""生成增量 payload（管线步 5）：`asset/` vs `backup/` → `payload/` + METADATA.json + 回读校验。

路径约定（照抄 Cross_Channel 方案）：
  asset/   = 交付文件（`build_patch.py` 只写有差异的归档，无差异者不在这里）
  backup/  = Steam 原始基线（差分依据，也是未交付归档在安装期的来源＝玩家原档）
  payload/ = 交给 `tool/install.py` 的增量包

按 `asset/` 的实际产物逐条分类，METADATA 的键就是交付路径（相对游戏根目录，正斜杠）：

- `copy` 整档覆盖：`OVERWRITE` 名单（`Rio.arc`、`zh-CN/Rio.arc`、`Script.arc`——体量小，
  构建已含玩家基线的全部成员），以及玩家目录原本不存在的新档（`PVOICE.arc` / `PCHIP.arc`）。
  补丁档与交付路径同名，安装时直接复制，重复安装天然幂等。
- `merge` 资源级合并：其余归档只出 `added` / `modified` 成员。成员表按 **asset 文件自身
  的成员顺序**写入（backup 独有成员追加为 `deleted`，安装器跳过它们）；安装器按
  (玩家原档 + 补丁档 + 元数据) 重组归档。按 asset 顺序而非「原档顺序 + 追加」排列，
  正是回放逐字节一致的关键（CC 教训：顺序错则内容全对、字节序不同，checksum 必失败）。
- `loose` 裸文件：`RIO/SL_*.ws2`（后日谈脚本，非归档），逐文件哈希校验。

补丁档定位口径由 `tool/install.py` 的 `payload_path_for()` 提供，打包与安装共用同一函数。

幂等：payload/ 每次清空重建。METADATA 只放可校验条目，不带 `_` 前缀元信息键。
"""
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, 'tool')
for _p in (ROOT, TOOL):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from tool import arcbuild                                    # noqa: E402
from tool.install import merge_arc, payload_path_for          # noqa: E402

ASSET_DIR = os.path.join(ROOT, 'asset')
BACKUP_DIR = os.path.join(ROOT, 'backup')
PAYLOAD_DIR = os.path.join(ROOT, 'payload')
VERIFY_TMP_DIR = os.path.join(ROOT, 'tmp', 'verify_merge')

# 整档覆盖的交付（相对 asset/ 的路径）；其余归档走资源级合并
OVERWRITE = ['Rio.arc', 'zh-CN/Rio.arc', 'Script.arc']
LOOSE_DIR = 'RIO'                 # 裸脚本目录（后日谈 SL_*.ws2）
LOOSE_KEY = 'RIO'                 # 其在 METADATA 中的键


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def asset_archives():
    """asset/ 内的归档相对路径（正斜杠）。"""
    out = []
    for dirpath, _dirs, files in os.walk(ASSET_DIR):
        for fn in files:
            if fn.lower().endswith('.arc'):
                out.append(os.path.relpath(os.path.join(dirpath, fn),
                                           ASSET_DIR).replace('\\', '/'))
    return sorted(out)


def check_asset_layout():
    """asset/ 只允许归档与 `RIO/` 裸文件；其他形态说明写盘器出了越界产物。"""
    stray = []
    for dirpath, _dirs, files in os.walk(ASSET_DIR):
        for fn in files:
            rel = os.path.relpath(os.path.join(dirpath, fn), ASSET_DIR).replace('\\', '/')
            if fn.lower().endswith('.arc') or rel.startswith(LOOSE_DIR + '/'):
                continue
            stray.append(rel)
    assert not stray, 'asset/ 出现未预期的产物 %r（只允许 *.arc 与 %s/ 裸文件）' % (stray[:5], LOOSE_DIR)


def build_archive_delta(asset_path, backup_path):
    """成员分类（added / modified / keep / deleted）+ 增量成员表，顺序按 asset 自身。"""
    asset_members = arcbuild.read_raw(asset_path)
    asset_map = {n.decode('utf-16le'): (n, d) for n, d in asset_members}
    asset_order = [n.decode('utf-16le') for n, _ in asset_members]

    backup_members = arcbuild.read_raw(backup_path) if os.path.exists(backup_path) else []
    backup_map = {n.decode('utf-16le'): d for n, d in backup_members}
    backup_order = [n.decode('utf-16le') for n, _ in backup_members]

    members_with_type, seen = [], set()
    for name in asset_order:                            # ← 按 asset 的实际顺序
        seen.add(name)
        if name not in backup_map:
            members_with_type.append({'name': name, 'type': 'added'})
        elif sha256(asset_map[name][1]) != sha256(backup_map[name]):
            members_with_type.append({'name': name, 'type': 'modified'})
        else:
            members_with_type.append({'name': name, 'type': 'keep'})
    for name in backup_order:
        if name not in seen:
            members_with_type.append({'name': name, 'type': 'deleted'})

    delta = [asset_map[m['name']] for m in members_with_type
             if m['type'] in ('added', 'modified')]
    stats = {t: sum(1 for m in members_with_type if m['type'] == t)
             for t in ('keep', 'added', 'modified', 'deleted')}
    return delta, members_with_type, stats


def generate():
    print('=' * 84)
    print('Payload 生成器（在这苍穹展翅 内容恢复补丁）')
    print('=' * 84)

    if not os.path.isdir(ASSET_DIR):
        print('错误: asset/ 不存在: %s' % ASSET_DIR)
        return None
    check_asset_layout()

    if os.path.exists(PAYLOAD_DIR):
        shutil.rmtree(PAYLOAD_DIR)
    os.makedirs(PAYLOAD_DIR, exist_ok=True)

    metadata = {}
    total_size = 0

    print('生成 payload:')
    print()

    for key in asset_archives():
        asset_path = os.path.join(ASSET_DIR, key)
        backup_path = os.path.join(BACKUP_DIR, key)
        checksum = sha256_file(asset_path)

        if key in OVERWRITE or not os.path.exists(backup_path):
            info = {'kind': 'copy', 'checksum': checksum}
            out_path = payload_path_for(PAYLOAD_DIR, key, info)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            shutil.copyfile(asset_path, out_path)
            size = os.path.getsize(out_path)
            total_size += size
            why = '名单指定' if key in OVERWRITE else 'backup 无此档（新档）'
            print('  [COPY] %s: %s bytes（整档覆盖，%s）' % (key, format(size, ','), why))
            metadata[key] = info
            continue

        delta, members_with_type, stats = build_archive_delta(asset_path, backup_path)
        if not delta:
            print('  [SKIP] %s: 与 backup 无成员差异（不交付）' % key)
            continue
        info = {'kind': 'merge', 'checksum': checksum, 'members': members_with_type}
        out_path = payload_path_for(PAYLOAD_DIR, key, info)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        arcbuild.write_arc(delta, out_path)
        size = os.path.getsize(out_path)
        total_size += size
        print('  [MERGE] %s: %s bytes (keep=%d added=%d modified=%d deleted=%d)'
              % (os.path.relpath(out_path, PAYLOAD_DIR).replace('\\', '/'),
                 format(size, ','), stats['keep'], stats['added'],
                 stats['modified'], stats['deleted']))
        metadata[key] = info

    # 裸文件（RIO/SL_*.ws2）
    loose_dir = os.path.join(ASSET_DIR, LOOSE_DIR)
    if os.path.isdir(loose_dir):
        files = {}
        for fn in sorted(os.listdir(loose_dir)):
            fp = os.path.join(loose_dir, fn)
            if os.path.isfile(fp):
                payload_fp = os.path.join(PAYLOAD_DIR, LOOSE_DIR, fn)
                os.makedirs(os.path.dirname(payload_fp), exist_ok=True)
                shutil.copyfile(fp, payload_fp)
                files['%s/%s' % (LOOSE_DIR, fn)] = sha256_file(fp)
                total_size += os.path.getsize(payload_fp)
        if files:
            metadata[LOOSE_KEY] = {'kind': 'loose', 'files': files}
            print('  [LOOSE] %s/: %d 个裸文件' % (LOOSE_DIR, len(files)))

    metadata_file = os.path.join(PAYLOAD_DIR, 'METADATA.json')
    with open(metadata_file, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print()
    print('=' * 84)
    print('交付条目: %d（copy=%d merge=%d loose=%d）'
          % (len(metadata),
             sum(1 for i in metadata.values() if i['kind'] == 'copy'),
             sum(1 for i in metadata.values() if i['kind'] == 'merge'),
             sum(1 for i in metadata.values() if i['kind'] == 'loose')))
    print('Payload 总大小: %s bytes (%.1f MB)' % (format(total_size, ','), total_size / 1024 / 1024))
    print('元数据: %s' % metadata_file)
    return metadata


def verify(metadata):
    """回读校验：backup + payload + METADATA 重放安装流程，结果必须与 asset 逐字节一致。"""
    print()
    print('=' * 84)
    print('回读校验（模拟安装流程）')
    print('=' * 84)

    if os.path.exists(VERIFY_TMP_DIR):
        shutil.rmtree(VERIFY_TMP_DIR)
    os.makedirs(VERIFY_TMP_DIR, exist_ok=True)

    metadata_path = os.path.join(PAYLOAD_DIR, 'METADATA.json')
    ok = True
    try:
        for key, info in metadata.items():
            src = payload_path_for(PAYLOAD_DIR, key, info)
            expected = info.get('checksum')
            if info['kind'] == 'loose':
                for rel, expect in sorted(info['files'].items()):
                    actual = sha256_file(os.path.join(PAYLOAD_DIR, rel))
                    state = actual == expect
                    print('  [%s] %s (loose)' % ('OK' if state else 'FAIL', rel))
                    ok = ok and state
                continue
            if info['kind'] == 'copy':
                actual = sha256_file(src)
                state = actual == expected
                print('  [%s] %s: 补丁档与 asset 同一份字节（整档覆盖）'
                      % ('OK' if state else 'FAIL', key))
                ok = ok and state
                continue
            out_path = os.path.join(VERIFY_TMP_DIR, key.replace('/', '_'))
            merge_arc(os.path.join(BACKUP_DIR, key), src, out_path, metadata_path, key)
            actual = sha256_file(out_path)
            if actual == expected:
                print('  [OK] %s: 重放与 asset 一致' % key)
            else:
                ok = False
                print('  [FAIL] %s: 重放不一致 期望=%s 实际=%s' % (key, expected, actual))
            if os.path.exists(out_path):
                os.remove(out_path)
    finally:
        shutil.rmtree(VERIFY_TMP_DIR, ignore_errors=True)

    print()
    print('[OK] 所有交付条目回读校验通过' if ok else '[FAIL] 回读校验失败')
    return ok


def main():
    metadata = generate()
    if metadata is None:
        return 1
    if not metadata:
        print('没有生成任何 payload，跳过校验')
        return 0
    if not verify(metadata):
        return 1
    print()
    print('下一步: bash script/pack.sh（PyInstaller 打包 tool/install.py，payload 随包嵌入）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
