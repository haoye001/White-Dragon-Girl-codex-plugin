# GPT 白龙桌宠合集

本仓库提供 Android 独立桌宠和 Windows Codex 桌宠插件。

## Android 版

支持 Android 9 及以上。下载并安装白龙娘桌宠，打开应用后按提示授权「显示在其他应用上层」，返回应用后点「开启桌宠」。[下载 APK](https://github.com/haoye001/GPT-/raw/refs/heads/main/android/DragonPet-Android.apk)

开启后可返回手机桌面或切换到其他应用。轻点白龙娘播放动作，拖动调整位置，长按关闭。五段透明动画已内置，应用可离线使用，无需登录或打开 ChatGPT。

源码、配套素材和构建步骤见 [Android 目录](android/README.md)。

## Windows 版

Windows 版在同一个本地插件市场中提供两套独立桌宠，共用 Python 环境和 Codex 启动监控。

| 插件 | 功能 |
| --- | --- |
| 白龙娘 `bailong-pet` | 透明 WebP 动画、拖拽、对话气泡、可选工作状态和 Codex 额度展示 |
| DSH 白龙 `dsh-dragon` | MP4 绿幕播放、点击和拖拽互动、`dragon_control` 接口 |

### 随附素材

仓库包含 25 段白龙娘透明 WebP 动画和 DSH 白龙的待机 MP4，素材总计约 662 MiB。白龙娘会在本机按需生成播放缓存。

可用 `-VideoSource` 导入额外的 DSH MP4。以 `点击回应` 开头的视频用于点击互动，`被鼠标拖拽悬空反馈.mp4` 用于拖拽动作。素材来源与授权见下方说明。

### 安装

需要 Windows、已安装的 Codex 桌面版，以及带 Tk 的 Python 3.11 或更高版本。在仓库根目录运行 PowerShell，并替换示例中的本地路径。

```powershell
cd codex-adapter
.\install.ps1 -PythonPath 'D:\python\python.exe'
```

默认安装两个插件。只安装白龙娘时，可传入 `-Plugins bailong-pet` 。如果无法自动定位 Codex CLI，可用 `-CodexPath` 指定可执行文件的绝对路径。

安装脚本会创建隔离 Python 环境、注册本地市场 `bailong-local`，并创建或更新当前用户的登录启动快捷方式。后台监控在检测到 Windows Store 版 Codex 打开时启动所选桌宠，在 Codex 完全退出时关闭桌宠。工作状态 hooks 可在 Codex 中审阅后启用。

### 使用和开发

- 在 Codex 新聊天中可请求启动桌宠、播放动作或显示气泡。白龙娘还支持通过桌宠菜单查询 Codex 额度。
- [详细安装和自启动说明](codex-adapter/README.md)
- [白龙娘使用手册](codex-adapter/BAILONG.md)
- [白龙娘素材来源和许可](codex-adapter/plugins/bailong-pet/ASSETS.md)

在 `codex-adapter` 目录完成环境配置后运行测试。

```powershell
.\.runtime\Scripts\python.exe -m unittest discover -s tests -v
```
