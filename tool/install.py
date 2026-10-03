"""
《在这苍穹展翅》Steam 版内容恢复补丁安装器
If My Heart Had Wings Steam Edition - Content Restoration Patch Installer

安装说明：
1. 运行安装器，自动检测游戏路径
2. 或手动选择游戏根目录（包含 AdvHD.exe）
3. 确认安装

Installation:
1. Run the installer to auto-detect game path
2. Or manually select the game root directory (contains AdvHD.exe)
3. Confirm installation

交付条目形态（`payload/METADATA.json`，键 = 相对游戏根目录的交付路径，一律正斜杠）：
- merge：资源级合并。补丁档 = 交付名 + `_patch.arc`，按 `members` 记录的 **asset 成员
  顺序**重组「玩家原档 + 补丁档」⇒ 与 asset 逐字节一致。
- copy：整档覆盖。补丁档与交付路径同名（含玩家目录原本不存在的新档）。
- loose：裸文件目录（键 `RIO`），`files` = {相对路径: sha256}，逐个复制。

除键 `RIO` 外，每个键都当游戏根目录下的一个文件处理，所以 METADATA 只放可校验的交付
条目；非交付元信息（指纹、出处等）会让校验环节报「文件不存在」。
"""

import sys
import shutil
import json
import hashlib
from pathlib import Path
import arcbuild

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def get_version():
    packed = Path(__file__).parent / 'VERSION'
    if packed.exists():
        return packed.read_text(encoding='utf-8').strip()
    dev = Path(__file__).parent.parent / 'VERSION'
    if dev.exists():
        return dev.read_text(encoding='utf-8').strip()
    return 'dev'


CURRENT_VERSION = get_version()
TARGET_APPID = '326480'
GAME_FOLDER_NAME = 'If My Heart Had Wings'
GAME_EXE = 'AdvHD.exe'

# 待处理清单的显示名（未列出的键按形态名显示）
LABELS = {
    'Rio.arc': '脚本还原+中文文本',
    'zh-CN/Rio.arc': '中文覆盖层(.lng+名牌表)',
    'Script.arc': '引擎 lua(门控与归档路由)',
    'GRAPHIC.arc': '分层立绘/图形',
    'SE.arc': '音效',
    'VOICE.arc': '语音',
    'CHIP2.arc': 'CG/立绘块',
    'CHIP3.arc': 'CG/立绘块',
    'CHIP4.arc': 'CG/立绘块',
    'CHIP5.arc': 'CG/立绘块',
    'CHIP6.arc': 'CG/立绘块',
    'PVOICE.arc': '后日谈语音(新增整档)',
    'PCHIP.arc': '后日谈图形(新增整档)',
}
KIND_LABELS = {'copy': '整档覆盖', 'merge': '资源级合并', 'loose': '裸文件'}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def entry_kind(info):
    return info.get('kind', 'merge')


def payload_path_for(payload_dir, key, info):
    """METADATA 键 → payload 内的补丁文件路径（与打包侧同一口径）。"""
    payload_dir = Path(payload_dir)
    if entry_kind(info) == 'merge':
        return payload_dir / (key[:-4] + '_patch.arc')
    return payload_dir / key


