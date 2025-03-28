# Run gunicorn
PROJECT_ID="netskrafl" \
FLASK_APP="src/main.py" \
GOOGLE_APPLICATION_CREDENTIALS="resources/netskrafl-0dd9fbdf9ab3.json" \
GOOGLE_CLOUD_PROJECT="netskrafl" \
GOOGLE_SDK_PYTHON_LOGGING_SCOPE="google.cloud.secretmanager" \
GOOGLE_API_PYTHON_CLIENT_TIMEOUT="120" \
RUNNING_LOCAL="True" \
SERVER_PORT="3001" \
REDISHOST="127.0.0.1" \
REDISPORT="6379" \
FIREBASE_DB_URL="https://netskrafl.firebaseio.com" \
gunicorn -b :3001 -w 3 --threads 6 --keep-alive 20 --timeout 60 --log-level info --capture-output --access-logfile - --error-logfile - --pythonpath './src' src.main:app
