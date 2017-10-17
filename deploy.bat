@ECHO OFF
ECHO Deploy an update to App Server
IF EXIST "c:\program files (x86)\google\google_appengine\appcfg.py" GOTO :X86
SET APPCFG="c:\program files\google\google_appengine\appcfg.py"
GOTO :CHECKS
:X86
SET APPCFG="c:\program files (x86)\google\google_appengine\appcfg.py"
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
ECHO Full deployment starting
grunt make
%APPCFG% update app.yaml skraflstats.yaml --noauth_local_webserver
ECHO Full deployment completed
GOTO :EOF
:DEFAULT
ECHO Default module deployment starting
grunt make
%APPCFG% update app.yaml --noauth_local_webserver
ECHO Default module deployment completed
GOTO :EOF
:INDEXES
ECHO Index update starting
%APPCFG% update_indexes . --noauth_local_webserver
ECHO Index update completed
GOTO :EOF
:CRON
ECHO Cron update starting
%APPCFG% update_cron . --noauth_local_webserver
ECHO Cron update completed
GOTO :EOF
:STATS
ECHO Skraflstats deployment starting
%APPCFG% update skraflstats.yaml --noauth_local_webserver
ECHO Skraflstats deployment completed
GOTO :EOF
