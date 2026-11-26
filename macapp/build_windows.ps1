# Builds the Windows app: dist-win\Job Finder\Job Finder.exe and a zip next to it.   Usage: macapp\build_windows.ps1
# Needs Python 3.11 or 3.12. Windows 10/11 already include the WebView2 runtime the window uses.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$venv = Join-Path (Get-Location).Path ".winbuild\venv"
if (-not (Test-Path $venv)) { & $py -m venv $venv }
& "$venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt -r macapp\requirements-app.txt

if (Test-Path dist-win) { Remove-Item dist-win -Recurse -Force }
& "$venv\Scripts\pyinstaller.exe" macapp\job_finder.spec --noconfirm --distpath dist-win --workpath (Join-Path (Get-Location).Path ".winbuild\work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$zip = "dist-win\Job-Finder-$version-windows.zip"
Compress-Archive -Path "dist-win\Job Finder" -DestinationPath $zip -Force
Write-Host "Built: dist-win\Job Finder\Job Finder.exe and $zip"
