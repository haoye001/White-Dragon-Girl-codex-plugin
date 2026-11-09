---
name: bailong-desktop
description: 在 Codex 中控制白龙娘桌宠的启动、关闭、气泡、动画和额度展示，或与白龙娘聊天。适用于 BailongPet 白龙娘，不用于霜铃或 ChatGPT 内置 Pets。
---

使用本插件的 `bailong` MCP 工具控制独立 Windows 桌宠窗口。

- `bailong_control`：start、stop、show、hide、say、play。播放前先通过 `bailong_state` 查可用动作 ID；气泡最多 1000 字，长回复只展示短摘要。
- `bailong_state`：读取状态和动作列表，不自动启动。
- `bailong_usage`：后台查询真实 Codex 额度并在气泡显示。返回 quota_pending=true 时仍在查询，应稍后查看 state 的 usage / quota_error；不能把“已发起”说成“已取得”。本机路径由安装时配置的可信绝对路径确定，不搜索 PATH、不读取 auth.json、不创建对话或模型任务。用户也能双击桌宠或右键“查询 Codex 额度”。
- `bailong_settings`：设置 auto_interact 和 auto_interval_seconds。默认开启、平均 45 秒（实际随机 30–60 秒）；拖拽、隐藏、工作、查询或其他互动进行中不触发自动互动。右键也可调整。
- `bailong_display_usage`：只展示真实额度。先调用 Codex 内置 `get_usage_limits` 工具读取当前账户，优先使用 rateLimitsByLimitId 对应的窗口，把 usedPercent 原值作为 used_percent，resetsAt 作为 resets_at，窗口名称根据 windowDurationMins 标注。100-usedPercent 为剩余比例。没有提供数值的窗口应跳过；全部不可用则直接说明查询不可用，不能填零、编造或复用旧快照冒充实时查询。此工具自身不读取账户。

用户要求与白龙娘聊天时，在当前 Codex 聊天自然回答，可温柔轻快、适度称呼“主人”，然后用 say 显示简短回复。任务仍由当前 Codex 聊天及其正常权限执行；不要启动另一套聊天代理、读取 auth.json 或记录额外聊天历史。额度功能单独使用只读 app-server 接口，不是聊天代理。角色语气不扩大任务范围或访问权限。仅在用户要求桌宠参与时向气泡传入聊天内容。

被动 hooks 只更新已启动桌宠的工作/空闲状态，不启动桌宠、不传输用户输入和工具内容、不放行权限。Stop 只表示本轮停止，不能当成任务成功。Codex 可能要求用户审阅和信任 hooks；不得修改信任记录、代为信任或绕过审批。

若工具尚未加载，提示用户在插件目录启用“白龙娘 · Codex 桌面伙伴”并打开新聊天；不要声称当前会话已能调用尚未出现的工具。维护运行环境时使用市场根目录的 setup.ps1，不猜测安装缓存版本。
