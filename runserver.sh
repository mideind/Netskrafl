#!/bin/bash

export GOOGLE_APPLICATION_CREDENTIALS=./credentials/explo-dev/service-account.json
export PROJECT_ID=explo-dev
export SERVER_SOFTWARE=Development
export OAUTHLIB_INSECURE_TRANSPORT=1
export SERVER_HOST=0.0.0.0
export SERVER_PORT=3000
export REDISHOST=127.0.0.1
export REDISPORT=6379

python3 ./src/main.py

