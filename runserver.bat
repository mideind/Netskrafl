REM Start the Google App Engine Development Server for Python
set GOOGLE_APPLICATION_CREDENTIALS=resources\netskrafl-0dd9fbdf9ab3.json
set APPSERVER="\program files (x86)\google\google_appengine\dev_appserver.py"
set PYTHONEXE=\python27\python
set PYTHONIOENCODING=utf-8
%PYTHONEXE% %APPSERVER% --port=8080 --admin_port=8000 --host=0.0.0.0 --enable_host_checking=False app.yaml skraflstats.yaml
