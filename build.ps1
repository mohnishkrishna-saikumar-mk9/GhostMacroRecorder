# Build Ghost Macro Recorder: icons -> tests -> PyInstaller app folder -> Setup installer
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "1. Generating icon assets..."
.\.venv\Scripts\python.exe scripts\generate_icon.py

Write-Host "2. Running unit tests..."
.\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

Write-Host "3. Packaging app folder via PyInstaller..."
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm GhostMacroRecorder.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "4. Building Setup installer via Inno Setup..."
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup not found - install it with: winget install JRSoftware.InnoSetup"
    Write-Host "App folder is ready at dist\GhostMacroRecorder\"
    exit 0
}
& $iscc installer\GhostMacroRecorder.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "Done! Installer: dist\GhostMacroRecorder-Setup.exe"
