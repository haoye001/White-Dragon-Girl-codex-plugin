param(
    [Parameter(Mandatory)][string]$AndroidJar,
    [Parameter(Mandatory)][string]$BuildTools,
    [Parameter(Mandatory)][string]$JavaHome,
    [Parameter(Mandatory)][string]$KeyStore,
    [string]$KeyAlias = 'dragonpet'
)
$ErrorActionPreference = 'Stop'
$env:JAVA_HOME = (Resolve-Path -LiteralPath $JavaHome).Path
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
$out = Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force $out,"$out/classes" | Out-Null
$sources = @(Get-ChildItem "$PSScriptRoot/src" -Filter '*.java' -File)
$classes = "$out/classes"

function Invoke-BuildTool($program, $arguments) {
    & $program @arguments
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $program ($LASTEXITCODE)" }
}

Invoke-BuildTool "$env:JAVA_HOME/bin/javac.exe" (@('-encoding','UTF-8','-source','17','-target','17','-classpath',$AndroidJar,'-d',$classes) + $sources.FullName)
$bytecode = @(Get-ChildItem $classes -Filter '*.class' -File -Recurse)
Invoke-BuildTool "$BuildTools/d8.bat" (@('--lib',$AndroidJar,'--min-api','28','--output',$out) + $bytecode.FullName)
Invoke-BuildTool "$BuildTools/aapt2.exe" @('link','-I',$AndroidJar,'--manifest',"$PSScriptRoot/AndroidManifest.xml",'-A',"$PSScriptRoot/assets",'-o',"$out/unsigned.apk")
Invoke-BuildTool "$env:JAVA_HOME/bin/jar.exe" @('uf',"$out/unsigned.apk",'-C',$out,'classes.dex')
Invoke-BuildTool "$BuildTools/zipalign.exe" @('-f','4',"$out/unsigned.apk","$out/aligned.apk")
$apk = "$PSScriptRoot/DragonPet-Android.apk"
$signing = @('sign','--ks',$KeyStore,'--ks-key-alias',$KeyAlias,'--out',$apk)
if ($env:DRAGONPET_KEYSTORE_PASSWORD) {
    $signing += @('--ks-pass','env:DRAGONPET_KEYSTORE_PASSWORD')
}
Invoke-BuildTool "$BuildTools/apksigner.bat" ($signing + "$out/aligned.apk")
Invoke-BuildTool "$BuildTools/apksigner.bat" @('verify','--verbose',$apk)
