param(
    [string]$PythonPath,
    [string]$CodexPath,
    [switch]$SkipDependencies,
    [string]$VideoSource,
    [ValidateSet('bailong-pet', 'dsh-dragon')]
    [string[]]$Plugins = @('bailong-pet', 'dsh-dragon')
)
$ErrorActionPreference = 'Stop'
if (-not $CodexPath) {
    $codexBin = Join-Path $env:LOCALAPPDATA 'OpenAI/Codex/bin'
    $candidates = @(Get-ChildItem -LiteralPath $codexBin -Filter 'codex.exe' -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -eq 0) { throw 'Provide the trusted Codex absolute path with -CodexPath.' }
    $CodexPath = $candidates[0].FullName
}
if (-not [IO.Path]::IsPathRooted($CodexPath) -or -not (Test-Path -LiteralPath $CodexPath -PathType Leaf)) {
    throw 'CodexPath must be an existing absolute path.'
}
& (Join-Path $PSScriptRoot 'setup.ps1') -PythonPath $PythonPath -CodexPath $CodexPath -SkipDependencies:$SkipDependencies -VideoSource $VideoSource
& $CodexPath plugin marketplace add $PSScriptRoot --json
if ($LASTEXITCODE -ne 0) { throw 'Marketplace registration failed.' }
foreach ($plugin in $Plugins) {
    & $CodexPath plugin add "$plugin@bailong-local" --json
    if ($LASTEXITCODE -ne 0) { throw "Plugin installation failed: $plugin" }
}
$monitor = Join-Path $PSScriptRoot 'plugins/dsh-dragon/runtime/monitor.py'
$pythonw = Join-Path $PSScriptRoot '.runtime/Scripts/pythonw.exe'
$arguments = '"' + $monitor + '" ' + ($Plugins -join ' ')
$startup = [Environment]::GetFolderPath('Startup')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startup 'DSH Dragon Codex.lnk'))
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7
$shortcut.Save()
Start-Process -FilePath $pythonw -ArgumentList $arguments -WindowStyle Hidden
Write-Output 'Open a new chat or restart Codex to load MCP tools.'
Write-Output 'Review optional hooks in Codex before trusting them.'
