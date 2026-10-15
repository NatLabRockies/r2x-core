@echo off
setlocal
pushd "%~dp0"
if "%~1" == "" goto help
if /i "%~1" == "help" goto help
if /i "%~1" == "html" goto html
if /i "%~1" == "livehtml" goto livehtml
echo Unknown documentation target: %~1
set docs_exit=1
goto done
:help
echo make html: build Astro/Starlight; make livehtml: start the development server
set docs_exit=0
goto done
:html
call npm run build
set docs_exit=%errorlevel%
goto done
:livehtml
call npm run dev
set docs_exit=%errorlevel%
:done
popd
exit /b %docs_exit%
