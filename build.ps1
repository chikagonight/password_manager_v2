param(
    [switch]$CleanOnly,
    [switch]$SkipInstaller,
    [switch]$SkipDependencies,
    [switch]$DependenciesOnly
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

$lockPath = Join-Path $projectRoot "requirements-build.lock"
if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
    throw "Build dependency lock is missing: $lockPath"
}

if (-not $SkipDependencies) {
    Write-Host "Installing locked build and CI dependencies..."
    & $pythonPath -m pip install --disable-pip-version-check --no-deps --requirement $lockPath
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed with exit code $LASTEXITCODE"
    }
    & $pythonPath -m pip install --disable-pip-version-check --no-deps --no-build-isolation --editable $projectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Project installation failed with exit code $LASTEXITCODE"
    }
}

# Проверка обязательна и при -SkipDependencies: обход lock-файла не допускается.
$verifyDependencies = @'
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement

errors = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = line.split("#", 1)[0].strip()
    if not line:
        continue
    requirement = Requirement(line)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    pins = list(requirement.specifier)
    if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
        errors.append(f"Unpinned build dependency: {line}")
        continue
    try:
        actual = version(requirement.name)
    except PackageNotFoundError:
        actual = "not installed"
    if actual != pins[0].version:
        errors.append(f"{requirement.name}: expected {pins[0].version}, found {actual}")
if errors:
    raise SystemExit("Build dependencies differ from lock:\n" + "\n".join(errors))
'@
$verifyDependencies | & $pythonPath - $lockPath
if ($LASTEXITCODE -ne 0) {
    throw "Build dependency verification failed. Run build.ps1 without -SkipDependencies."
}
& $pythonPath -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "Installed dependencies are inconsistent."
}
if ($DependenciesOnly) {
    exit 0
}

$env:PYINSTALLER_CONFIG_DIR = Join-Path $buildPath ".pyinstaller"
& $pythonPath -I -m PyInstaller `
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
& $pythonPath -I -m PyInstaller `
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
