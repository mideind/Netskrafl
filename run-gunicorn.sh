# Run gunicorn
PROJECT_ID="netskrafl" \
GOOGLE_APPLICATION_CREDENTIALS="resources/netskrafl-0dd9fbdf9ab3.json" \
GOOGLE_CLOUD_PROJECT="netskrafl" \
GOOGLE_API_PYTHON_CLIENT_TIMEOUT="120" \
RUNNING_LOCAL="True" \
SERVER_PORT="3001" \
REDISHOST="127.0.0.1" \
REDISPORT="6379" \
FIREBASE_DB_URL="https://netskrafl.firebaseio.com" \
gunicorn -b :3001 -w 3 --threads=6 --worker-class=gthread --keep-alive=20 --timeout=60 --log-level=info --access-logfile=- --error-logfile=- --pythonpath='./src' main:app
