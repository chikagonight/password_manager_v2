param(
    [switch]$CleanOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Virtual environment not found. Create .venv and install .[build] first."
}

if ($CleanOnly) {
    $buildPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
    $distPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "dist"))
    $expectedPrefix = [IO.Path]::GetFullPath($projectRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $buildPath.StartsWith($expectedPrefix) -or -not $distPath.StartsWith($expectedPrefix)) {
        throw "Refusing to remove paths outside the project directory."
    }
    Remove-Item -LiteralPath $buildPath -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $distPath -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name PasswordManagerV2 `
    --collect-all customtkinter `
    (Join-Path $projectRoot "password_manager_app.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "Build created at: $(Join-Path $projectRoot 'dist\PasswordManagerV2\PasswordManagerV2.exe')"
