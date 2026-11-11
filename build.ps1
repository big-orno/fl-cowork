# Construit dist\FLCoworkSetup.exe (installateur + application, un seul fichier).
# Prerequis : Python 3.13+ (TLS-PSK). Usage : powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$venv = Join-Path $PSScriptRoot '.build-venv'
if (-not (Test-Path $venv)) { py -3.14 -m venv $venv }
& "$venv\Scripts\python.exe" -m pip install --quiet --upgrade pip pyinstaller
& "$venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name FLCoworkSetup --paths . `
    --add-data "$PSScriptRoot\fl_script\device_FLCowork.py;." `
    --distpath dist --workpath build --specpath build `
    cowork\__main__.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a echoue" }
Write-Output "OK -> $(Join-Path $PSScriptRoot 'dist\FLCoworkSetup.exe')"
