# GPT 白龙桌宠合集

本仓库提供 Android 独立桌宠和 Windows Codex 桌宠插件。

## Android 版

支持 Android 9 及以上。下载并安装白龙娘桌宠，打开应用后按提示授权「显示在其他应用上层」，返回应用后点「开启桌宠」。[下载 APK](https://github.com/hyG0611/White-Dragon-Girl-codex-plugin/raw/refs/heads/main/android/DragonPet-Android.apk)

开启后可返回手机桌面或切换到其他应用。轻点白龙娘随机播放互动，拖动调整位置，长按打开菜单，可手动选择全部 25 段动作或关闭桌宠。动画已内置，应用可离线使用，无需登录或打开 ChatGPT。

源码、配套素材和构建步骤见 [Android 目录](android/README.md)。

## Windows 版

Windows 版在同一个本地插件市场中提供两套独立桌宠，共用 Python 环境和 Codex 启动监控。

| 插件 | 功能 |
| --- | --- |
| 白龙娘 `bailong-pet` | 透明 WebP 动画、拖拽、对话气泡、可选工作状态和 Codex 额度展示 |
| DSH 白龙 `dsh-dragon` | MP4 与透明 VP9 WebM、角色切换、同进程多宠、待办提醒、可选 Codex 工作状态联动 |

### 随附素材

仓库包含 25 段白龙娘透明 WebP、DSH 白龙的四段 MP4，以及大肥鱼角色包的 106 段透明 WebM。白龙娘会在本机按需生成播放缓存。

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

- DSH 白龙可通过托盘或自定义全局快捷键显隐，默认组合键为 **Ctrl+Alt+P**。「桌宠设置」集中管理不透明度、播放速率、气泡字号和互动开关。「配置菜单」支持显隐、排序、自定义子菜单和实时预览。
- 右键可新增桌宠、切换角色和管理多条待办。动画在后台解码，同素材、同速率的短待机循环可共享无损帧缓存。
- 自定义角色可使用绿幕 MP4 或透明 VP9 WebM。播放透明 WebM 需要将带 `libvpx-vp9` 的 FFmpeg 加入 PATH。
- 在 Windows 的 DSH 白龙桌宠上右键选择 **切换角色 → 大肥鱼** 即可使用随附角色包。选择「默认白龙」可切回原角色。角色包保留原有素材署名和非商业条款。[大肥鱼素材来源与许可](codex-adapter/plugins/dsh-dragon/assets/characters/大肥鱼/ASSETS.md)
- DSH 白龙可从右键菜单或托盘查询 Codex 剩余额度。「桌面小工具」含每日一签、节日与生日提醒、整点报时和本地应用快捷启动。
- 「桌面小工具 → 查看天气」默认查询成都。气泡显示气温、体感、湿度和数据时间，连接临时失败时会重试一次。
- 「桌面灵动岛」可从右键或托盘打开，显示 Windows 正在播放的媒体、同步歌词、下一条待办和 Codex 状态。歌词可加载本地 LRC，也可主动在线查询。
- 「桌宠对话」支持自定义模型、流式回复、本地会话历史和 Windows 本地朗读。截图问答在确认发送前会预览选区。主动识屏需手动开启并设置应用白名单、间隔和每日上限。[对话和识屏设置](codex-adapter/README.md#桌宠对话和识屏)
- DSH 工作状态可聚合多个 Codex 会话，优先显示待确认、工作和思考。自动联动需在 Codex 的 **设置 → Hooks** 中审阅并信任。已用真实 Codex CLI 和本地模拟模型验证工具调用与任务结束时的自动触发。
- 在 Codex 新聊天中可请求启动桌宠、播放动作或显示气泡。白龙娘还支持通过桌宠菜单查询 Codex 额度。
- [详细安装和自启动说明](codex-adapter/README.md)
- [白龙娘使用手册](codex-adapter/BAILONG.md)
- [白龙娘素材来源和许可](codex-adapter/plugins/bailong-pet/ASSETS.md)

在 `codex-adapter` 目录完成环境配置后运行测试。

```powershell
.\.runtime\Scripts\python.exe -m unittest discover -s tests -v
```
