# 白龙桌宠合集

本项目将两套桌宠整合到同一个 Codex 本地市场和 Python 环境。

| 插件 | 功能 |
| --- | --- |
| `bailong-pet` | 25 段透明 WebP 动画、气泡、工作状态和额度展示 |
| `dsh-dragon` | MP4 绿幕播放、点击和拖拽互动、`dragon_control` 接口 |

在本目录运行以下命令。首次安装需要提供可信的 Python 3.11+ 绝对路径，Python 需包含 Tk。

```powershell
.\install.ps1 -PythonPath 'D:\python\python.exe'
```

默认在 `bailong-local` 下安装两个插件。可用 `-Plugins bailong-pet` 仅安装白龙娘，也可用 `-VideoSource 'D:\Desktop\素材库'` 导入额外的 DSH MP4。DSH 需要在本机提供待机视频，素材目录须包含 `待机呼吸休闲.mp4`。若已有同名市场指向旧目录，请在 Codex 插件管理中移除旧市场登记后重新运行安装。

`setup.ps1` 仅创建共享环境和生成插件配置。统一安装入口更新 Windows 登录启动项中的 DSH Dragon Codex 快捷方式。一个后台监控负责启动所选桌宠。打开 Windows Store 版 Codex 时启动，Codex 完全退出时关闭。手动退出桌宠后，下次打开 Codex 才会再次自动启动。若旧版监控仍在运行，注销并重新登录 Windows 后切换到新版。白龙娘工作状态 hooks 由 Codex 的信任流程管理。

白龙娘的操作和素材许可见 [BAILONG.md](BAILONG.md) 和 [ASSETS.md](plugins/bailong-pet/ASSETS.md)。

```powershell
.\.runtime\Scripts\python.exe -m unittest discover -s tests -v
```
