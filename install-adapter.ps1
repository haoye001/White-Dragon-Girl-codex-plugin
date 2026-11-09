$ErrorActionPreference = 'Stop'
$target = 'D:\Desktop\ds-pet\dsh-pet\codex-adapter'
$stage = Join-Path $PSScriptRoot 'codex-adapter'
$codex = (Get-Process codex | Where-Object Path | Select-Object -First 1 -ExpandProperty Path)
if (-not $codex) { throw 'Codex executable not found' }
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item -Path "$stage\*" -Destination $target -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.runtime') -Destination $target -Recurse -Force
$plugin = Join-Path $target 'plugins\dsh-dragon'
Copy-Item -Path 'D:\Desktop\素材库\*.mp4' -Destination "$plugin\assets\videos" -Force
$python = Join-Path $target '.runtime\Scripts\python.exe'
$pythonw = Join-Path $target '.runtime\Scripts\pythonw.exe'
$manifest = @{
 name='dsh-dragon'; version='1.0.0'; description='使用用户提供的46段白龙动画的 Codex 桌宠';
 skills='./skills/'; mcpServers='./.mcp.json'; requires_local_executor=$true;
 interface=@{displayName='DSH 白龙 · Codex 素材版'; shortDescription='46段动画、点击拖拽、随 Codex 自动启动'}
}
New-Item -ItemType Directory -Force "$plugin\.codex-plugin", "$target\.agents\plugins" | Out-Null
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 "$plugin\.codex-plugin\plugin.json"
@{mcpServers=@{dragon=@{command=$python; args=@("$plugin\runtime\bridge.py")}}} | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 "$plugin\.mcp.json"
@{name='dsh-dragon-local'; interface=@{displayName='DSH 白龙本地适配'}; plugins=@(@{name='dsh-dragon'; source=@{source='local';path='./plugins/dsh-dragon'};policy=@{installation='AVAILABLE';authentication='ON_INSTALL'};category='Productivity'})} | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 "$target\.agents\plugins\marketplace.json"
& $codex plugin marketplace add $target --json
if ($LASTEXITCODE -ne 0) { throw 'Marketplace registration failed' }
& $codex plugin add dsh-dragon@dsh-dragon-local --json
if ($LASTEXITCODE -ne 0) { throw 'Plugin installation failed' }
$startup = [Environment]::GetFolderPath('Startup')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startup 'DSH Dragon Codex.lnk'))
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + "$plugin\runtime\monitor.py" + '"'
$shortcut.WorkingDirectory = $target
$shortcut.WindowStyle = 7
$shortcut.Save()
Start-Process -FilePath $pythonw -ArgumentList @('"' + "$plugin\runtime\monitor.py" + '"') -WindowStyle Hidden
Write-Output "Installed: $plugin"
Write-Output "Startup: $startup\DSH Dragon Codex.lnk"
