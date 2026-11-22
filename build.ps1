$ErrorActionPreference = 'Stop'
$mascotSource = $PSScriptRoot
$mascotPython = Join-Path $mascotSource '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $mascotPython)) {
    $mascotPython = Join-Path (Split-Path -Parent $mascotSource) '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $mascotPython)) {
    throw 'Create .venv and install requirements.txt first. See README.md.'
}
Push-Location -LiteralPath $mascotSource
$mascotOriginalPath = $env:PATH
$mascotName = 'window AI'
$mascotDist = Join-Path $mascotSource "dist\$mascotName"
$mascotPortableSettingsPath = Join-Path $mascotDist 'data\settings.json'
$mascotLegacySettingsPath = Join-Path $mascotSource 'dist\Window Dragon\data\settings.json'
$mascotPortableSettings = $null
if (Test-Path -LiteralPath $mascotPortableSettingsPath) {
    $mascotPortableSettings = [System.IO.File]::ReadAllBytes($mascotPortableSettingsPath)
} elseif (Test-Path -LiteralPath $mascotLegacySettingsPath) {
    $mascotPortableSettings = [System.IO.File]::ReadAllBytes($mascotLegacySettingsPath)
}
if ((Test-Path -LiteralPath $mascotDist) -and
    ((Resolve-Path -LiteralPath $mascotDist).ProviderPath -ne $mascotDist -or
     (Get-Item -LiteralPath $mascotDist).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Unexpected build destination $mascotDist"
}
try {
    # Tool-host PATH entries can contain unrelated ICU and Windows runtime DLLs.
    # Resolve Windows dependencies from this machine, alongside Python and Qt.
    $env:PATH = @(
        (Join-Path $env:SystemRoot 'System32')
        $env:SystemRoot
        (Split-Path -Parent $mascotPython)
    ) -join ';'
    & $mascotPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $mascotPython -m PyInstaller --clean --noconfirm --windowed --onedir --name $mascotName --add-data 'assets:assets' --exclude-module tkinter --exclude-module unittest mascot.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    Copy-Item -LiteralPath (Join-Path $mascotSource 'README.md') -Destination (Join-Path $mascotDist 'README.md') -Force
    Compress-Archive -LiteralPath $mascotDist -DestinationPath "$mascotDist.zip" -Force
    Write-Output (Join-Path $mascotDist "$mascotName.exe")
} finally {
    $env:PATH = $mascotOriginalPath
    Pop-Location
    # Preserve this computer's portable preferences without putting them in the ZIP.
    if ($null -ne $mascotPortableSettings) {
        [System.IO.Directory]::CreateDirectory((Split-Path -Parent $mascotPortableSettingsPath)) | Out-Null
        [System.IO.File]::WriteAllBytes($mascotPortableSettingsPath, $mascotPortableSettings)
    }
}
