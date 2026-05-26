@echo off
REM Double-click to run the guided conversion (Windows).
REM Activates the `traj` conda environment once, then loops on the experiment-id
REM prompt so you can process several experiments without re-activating. Searches
REM the standard Miniconda / Anaconda install paths so this works on a default
REM install where `conda` is NOT on PATH.
setlocal
cd /d "%~dp0"

call :ACTIVATE
if errorlevel 1 (
  echo.
  echo Could not activate the 'traj' conda environment.
  echo One-time setup:  conda env create -f environment.yml
  echo.
  pause
  exit /b 1
)

:MAIN
set /p EXPERIMENT="Enter the experiment id (start date, e.g. 2025-01-21): "
python -m src.convert "%EXPERIMENT%" %*
echo.
set /p AGAIN="Process another experiment? [y/n] "
if /i "%AGAIN%"=="y" goto MAIN

exit /b 0


:ACTIVATE
REM Try a PATH-resident conda first (works if `conda init` was run).
where conda >nul 2>&1 && call conda activate traj 2>nul && exit /b 0

REM Otherwise search the standard install paths for Scripts\activate.bat.
for %%P in (
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\anaconda3"
    "%LOCALAPPDATA%\miniconda3"
    "%LOCALAPPDATA%\anaconda3"
    "C:\ProgramData\miniconda3"
    "C:\ProgramData\anaconda3"
) do (
    if exist "%%~P\Scripts\activate.bat" (
        call "%%~P\Scripts\activate.bat" traj 2>nul && exit /b 0
    )
)
exit /b 1
