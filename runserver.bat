REM Start the Google App Engine Development Server for Python
set GOOGLE_APPLICATION_CREDENTIALS=resources\netskrafl-0dd9fbdf9ab3.json
set PYTHON=C:\python27\python
set CLOUD_SDK=%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk
set APPSERVER=%CLOUD_SDK%\bin\dev_appserver.py
set PYTHONIOENCODING=utf-8
%PYTHON% "%APPSERVER%" --port=8080 --admin_port=8000 --host=0.0.0.0 ^
   --enable_host_checking=False --enable_console=True app.yaml skraflstats.yaml
