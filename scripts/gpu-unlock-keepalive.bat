@echo off
rem Auto-started at Windows logon: grabs the dGPU with a CUDA context as early as
rem possible (keeps it awake so an EFI-applied unlock is not lost to RTD3 power-down)
rem and shows the live FP16 tensor rate (~57-73 = unlock held; ~28-39 = reset; scales with SM clock).
rem To remove this autostart: delete this file.
title GPU unlock keep-alive / monitor  (close to stop)
py -3 -P "%~dp0gpu_keepalive_light.py"
echo.
echo Monitor stopped. Press any key to close.
pause >nul
