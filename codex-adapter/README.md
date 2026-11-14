# 白龙桌宠合集

本项目将两套桌宠整合到同一个 Codex 本地市场和 Python 环境。

| 插件 | 功能 |
| --- | --- |
| `bailong-pet` | 25 段透明 WebP 动画、气泡、工作状态和额度展示 |
| `dsh-dragon` | MP4 绿幕播放、点击和拖拽互动、`dragon_control` 接口 |

DSH 白龙的右键菜单可锁定位置、调整不透明度和播放速率、设置自动互动间隔，以及复制当前动画画面。锁定后按住 Shift 仍可拖动。位置和播放设置会在重启后恢复。

系统托盘提供显示、隐藏、鼠标穿透和退出。隐藏时暂停动画与自动互动。右键可开启点击提示音和随机自言自语。装有「吃Token」动作时，把本地文件拖到桌宠上可触发该动画，文件留在原位。

拖动时白龙会转向，快速松手会短距离滑行。右键可启用「边缘探头」，或选择「黄金回旋」播放一圈旋转。托盘头像取自随附的白龙娘待机动画。

Windows 下可在右键菜单勾选「全局显隐快捷键（Ctrl+Alt+P）」。启用后，即使桌宠处于隐藏状态也能用该组合键重新显示。

- **待办提醒**可在主桌宠右键菜单添加、编辑和删除多条事项。每条可设置到期时间和提前量。到期自动归档，超过 10 分钟的补发宽限后只归档。桌宠可见时用气泡提醒，隐藏时通过托盘通知。
- **配置菜单**可勾选顶层菜单项的显隐并拖动排序，点击保存后生效。
- **切换角色**可从右键选择「大肥鱼」或「默认白龙」。随附的大肥鱼角色包含 106 段透明 WebM。[素材来源与许可](plugins/dsh-dragon/assets/characters/大肥鱼/ASSETS.md)
- **自定义角色**可放在 `plugins/dsh-dragon/assets/characters/<角色名>/`。待机素材可命名为 `idle` 或 `待机呼吸休闲`，也可放在 `idle` 子目录。MP4 使用绿幕处理。透明 VP9 WebM 需要支持 `libvpx-vp9` 的 FFmpeg。请将 `ffmpeg.exe` 放进本地市场的 `.runtime/Scripts/` 或加入 PATH。可运行 `ffmpeg -decoders | Select-String libvpx-vp9` 检查 PATH 版本。
- **新增桌宠**最多可同时打开八只。各自保存角色、位置和播放设置。动画在后台解码，相同素材与速率的待机动画共享解码器。短待机循环复用原始 RGBA 帧，全部桌宠共用 96 MiB 的帧缓存额度。超出额度的内容继续流式解码，单次互动独立播放。
- **Codex 联动**通过 `dragon_control` 的 `activity` 命令接收 `thinking`、`working`、`attention`、`idle`。统一安装会生成可选工作状态 hooks，可在 Codex 的 **设置 → Hooks** 中审阅并信任。联动只使用事件名，桌宠需要已启动。已直接执行 Windows hooks 并验证「写代码 → 待机」切换。临时 Codex 会话的模型请求超时，自动联动的完整链路仍待验证。
- **查询 Codex 额度**可在右键菜单或托盘触发，后台通过安装时配置的 Codex 路径读取本机登录账户额度，并显示剩余百分比、重置时间和查询时间。
- **桌面小工具**可抽取每日一签，查看公历、农历节日和节气，设置公历生日提醒。节日与节气提醒、整点报时可单独开启，整点以系统提示音和气泡报时。快捷启动可选取本机 `.exe` 并从菜单打开。

在本目录运行以下命令。首次安装需要提供可信的 Python 3.11+ 绝对路径，Python 需包含 Tk。

```powershell
.\install.ps1 -PythonPath 'D:\python\python.exe'
```

默认在 `bailong-local` 下安装两个插件。可用 `-Plugins bailong-pet` 仅安装白龙娘，也可用 `-VideoSource 'D:\Desktop\素材库'` 导入额外的 DSH MP4。仓库随附 DSH 待机视频。若已有同名市场指向旧目录，请在 Codex 插件管理中移除旧市场登记后重新运行安装。

`setup.ps1` 仅创建共享环境和生成插件配置。统一安装入口更新 Windows 登录启动项中的 DSH Dragon Codex 快捷方式。一个后台监控负责启动所选桌宠。打开 Windows Store 版 Codex 时启动，Codex 完全退出时关闭。手动退出桌宠后，下次打开 Codex 才会再次自动启动。若旧版监控仍在运行，注销并重新登录 Windows 后切换到新版。白龙娘工作状态 hooks 由 Codex 的信任流程管理。

白龙娘的操作和素材许可见 [BAILONG.md](BAILONG.md) 和 [ASSETS.md](plugins/bailong-pet/ASSETS.md)。

```powershell
.\.runtime\Scripts\python.exe -m unittest discover -s tests -v
```
