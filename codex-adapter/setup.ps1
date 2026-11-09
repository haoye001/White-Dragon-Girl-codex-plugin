param([string]$PythonPath, [string]$CodexPath, [switch]$SkipDependencies, [string]$VideoSource)
$ErrorActionPreference = 'Stop'
$marketRoot = $PSScriptRoot
$pluginRoot = Join-Path $marketRoot 'plugins/bailong-pet'
$dragonRoot = Join-Path $marketRoot 'plugins/dsh-dragon'
$runtimePython = Join-Path $marketRoot '.runtime/Scripts/python.exe'
if (-not $CodexPath) {
    $codexBin = Join-Path $env:LOCALAPPDATA 'OpenAI/Codex/bin'
    $codexCandidates = @(Get-ChildItem -LiteralPath $codexBin -Filter 'codex.exe' -File -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($codexCandidates.Count -eq 0) { throw 'Supply a trusted Codex absolute path with -CodexPath.' }
    $CodexPath = $codexCandidates[0].FullName
}
if (-not [IO.Path]::IsPathRooted($CodexPath) -or -not (Test-Path -LiteralPath $CodexPath -PathType Leaf)) {
    throw 'CodexPath must be an existing absolute path.'
}
@{
    codex = $CodexPath
    dataDirectory = Join-Path $env:LOCALAPPDATA 'BailongCodexPlugin'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $pluginRoot 'runtime-config.json') -Encoding utf8
if (-not (Test-Path -LiteralPath $runtimePython)) {
    if (-not $PythonPath) { throw 'Supply a trusted Python 3.11+ absolute path: -PythonPath D:\python\python.exe' }
    if (-not [IO.Path]::IsPathRooted($PythonPath) -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'PythonPath must be an existing absolute path.'
    }
    & $PythonPath -c 'import sys,tkinter; assert sys.version_info >= (3,11), "Python 3.11+ required"'
    if ($LASTEXITCODE -ne 0) { throw 'Python/Tk validation failed.' }
    & $PythonPath -m venv (Join-Path $marketRoot '.runtime')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated runtime.' }
}
if (-not $SkipDependencies) {
    & $runtimePython -m pip install --disable-pip-version-check -r (Join-Path $marketRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed; plugin was not registered.' }
}
& $runtimePython -c 'import PIL,tkinter,cv2,numpy,psutil,PySide6.QtWidgets; assert int(PIL.__version__.split(".")[0]) >= 13, "Pillow 13+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Runtime validation failed.' }
$config = @{
    mcpServers = @{
        bailong = @{
            type = 'stdio'
            command = $runtimePython
            args = @('${PLUGIN_ROOT}/runtime/bridge.py', 'mcp')
            cwd = '${PLUGIN_ROOT}'
        }
    }
}
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $pluginRoot '.mcp.json') -Encoding utf8
@{ mcpServers = @{ dragon = @{
    type = 'stdio'
    command = $runtimePython
    args = @('${PLUGIN_ROOT}/runtime/bridge.py')
    cwd = '${PLUGIN_ROOT}'
} } } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $dragonRoot '.mcp.json') -Encoding utf8
if ($VideoSource) {
    $videos = @(Get-ChildItem -LiteralPath $VideoSource -Filter '*.mp4' -File)
    if (!$videos.Count) { throw 'VideoSource contains no MP4 files.' }
    $destination = Join-Path $dragonRoot 'assets/videos'
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    foreach ($video in $videos) {
        Copy-Item -LiteralPath $video.FullName -Destination $destination -Force
    }
}
$hookMap = @{}
foreach ($eventName in @('UserPromptSubmit','PreToolUse','PermissionRequest','Stop','Interrupt','SessionEnd')) {
    $hookMap[$eventName] = @(@{ hooks = @(@{
        type = 'command'
        command = ('"' + $runtimePython + '" "${PLUGIN_ROOT}/runtime/bridge.py" hook')
        timeout = 4
    }) })
}
@{ description = 'Only update an already-running companion. No prompts, commands or outputs are saved. No approval decisions.'; hooks = $hookMap } |
    ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $pluginRoot 'hooks/hooks.json') -Encoding utf8
Write-Output "Ready: $pluginRoot"
Write-Output 'No startup entry or plugin trust setting was changed.'
