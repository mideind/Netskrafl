REM Start the Google App Engine Development Server for Python
set GOOGLE_APPLICATION_CREDENTIALS=resources\netskrafl-0dd9fbdf9ab3.json
python dev_appserver.py --port=8080 --admin_port=8000 --host=0.0.0.0 --enable_host_checking=False app.yaml skraflstats.yaml
