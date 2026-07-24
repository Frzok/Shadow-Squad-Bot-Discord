@echo off
setlocal
where py >nul 2>nul
if %errorlevel% equ 0 goto use_py
where python >nul 2>nul
if %errorlevel% equ 0 goto use_python
echo Python 3 ne naiden.
echo Ustanovite Python s https://www.python.org/downloads/windows/
echo Pri ustanovke vklyuchite Add Python to PATH.
pause
exit /b 1

:use_py
py -3 "%~dp0wr_archon_importer.py"
goto finished

:use_python
python "%~dp0wr_archon_importer.py"

:finished
if not %errorlevel% equ 0 pause
