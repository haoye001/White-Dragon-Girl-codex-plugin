---
name: dragon-desktop
description: 控制 DSH 改造的白龙素材桌宠，启动、关闭、播放动作、显示气泡。
---

使用 dragon_control 控制本地桌宠。先用 state 获取真实动作名称，再用 play 播放。
start 启动；stop 退出；show/hide 显隐；say 展示不超过100字的气泡。
仅在用户要求桌宠参与时向气泡传递聊天内容。不读取凭据、不创建额外模型会话。
随 Codex 启动由本机 monitor.py 负责，不修改或自动信任 Codex hooks。
