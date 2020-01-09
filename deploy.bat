@ECHO OFF
ECHO Deploy an update to App Server
set GOOGLE_APPLICATION_CREDENTIALS=resources\netskrafl-0dd9fbdf9ab3.json
set PYTHONEXE=c:\python27\python
set CLOUD_SDK=%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk
set PYTHONPATH=%CLOUD_SDK%\platform\google_appengine;%cd%\lib
set APPCFG=%CLOUD_SDK%\platform\google_appengine\appcfg.py
:CHECKS
IF /i "%1" EQU "SKRAFLSTATS" GOTO STATS
IF /i "%1" EQU "STATS" GOTO STATS
IF /i "%1" EQU "S" GOTO STATS
IF /i "%1" EQU "INDEXES" GOTO INDEXES
IF /i "%1" EQU "IX" GOTO INDEXES
IF /i "%1" EQU "I" GOTO INDEXES
IF /i "%1" EQU "CRON" GOTO CRON
IF /i "%1" EQU "C" GOTO CRON
IF /i "%1" EQU "DEFAULT" GOTO DEFAULT
IF /i "%1" EQU "D" GOTO DEFAULT
ECHO Full deployment (app + skraflstats) starting
cmd.exe /c "grunt make"
rem %PYTHONEXE% %APPCFG% update app.yaml skraflstats.yaml --noauth_local_webserver
ECHO Full deployment completed
GOTO :EOF
:DEFAULT
ECHO Default module deployment (app) starting
cmd.exe /c "grunt make"
%PYTHONEXE% "%APPCFG%" update app.yaml --noauth_local_webserver
ECHO Default module deployment completed
GOTO :EOF
:INDEXES
ECHO Index update starting
%PYTHONEXE% "%APPCFG%" update_indexes . --noauth_local_webserver
ECHO Index update completed
GOTO :EOF
:CRON
ECHO Cron update starting
%PYTHONEXE% "%APPCFG%" update_cron . --noauth_local_webserver
ECHO Cron update completed
GOTO :EOF
:STATS
ECHO Skraflstats deployment starting
rem %PYTHONEXE% %APPCFG% update skraflstats.yaml --noauth_local_webserver
ECHO Skraflstats deployment completed
GOTO :EOF
:EOF
