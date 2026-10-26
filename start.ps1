$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python server.py --port 8765
