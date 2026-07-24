@echo off
setlocal
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%~dp0wr_archon_importer.py"
) else (
  python "%~dp0wr_archon_importer.py"
)
if not %errorlevel% equ 0 pause
