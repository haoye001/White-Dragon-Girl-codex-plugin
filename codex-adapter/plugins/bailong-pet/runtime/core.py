"""Local configuration, bounded artwork loading and companion commands."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets' / 'animations'
VERSION = '1.1.0'
MAX_FRAMES = 240
MAX_PIXELS = 2048 * 2048


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


DATA = Path(os.environ.get('BAILONG_PLUGIN_DATA')
            or (read_json(ROOT / 'runtime-config.json', {}) or {}).get('dataDirectory')
            or os.environ.get('PLUGIN_DATA')
            or Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'BailongCodexPlugin')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def animation_catalog():
    manifest = read_json(ASSETS / '素材清单.json')
    if not isinstance(manifest, dict):
        raise ValueError('动画清单缺失或无效')
    items = [manifest.get('idle')]
    for key in ('additionalIdleAnimations', 'variants', 'workAnimations'):
        items.extend(manifest.get(key, []))
    items.extend(manifest.get(k) for k in ('dragAnimation', 'landingAnimation', 'quotaAnimation'))
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue  # Original manifest contains a null work animation.
        file = item.get('playbackFile') or item['file']
        path = (ASSETS / file).resolve()
        if not path.is_relative_to(ASSETS.resolve()) or path.suffix.lower() != '.webp':
            raise ValueError('素材路径必须是动画目录内的 WebP')
        if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('动画文件缺失或过大')
        result[item['id']] = {**item, 'path': path}
    return result


def validate_command(value, catalog):
    if not isinstance(value, dict):
        raise ValueError('命令必须是对象')
    action = value.get('action')
    allowed = {'state', 'stop', 'show', 'hide', 'say', 'play', 'usage', 'event', 'query_usage', 'settings'}
    if action not in allowed:
        raise ValueError('不支持的桌宠操作')
    if action == 'say':
        if not isinstance(value.get('message'), str) or not 1 <= len(value['message']) <= 1000:
            raise ValueError('气泡文字需要 1–1000 个字符')
        seconds = value.get('seconds', 8)
        if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not 1 <= seconds <= 60:
            raise ValueError('显示时长需要在 1–60 秒之间')
    if action == 'play' and value.get('animation') not in catalog:
        raise ValueError('未知动作；先查看 bailong_state 的 animations')
    if action == 'settings':
        settings = value.get('settings')
        if not isinstance(settings, dict) or not settings or set(settings)-{'auto_interact', 'auto_interval_seconds'}:
            raise ValueError('未知设置')
        if 'auto_interact' in settings and type(settings['auto_interact']) is not bool:
            raise ValueError('auto_interact 必须为布尔值')
        if 'auto_interval_seconds' in settings:
            seconds = settings['auto_interval_seconds']
            if type(seconds) not in (int, float) or not 10 <= seconds <= 600:
                raise ValueError('互动间隔需要在 10–600 秒之间')
    if action == 'event' and value.get('event') not in {
        'UserPromptSubmit', 'PreToolUse', 'Stop', 'Interrupt', 'SessionEnd', 'PermissionRequest'
    }:
        raise ValueError('未知会话事件')
    if action == 'usage':
        windows = value.get('windows')
        if not isinstance(windows, list) or not 1 <= len(windows) <= 8:
            raise ValueError('需要 1–8 个真实额度窗口')
        for window in windows:
            if not isinstance(window, dict) or not isinstance(window.get('label'), str) or not 1 <= len(window['label']) <= 50:
                raise ValueError('额度窗口名称无效')
            used = window.get('used_percent')
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
                raise ValueError('已用百分比需要在 0–100 之间')
            reset = window.get('resets_at')
            if reset is not None and (isinstance(reset, bool) or not isinstance(reset, (int, float)) or not 0 < reset < 10**11):
                raise ValueError('重置时间需要为 Unix 秒数或 null')
    return value
