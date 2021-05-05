#!/bin/bash
export GOOGLE_APPLICATION_CREDENTIALS=resources/netskrafl-0dd9fbdf9ab3.json
export PROJECT_ID=netskrafl
export REDISHOST=127.0.0.1
export REDISPORT=6379
export CLIENT_ID=62474854399-j186rtbl9hbh6c6o21or405o6clbcj84.apps.googleusercontent.com
export CLIENT_SECRET=fYrSNk7MwNYDqH3U8YCFUEac
export FIREBASE_API_KEY=AIzaSyBAhoxuIMvvsDepArFbW9YF9F4eduCuWB8
export FIREBASE_SENDER_ID=62474854399
export SERVER_SOFTWARE=Development
export SERVER_HOST=0.0.0.0
export PYTHONUNBUFFERED=TRUE
# export DATASTORE_EMULATOR_HOST=localhost:8081
export OAUTHLIB_INSECURE_TRANSPORT=1
python netskrafl.py

