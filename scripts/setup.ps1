$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

# uv manages Python 3.13 without modifying the system Python.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv (official Astral installer)...'
    irm https://astral.sh/uv/install.ps1 | iex
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:PATH"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv was not found after installation. Open a new PowerShell window and retry.'
}

$python313 = Get-Command python3.13 -ErrorAction SilentlyContinue
if ($python313) {
    $interpreter = $python313.Source
} else {
    Write-Host 'Ensuring Python 3.13 is installed...'
    uv python install 3.13
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 installation failed.' }
    $interpreter = '3.13'
}

uv venv --clear --python $interpreter .venv
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& .\.venv\Scripts\python.exe -c 'import sys; assert sys.version_info >= (3, 13), sys.version'
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed.' }
Write-Host 'Ready: .\.venv\Scripts\python.exe -m netmon start'
