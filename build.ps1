$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

python -m PyInstaller --clean --noconfirm vm-clone.spec

$artifact = Get-Item -LiteralPath "$projectRoot\dist\vm-clone.exe"
$sizeMb = [math]::Round($artifact.Length / 1MB, 2)
Write-Host "Build complete: $($artifact.FullName) ($sizeMb MB)"
