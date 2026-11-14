# 白龙娘桌宠 Android 版

[下载已签名的 APK](https://github.com/hyG0611/White-Dragon-Girl-codex-plugin/raw/refs/heads/main/android/DragonPet-Android.apk)

安装后打开「白龙娘桌宠」，授予显示在其他应用上层的权限，然后点击「开启桌宠」。Android 9 及以上可用。轻点随机播放招手、比心、庆祝或困倦动画，拖动调整位置。长按打开「选择动作」菜单，可选择全部 25 段动画，也可在菜单或应用首页关闭桌宠。应用无需网络或 ChatGPT 账号。

## 配套资源

`assets/` 包含 Windows 版白龙娘的全部 25 段透明动画及动作清单，均已打进 APK。菜单中的「查阅额度」和工作动作可作为动画手动播放。素材缩小到最长边 384 像素，保留透明度与帧时序。[素材来源与许可](../codex-adapter/plugins/bailong-pet/ASSETS.md)

## 本地构建

使用 JDK 17 或更新版本、Android SDK Platform 35 和 Build Tools 35.0.1。准备自己的 Android 签名密钥。更新同一安装包时需要使用原签名密钥。

```powershell
.\build.ps1 -JavaHome 'D:\jdk' -AndroidJar 'D:\Android\platforms\android-35\android.jar' `
    -BuildTools 'D:\Android\build-tools\35.0.1' -KeyStore 'D:\keys\dragonpet.jks'
```

输出为 `DragonPet-Android.apk`。如需补齐素材，可在安装 Pillow 的 Python 环境中运行 `python prepare_assets.py`。要重新转换某段动画，请先移除对应的移动端 WebP，再运行脚本。