def parse_vdf(vdf_path):
    """
    解析 Steam libraryfolders.vdf 文件
    VDF 格式类似 JSON，使用递归下降解析

    Returns:
        list: [(library_path, {appid: size, ...}), ...]
    """
    try:
        with open(vdf_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return []

    def tokenize(text):
        tokens = []
        i = 0
        while i < len(text):
            if text[i].isspace():
                i += 1
                continue
            if text[i] == '"':
                i += 1
                start = i
                while i < len(text) and text[i] != '"':
                    if text[i] == '\\' and i + 1 < len(text):
                        i += 2
                    else:
                        i += 1
                tokens.append(('STRING', text[start:i]))
                i += 1
            elif text[i] == '{':
                tokens.append(('LBRACE', '{'))
                i += 1
            elif text[i] == '}':
                tokens.append(('RBRACE', '}'))
                i += 1
            elif text[i:i + 2] == '//':
                while i < len(text) and text[i] != '\n':
                    i += 1
            else:
                i += 1
        return tokens

    def parse_dict(tokens, pos):
        result = {}
        while pos < len(tokens):
            token_type, token_value = tokens[pos]

            if token_type == 'RBRACE':
                return result, pos + 1
            elif token_type == 'STRING':
                key = token_value
                pos += 1

                if pos >= len(tokens):
                    break

                next_type, next_value = tokens[pos]

                if next_type == 'LBRACE':
                    pos += 1
                    value, pos = parse_dict(tokens, pos)
                    result[key] = value
                elif next_type == 'STRING':
                    result[key] = next_value
                    pos += 1
                else:
                    pos += 1
            else:
                pos += 1

        return result, pos

    tokens = tokenize(content)
    data, _ = parse_dict(tokens, 0)

    libraries = []
    if 'libraryfolders' not in data:
        return []

    libraryfolders = data['libraryfolders']
    for key, value in libraryfolders.items():
        if not isinstance(value, dict):
            continue
        if 'path' not in value or 'apps' not in value:
            continue

        library_path = value['path'].replace('\\\\', '\\')
        apps = value['apps'] if isinstance(value['apps'], dict) else {}
        libraries.append((library_path, apps))

    return libraries


def find_steam_game_path():
    """
    自动检测 Steam 游戏路径（仅 Windows）

    Returns:
        Path or None: 游戏路径，如果找不到则返回 None
    """
    if sys.platform != 'win32':
        return None

    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)

        steam_path = Path(steam_path)
        libraryfolders_vdf = steam_path / "steamapps" / "libraryfolders.vdf"

        if not libraryfolders_vdf.exists():
            return None

        libraries = parse_vdf(libraryfolders_vdf)

        for library_path, apps in libraries:
            if TARGET_APPID in apps:
                game_path = Path(library_path) / "steamapps" / "common" / GAME_FOLDER_NAME
                if (game_path / GAME_EXE).exists():
                    return game_path

        return None

    except Exception as e:
        print(f"自动检测失败: {e}")
        return None


def merge_arc(game_arc_path, patch_arc_path, output_path, metadata_path=None, asset_name=None):
    """
    合并游戏原有的 arc 文件和补丁 arc 文件（资源级替换，按元数据指定的顺序）

    Args:
        game_arc_path: 游戏原有的 arc 文件路径
        patch_arc_path: 补丁 arc 文件路径
        output_path: 输出文件路径
        metadata_path: 元数据文件路径（JSON，包含成员顺序和变化信息）
        asset_name: asset 文件名（如 'CHIP2.arc'，用于查找元数据中对应的条目）
    """
    # 玩家原档不存在（补丁新增的整档）按空表处理
    if Path(game_arc_path).exists():
        game_members = {nb.decode('utf-16le'): (nb, d)
                        for nb, d in arcbuild.read_raw(str(game_arc_path))}
    else:
        game_members = {}

    patch_members = {nb.decode('utf-16le'): (nb, d)
                     for nb, d in arcbuild.read_raw(str(patch_arc_path))}

    metadata = {}
    if metadata_path and Path(metadata_path).exists() and asset_name:
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                all_metadata = json.load(f)
            metadata = all_metadata.get(asset_name, {})
        except Exception as e:
            print(f"    警告：无法读取元数据 {metadata_path}: {e}")

    merged = []
    target_members = metadata.get('members', [])
    deleted_count = sum(1 for m in target_members if isinstance(m, dict) and m.get('type') == 'deleted')

    if target_members:
        # 按元数据中的目标顺序重组
        # target_members 中的每个元素是 {"name": "...", "type": "keep|added|modified|deleted"}
        missing_members = []
        for member_info in target_members:
            if isinstance(member_info, dict):
                name = member_info.get('name')
                member_type = member_info.get('type', 'keep')
            else:
                # 兼容旧格式（直接是字符串）
                name = member_info
                member_type = 'keep'

            if not name:
                continue

            if member_type == 'deleted':
                # 已删除：不写入输出
                continue

            if member_type in ('added', 'modified'):
                # 新增或修改：优先用补丁版本，找不到则降级用原版
                if name in patch_members:
                    merged.append(patch_members[name])
                elif name in game_members:
                    merged.append(game_members[name])
                    missing_members.append((name, member_type, 'patch'))
                else:
                    missing_members.append((name, member_type, 'both'))
            else:  # 'keep'
                # 保持原版：优先用原版，找不到则用补丁版本
                if name in game_members:
                    merged.append(game_members[name])
                elif name in patch_members:
                    merged.append(patch_members[name])
                    missing_members.append((name, member_type, 'game'))
                else:
                    missing_members.append((name, member_type, 'both'))

        if missing_members:
            print(f"    警告：{len(missing_members)} 个成员未能在预期位置找到")
            for name, mtype, missing_from in missing_members:
                print(f"      - {name} (type={mtype}): {missing_from} 中不存在")
    else:
        # 降级方案：如果没有元数据，按游戏原顺序处理
        for name, (name_bytes, data) in game_members.items():
            if name in patch_members:
                merged.append(patch_members[name])
            else:
                merged.append((name_bytes, data))

        for name, (name_bytes, data) in patch_members.items():
            if name not in game_members:
                merged.append((name_bytes, data))

    arcbuild.write_arc(merged, str(output_path))

    return len(game_members), len(patch_members), deleted_count, len(merged)


