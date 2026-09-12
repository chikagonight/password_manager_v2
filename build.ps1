param(
    [switch]$CleanOnly,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appName = "passwordSafe"

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
    --name $appName `
    --collect-all customtkinter `
    (Join-Path $projectRoot "password_manager_app.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

$appDistPath = Join-Path $projectRoot "dist\$appName"
$appExecutablePath = Join-Path $appDistPath "$appName.exe"
if (-not (Test-Path -LiteralPath $appExecutablePath -PathType Leaf)) {
    throw "Application executable was not created: $appExecutablePath"
}

Write-Host "Application created at: $appExecutablePath"

if ($SkipInstaller) {
    exit 0
}

$payloadArgument = "$appDistPath;payload"
& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "$appName-Setup" `
    --add-data $payloadArgument `
    (Join-Path $projectRoot "install_password_safe.py")

if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE"
}

$installerPath = Join-Path $projectRoot "dist\$appName-Setup.exe"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Installer executable was not created: $installerPath"
}

Write-Host "Installer created at: $installerPath"
