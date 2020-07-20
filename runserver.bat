
REM Start the Netskrafl server on a local development machine

REM Prepare the environment
set GOOGLE_APPLICATION_CREDENTIALS=resources\netskrafl-0dd9fbdf9ab3.json
set PROJECT_ID=netskrafl
set REDISHOST=10.128.0.3
set REDISPORT=6379
set CLIENT_ID=62474854399-j186rtbl9hbh6c6o21or405o6clbcj84.apps.googleusercontent.com
set FIREBASE_API_KEY=AIzaSyBAhoxuIMvvsDepArFbW9YF9F4eduCuWB8
set FIREBASE_SENDER_ID=62474854399
set SERVER_SOFTWARE=Development
set DATASTORE_EMULATOR_HOST=localhost:8081

REM Start the main server
python netskrafl.py