def select_game_directory():
    """
    选择游戏目录

    Returns:
        Path or None: 游戏路径
    """
    print("=" * 60)
    print(f"《在这苍穹展翅》内容恢复补丁 {CURRENT_VERSION}")
    print("If My Heart Had Wings - Content Restoration Patch")
    print("=" * 60)
    print()

    print("正在检测游戏路径...")
    print("Detecting game path...")
    print()

    auto_path = find_steam_game_path()

    if auto_path:
        print(f"检测到游戏路径：")
        print(f"  {auto_path}")
        print()
        use_auto = input("使用此路径? (Y/n): ").strip().lower()
        if use_auto not in ['n', 'no']:
            return auto_path
        print()
    else:
        print("未能自动检测到游戏路径")
        print()

    print(f"请输入游戏根目录路径（包含 {GAME_EXE} 的目录）：")
    print(f"Please enter the game root directory path (contains {GAME_EXE}):")
    print()
    print("提示：")
    print(r"  1. 直接输入路径（如 E:\SteamLibrary\steamapps\common\If My Heart Had Wings）")
    print("  2. 输入 '.' 使用安装器所在目录")
    print("  3. 留空取消安装")
    print()

    user_input = input("路径 / Path: ").strip()

    if not user_input:
        return None

    if user_input == '.':
        return Path.cwd()

    user_input = user_input.strip('"').strip("'")

    game_path = Path(user_input)

    if not game_path.exists():
        print(f"错误：路径不存在 / Path does not exist: {game_path}")
        return None

    if not (game_path / GAME_EXE).exists():
        print(f"错误：该目录下未找到 {GAME_EXE}")
        print(f"Error: {GAME_EXE} not found in this directory")
        return None

    return game_path


def build_files_to_process(metadata, payload_dir, game_path):
    """METADATA → 待处理清单（name / game_path / patch_path / output_path / kind）。

    交付面由打包侧决定，不在此写死归档名单；loose 条目展开为逐文件。
    """
    files_to_process = []
    for key, info in metadata.items():
        kind = entry_kind(info)
        if kind == 'loose':
            for rel in sorted(info['files']):
                files_to_process.append({
                    "name": f"{rel} (裸文件)",
                    "kind": kind,
                    "asset_name": key,
                    "game_path": game_path / rel,
                    "patch_path": payload_dir / rel,
                    "output_path": game_path / rel,
                })
            continue
        files_to_process.append({
            "name": f"{key} ({LABELS.get(key, KIND_LABELS.get(kind, kind))})",
            "kind": kind,
            "asset_name": key,
            "game_path": game_path / key,
            "patch_path": payload_path_for(payload_dir, key, info),
            "output_path": game_path / key,
        })
    return files_to_process


