# Set up this clone to play from source on Windows: Python 3.10+, a .venv with the
# game's requirements, the SDL2 and SDL2_ttf DLLs, then the self-test. Safe to run again.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# The offline package is the other route; see docs\RELEASE-CHECKLIST.md.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$candidates = @(
    @{ Exe = 'py'; Pre = @('-3') },
    @{ Exe = 'python'; Pre = @() },
    @{ Exe = 'python3'; Pre = @() }
)
$boot = $null
foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
    & $candidate.Exe @($candidate.Pre) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { $boot = $candidate; break }
}
if (-not $boot) {
    Write-Host 'Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/,' -ForegroundColor Red
    Write-Host 'tick "Add python.exe to PATH", open a new PowerShell window, and run this script again.' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host 'Creating .venv ...'
    & $boot.Exe @($boot.Pre) -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
}
Write-Host "Installing the game's Python requirements ..."
& '.venv\Scripts\python.exe' -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip could not install requirements.txt.' }

# The same loaders the game uses. On Windows they look for the DLLs beside the game.
$check = @'
import sys
from fishing.platform import _load, find_font
try:
    _load("libSDL2-2.0.so.0")
    _load("libSDL2_ttf-2.0.so.0")
except OSError as error:
    print(error)
    sys.exit(3)
'@
& '.venv\Scripts\python.exe' -c $check
switch ($LASTEXITCODE) {
    0 { }
    3 {
        Write-Host 'SDL2.dll and SDL2_ttf.dll must be in the clone folder:' -ForegroundColor Yellow
        Write-Host "  $root"
        Write-Host 'Download both runtime zips and copy every .dll from them into that folder:'
        Write-Host '  https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9-win32-x64.zip'
        Write-Host '  https://github.com/libsdl-org/SDL_ttf/releases/download/release-2.22.0/SDL2_ttf-2.22.0-win32-x64.zip'
        Write-Host 'Then run this script again.'
        exit 1
    }
    default { exit $LASTEXITCODE }
}

Write-Host 'Running the self-test ...'
& '.venv\Scripts\python.exe' -m fishing --selftest --software
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Setup complete. Start the game with: .venv\Scripts\python.exe -m fishing'
