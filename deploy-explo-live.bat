@ECHO OFF
ECHO Deploy an update to Explo Development App Server
ECHO *** Run me from the Google Cloud SDK Shell! ***
set GOOGLE_APPLICATION_CREDENTIALS="resources\explo-live-0d431e5fcf4a.json"
:CHECKS
IF /i "%1" EQU "SKRAFLSTATS" GOTO STATS
IF /i "%1" EQU "STATS" GOTO STATS
IF /i "%1" EQU "S" GOTO STATS
IF /i "%1" EQU "INDEXES" GOTO INDEXES
IF /i "%1" EQU "INDEX" GOTO INDEXES
IF /i "%1" EQU "IX" GOTO INDEXES
IF /i "%1" EQU "I" GOTO INDEXES
IF /i "%1" EQU "CRON" GOTO CRON
IF /i "%1" EQU "C" GOTO CRON
IF /i "%1" EQU "DEFAULT" GOTO DEFAULT
IF /i "%1" EQU "D" GOTO DEFAULT
ECHO Full deployment (app + skraflstats) starting
cmd.exe /c "npx grunt make"
ECHO *** Currently disabled ***
ECHO Full deployment completed
GOTO :EOF
:DEFAULT
IF "%2" EQU "" GOTO NOVERSION
ECHO Default module deployment starting, version '%2'
cmd.exe /c "npx grunt make"
gcloud beta app deploy --version=%2 --no-promote --project=explo-live app-explo-live.yaml
ECHO Default module deployment completed
GOTO :EOF
:NOVERSION
ECHO Version is missing; enter deploy D[EFAULT] version
GOTO :EOF
:INDEXES
ECHO Index update starting
gcloud beta app deploy --project=explo-live index.yaml
gcloud datastore indexes cleanup index.yaml
ECHO Index update completed
GOTO :EOF
:CRON
ECHO Cron update starting
gcloud beta app deploy --project=explo-live cron.yaml
ECHO Cron update completed
GOTO :EOF
:STATS
ECHO Skraflstats deployment starting
ECHO *** Currently disabled ***
ECHO Skraflstats deployment completed
GOTO :EOF
:EOF
