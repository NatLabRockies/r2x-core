@echo off
pushd "%~dp0"
if "%1" == "livehtml" (
  call npm run dev
) else (
  call npm run build
)
set docs_exit=%errorlevel%
popd
exit /b %docs_exit%
