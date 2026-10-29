$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Project Python was not found at .venv\Scripts\python.exe.'
}
$taskMain = Join-Path $taskProjectRoot 'main.py'
# main.py and collectors share the same .env and persistent Chrome profile.
& $taskPython $taskMain browser --open
exit $LASTEXITCODE