def install():
    """执行安装"""

    game_path = select_game_directory()

    if not game_path:
        print("安装已取消")
        print("Installation cancelled")
        return False

    print()
    print("=" * 60)
    print(f"游戏目录: {game_path}")
    print("=" * 60)
    print()

    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).parent.parent
    payload_dir = base_dir / "payload"

    if not payload_dir.exists():
        print(f"错误：找不到 payload 目录")
        print(f"Error: payload directory not found")
        print(f"预期位置：{payload_dir}")
        return False

    metadata_path = payload_dir / "METADATA.json"
    if not metadata_path.exists():
        print(f"错误：找不到元数据文件")
        print(f"Error: METADATA.json not found")
        print(f"预期位置：{metadata_path}")
        return False

    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    print("检测到补丁文件")
    print()

    files_to_process = build_files_to_process(metadata, payload_dir, game_path)

    print("检查补丁文件...")
    for file_info in files_to_process:
        if not file_info["patch_path"].exists():
            print(f"错误：缺失补丁文件 {file_info['patch_path']}")
            print(f"Error: Missing patch file {file_info['patch_path']}")
            return False

        # 资源级合并要在玩家原档上重组，原档必须在位；
        # 整档覆盖（Rio.arc / zh-CN/Rio.arc / Script.arc）与新增档（PVOICE / PCHIP）不要求
        if file_info["kind"] == "merge" and not file_info["game_path"].exists():
            print(f"错误：游戏文件不存在 {file_info['game_path']}")
            print(f"Error: Game file not found {file_info['game_path']}")
            return False

    print("所有文件检查通过")
    print()

    print("即将安装内容恢复补丁，这将修改以下文件：")
    print("About to install the content restoration patch. The following files will be modified:")
    for file_info in files_to_process:
        print(f"  - {file_info['name']}")
    print()
    print("建议：安装前通过 Steam 验证游戏完整性以创建备份")
    print("Recommendation: Verify game integrity via Steam before installation to create a backup")
    print()

    confirm = input("确认安装? (Y/n): ").strip().lower()
    if confirm in ['n', 'no']:
        print("安装已取消")
        print("Installation cancelled")
        return False

    print()
    print("开始安装...")
    print()

    try:
        for file_info in files_to_process:
            print(f"处理 {file_info['name']}...")

            if file_info["kind"] == "merge":
                game_count, patch_count, deleted_count, merged_count = merge_arc(
                    file_info["game_path"],
                    file_info["patch_path"],
                    file_info["output_path"],
                    metadata_path,
                    file_info["asset_name"]
                )
                print(f"  原文件成员: {game_count}")
                print(f"  补丁成员: {patch_count}")
                print(f"  删除成员: {deleted_count}")
                print(f"  合并后成员: {merged_count}")
            else:
                file_info["output_path"].parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file_info["patch_path"], file_info["output_path"])
                print(f"  已覆盖: {file_info['output_path'].relative_to(game_path)}")

            print(f"{file_info['name']} 完成")
            print()

        print("验证安装文件...")

        all_verified = True
        for asset_name, asset_info in metadata.items():
            if entry_kind(asset_info) == 'loose':
                for rel, expected_hash in sorted(asset_info['files'].items()):
                    installed_path = game_path / rel
                    if not installed_path.exists():
                        print(f"  [FAIL] {rel}: 文件不存在")
                        all_verified = False
                        continue
                    file_hash = file_sha256(installed_path)
                    if file_hash == expected_hash:
                        print(f"  [OK] {rel}")
                    else:
                        print(f"  [FAIL] {rel}: 哈希不匹配")
                        print(f"    预期: {expected_hash}")
                        print(f"    实际: {file_hash}")
                        all_verified = False
                continue

            expected_hash = asset_info.get('checksum')
            installed_path = game_path / asset_name

            if not installed_path.exists():
                print(f"  [FAIL] {asset_name}: 文件不存在")
                all_verified = False
                continue

            file_hash = file_sha256(installed_path)
            if file_hash == expected_hash:
                print(f"  [OK] {asset_name}")
            else:
                print(f"  [FAIL] {asset_name}: 哈希不匹配")
                print(f"    预期: {expected_hash}")
                print(f"    实际: {file_hash}")
                all_verified = False

        if not all_verified:
            print()
            print("=" * 60)
            print("验证失败：部分文件不正确")
            print("Verification failed: some files are incorrect")
            print("=" * 60)
            print()
            print("请按以下步骤恢复后重新安装：")
            print("Please follow these steps to recover and reinstall:")
            print()
            print("1. 打开 Steam，找到《在这苍穹展翅》(If My Heart Had Wings)")
            print("   Open Steam and find 'If My Heart Had Wings'")
            print()
            print("2. 右键点击游戏 -> 属性 -> 已安装文件 -> 校验游戏文件完整性")
            print("   Right-click game -> Properties -> Installed Files -> Verify integrity")
            print()
            print("3. 等待 Steam 完成验证和修复")
            print("   Wait for Steam to complete verification")
            print()
            print("4. 重新运行本安装程序")
            print("   Run this installer again")
            return False

        print()
        print("=" * 60)
        print("安装完成！")
        print("Installation completed!")
        print("=" * 60)
        print()
        print("现在可以启动游戏体验还原内容")
        print("You can now launch the game to experience the restored content")
        print()

        return True

    except Exception as e:
        print()
        print("=" * 60)
        print(f"安装失败：{e}")
        print(f"Installation failed: {e}")
        print("=" * 60)
        print()
        print("请通过 Steam 验证游戏完整性恢复原始文件")
        print("Please verify game integrity via Steam to restore original files")
        return False


if __name__ == "__main__":
    try:
        success = install()
        input("\n按任意键退出...")
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n安装已取消")
        print("Installation cancelled")
        input("\n按任意键退出...")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n未预期的错误：{e}")
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        input("\n按任意键退出...")
        sys.exit(1)
