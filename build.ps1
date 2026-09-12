param(
    [switch]$CleanOnly,
    [switch]$SkipInstaller,
    [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appName = "passwordSafe"
$buildPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
$distPath = [IO.Path]::GetFullPath((Join-Path $projectRoot "dist"))
$expectedPrefix = [IO.Path]::GetFullPath($projectRoot) + [IO.Path]::DirectorySeparatorChar

if ($CleanOnly) {
    if (-not $buildPath.StartsWith($expectedPrefix) -or -not $distPath.StartsWith($expectedPrefix)) {
        throw "Refusing to remove paths outside the project directory."
    }
    Remove-Item -LiteralPath $buildPath -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $distPath -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Write-Host "Creating Python 3.14 virtual environment..."
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3.14 -m venv $venvPath
    }
    else {
        $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $systemPython) {
            throw "Python 3.14 was not found. Install it and enable the py launcher or add python.exe to PATH."
        }
        $systemPythonVersion = (& $systemPython.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
        if ($systemPythonVersion -ne "3.14") {
            throw "Python 3.14 is required, but python.exe reports $systemPythonVersion."
        }
        & $systemPython.Source -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Failed to create the Python 3.14 virtual environment."
    }
}

$pythonVersion = (& $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne "3.14") {
    throw "The project virtual environment must use Python 3.14. Current version: $pythonVersion"
}

if (-not $SkipDependencies) {
    Write-Host "Installing build dependencies..."
    $editableTarget = "$projectRoot[build]"
    & $pythonPath -m pip install --disable-pip-version-check --editable $editableTarget
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed with exit code $LASTEXITCODE"
    }
}

& $pythonPath -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name $appName `
    --distpath $distPath `
    --workpath $buildPath `
    --specpath $projectRoot `
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
    --distpath $distPath `
    --workpath $buildPath `
    --specpath $projectRoot `
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
