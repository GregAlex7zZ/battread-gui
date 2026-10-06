# Start the source application without activating its virtual environment.
$guiRoot = $PSScriptRoot
$guiPython = Join-Path $guiRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $guiPython)) {
    throw 'The local environment is missing. Follow the setup instructions in README.md.'
}
& $guiPython -m battread_gui
