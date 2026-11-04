@echo off
rem Started by the "FaceAttendance" scheduled task at boot. Restarts the service if it exits.
cd /d "%~dp0.."
if not exist data mkdir data
if not defined LOG_FILE set LOG_FILE=data\attendance.log
:loop
".venv\Scripts\python.exe" -m attendance.main > data\last-exit.log 2>&1
rem "timeout" needs a console, which a SYSTEM task does not have
ping -n 11 127.0.0.1 >nul
goto loop
