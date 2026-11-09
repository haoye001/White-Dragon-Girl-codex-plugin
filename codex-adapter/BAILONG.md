# 白龙娘 · Codex 桌面伙伴

由本机 BailongPet 0.4.1 素材改造的 Windows Codex 插件，25 段原动画，新写的可审阅 Python 源码。原 BailongPet 目录保持不变。它是独立桌面窗口，不替换 Codex/ChatGPT 内置 Pets，也不是 OpenAI 官方插件。

## 安装

安装步骤见 [白龙桌宠合集](README.md)。白龙娘使用其中的 `bailong-pet` 插件。

## 使用

- “启动白龙娘桌宠”
- “让白龙娘说：今天也一起加油”
- “让白龙娘招手”
- “查询我的 Codex 额度，并显示在白龙桌宠上”
- “隐藏白龙娘” / “显示白龙娘” / “关闭白龙娘”

单击桌宠随机互动；拖动移动，松开播放落地；右键可选动作、查询额度和退出。隐藏后通过 Codex 的 show 恢复。完整对话仍在当前 Codex 聊天，带圆角和小尾巴的独立气泡随文字自动调整高度并跟随桌宠移动，不保存聊天历史。

1.1.0 默认每 30–60 秒随机播放一个互动动作并显示对应台词，避免连续重复。拖拽、隐藏、任务工作、额度查询、台词气泡或其他动画进行中会避让。右键“定时随机互动”可以关闭，右键“自动互动间隔”可以选 10–20 秒、30–60 秒、1–2 分钟、2–4 分钟；偏好保存在运行数据目录的 settings.json。

双击桌宠或右键“查询 Codex 额度”会后台读取真实账户额度，在气泡显示剩余比例和重置时间。仅通过安装时确定的 Codex 绝对路径启动短暂的只读 app-server，调用 initialize / account/rateLimits/read，完成后关闭连接；不创建对话、不调用模型、不消耗重置券、不读取 auth.json。接口依据[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)。Codex 路径失效时可重跑 setup.ps1 -CodexPath '可信绝对路径'；登录和网络失败会明确显示错误，不把未知数值显示为 0。右键“显示上次额度”会标明查询时间。聊天侧仍支持 get_usage_limits 传入额度；两种方式均不表示 ChatGPT 的所有模型余额。

工作状态 hooks 只处理事件名，只更新已经启动的桌宠，不会随 Windows 登录自动启动。Stop 仅将桌宠设为空闲，不伪报成功或庆祝。多个聊天共用一个桌宠，状态表示最近收到的事件，不是全部聊天的聚合状态。

## 安全与数据

没有打包原 EXE/DLL，不执行用户命令、不读取 Codex auth.json、没有后台模型调用、没有任意文件读写 MCP 工具。动画只允许素材目录内的 WebP，并限制尺寸、帧数和文件大小。Pillow 固定为 13.0.0，使用隔离环境，不修改全局 Python。

1.0.1 使用预先渲染到 300×300 的无损 RGBA 帧缓存，解压和首次缩放全部在后台线程执行。界面线程每次只创建当前帧图片，保留三张 Tk 图片；解码帧缓存预算为 160 MiB（后台正在加载的临时帧和 Tk 内部内存另计），固定保留待机、拖拽和落地，其余按最近使用顺序淘汰。首次切换时继续播放当前动画，加载完成后切换；连续点击只采用最新选择，工作事件不重复重启动画。缺少预处理文件时会后台生成到运行数据目录 frame-cache，不冻结界面。

维护素材后，可重新生成随插件携带的预处理缓存，保留原始文件且不增加画质损失：

```powershell
.\.runtime\Scripts\python.exe .\prepare_animations.py
```

这些缓存仅含动画帧和帧间隔，不含个人数据。`animation-benchmark.json` 和 `desktop-benchmark.json` 记录本机预处理读取时间及真实窗口的响应时间，不能视为其他电脑的性能保证。

运行时用随机端口监听 127.0.0.1，所有命令需要随机 bearer token，客户端禁用代理。端点令牌、偏好和启动锁保存在 `%LOCALAPPDATA%/BailongCodexPlugin`（统一安装时由配置指定，供后台监控、MCP 和 hooks 共用）；同一 Windows 用户权限的其他进程不在隔离边界内。气泡文字和额度只在内存，只有互动开关/间隔写入 settings.json；runtime.log 只接收运行错误，不主动记录请求正文。`BAILONG_PLUGIN_DATA` 可覆盖运行数据位置，测试使用专门目录。

统一安装版由共享后台监控随 Codex 开启和退出。卸载：先关闭桌宠，在 Codex 插件管理中卸载此插件；可移除 bailong-local 市场，再自行删除市场目录和运行数据目录。不要删除其他插件或 Codex 账号数据。

## 验证与许可

```powershell
.\.runtime\Scripts\python.exe -m unittest discover -s tests -v
```

代码、插件清单和测试均可本地审阅。美术未额外授权再分发/商用，详见 plugins/bailong-pet/ASSETS.md；此版本供本机使用，未发布到公共市场。
