# Claude2Antigravity installer for Windows PowerShell. Passes every argument to install.py.
#   .\install.ps1            # install the skill for Claude Code and Antigravity, preview the first sync
#   .\install.ps1 --sync     # ...and run the first sync
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { Write-Host "Python 3.10+ is needed: https://www.python.org/downloads/"; exit 1 }
& $py.Source "$PSScriptRoot\install.py" @args
exit $LASTEXITCODE
