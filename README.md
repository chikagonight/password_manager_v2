# passwordSafe

Локальный менеджер паролей для Windows с зашифрованным хранилищем.

## Требования для сборки

- Windows 10 или 11;
- Python 3.14 с командой `py` или `python` в `PATH`;
- доступ к интернету при первом запуске скрипта.

## Сборка

Откройте PowerShell в корне проекта и выполните:

```powershell
.\build.ps1
```

Скрипт сам создаст `.venv`, установит зависимости и соберёт приложение с установщиком.

Если выполнение PowerShell-скриптов запрещено политикой системы:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

Готовые файлы:

```text
dist\passwordSafe-Setup.exe
dist\passwordSafe\passwordSafe.exe
```

Для установки запустите `passwordSafe-Setup.exe` и выберите папку, где будет находиться приложение.

## Параметры скрипта

```powershell
.\build.ps1 -SkipDependencies  # не проверять и не устанавливать зависимости
.\build.ps1 -SkipInstaller     # собрать только приложение
.\build.ps1 -CleanOnly         # удалить каталоги build и dist
```
