@ECHO OFF
ECHO Deploy an update to App Server
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
"c:\program files\google\google_appengine\appcfg.py" update app.yaml skraflstats.yaml
ECHO Full deployment completed
GOTO :EOF
:DEFAULT
ECHO Default module deployment starting
"c:\program files\google\google_appengine\appcfg.py" update app.yaml
ECHO Default module deployment completed
GOTO :EOF
:INDEXES
ECHO Index update starting
"c:\program files\google\google_appengine\appcfg.py" update_indexes .
ECHO Index update completed
GOTO :EOF
:CRON
ECHO Cron update starting
"c:\program files\google\google_appengine\appcfg.py" update_cron .
ECHO Cron update completed
GOTO :EOF
:STATS
ECHO Skraflstats deployment starting
"c:\program files\google\google_appengine\appcfg.py" update skraflstats.yaml
ECHO Skraflstats deployment completed
GOTO :EOF
