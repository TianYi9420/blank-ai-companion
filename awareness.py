"""Opt-in foreground application label only. No window text or desktop pet.

No polling, import-time native calls, screenshots, idle input, GPU queries,
process enumeration, executable reads or subprocesses. Unknown names disappear.
"""
import ctypes
from ctypes import wintypes
import ntpath
import os

# Fixed labels only: never forward process names, paths or arbitrary aliases.
_APP_LABELS = {
    "code.exe": "代码编辑器", "workbuddy.exe": "AI工作助手",
    "chrome.exe": "浏览器", "msedge.exe": "浏览器", "firefox.exe": "浏览器",
    "discord.exe": "聊天应用", "steam.exe": "游戏平台", "steamwebhelper.exe": "游戏平台",
    "swordofjustice.exe": "游戏", "nshm.exe": "游戏",
    "explorer.exe": "文件管理器", "notepad.exe": "文本编辑器", "obsidian.exe": "笔记应用",
}
_LABELS = frozenset(_APP_LABELS.values())
_FIELDS = frozenset(("enabled", "share_app_label"))


def config_errors(cfg):
    if not isinstance(cfg, dict):
        return ["invalid_awareness_settings"]
    settings = cfg.get("awareness", {})
    if not isinstance(settings, dict) or set(settings) - _FIELDS:
        return ["invalid_awareness_settings"]
    if any(type(settings.get(key, False)) is not bool for key in _FIELDS):
        return ["invalid_awareness_settings"]
    if settings.get("enabled") is True and settings.get("share_app_label") is not True:
        return ["awareness_label_sharing_requires_opt_in"]
    return []


def permitted(cfg):
    return (not config_errors(cfg) and cfg.get("awareness", {}).get("enabled") is True
            and cfg["awareness"].get("share_app_label") is True)


def _foreground_process_name():
    """Read one foreground PID and its executable basename, no title APIs."""
    if os.name != "nt":
        return ""
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    hwnd = user.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    if not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
        return ""
    handle = kernel.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return ntpath.basename(buffer.value).casefold()
    finally:
        kernel.CloseHandle(handle)


def snapshot(cfg):
    """One gated sample; only a fixed label escapes, never native errors."""
    if not permitted(cfg):
        return {}
    try:
        name = _foreground_process_name()
        label = _APP_LABELS.get(name.casefold(), "") if isinstance(name, str) else ""
        return {"app_label": label} if label else {}
    except Exception:
        return {}


def describe(state):
    if not isinstance(state, dict) or set(state) != {"app_label"}:
        return ""
    label = state.get("app_label")
    if not isinstance(label, str) or label not in _LABELS:
        return ""
    return "本次采样的前景应用类别是" + label + "；这不证明正在操作、在线、心情或具体任务，不推断窗口内容。"
