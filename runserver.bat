SET GOOGLE_APPLICATION_CREDENTIALS=c:\users\Lenovo\documents\github\netskrafl\resources\netskrafl-0dd9fbdf9ab3.json
IF EXIST "C:\Program Files (x86)\Google\google_appengine\dev_appserver.py" GOTO X86
C:\Python27\python.exe "C:\Program Files\Google\google_appengine\dev_appserver.py" --port=8080 --admin_port=8000 --host=0.0.0.0 app.yaml skraflstats.yaml
GOTO END
:X86
C:\Python27\python.exe "C:\Program Files (x86)\Google\google_appengine\dev_appserver.py" --port=8080 --admin_port=8000 --host=0.0.0.0 app.yaml skraflstats.yaml
:END
