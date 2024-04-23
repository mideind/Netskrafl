#!/bin/bash
set -e

#######################################
# Run without arguments to set up the dev env:
#  - Symlink site packages to ./lib/
#  - Checks for dependencies
#  - Installs python requirements
#  - Installs node requirements
#  - Builds dawg files
#  - Generates flask secret
#  - Generates css and js
#
# Run with <setup-dev.sh> tmux to start
# the server and grunt in a tmux session

if [ "$1" == "tmux" ]; then
    tmux new-session -d 'grunt watch' \; split-window -h './runserver.sh; read -p "Press [Enter] to continue..."' \; attach
    exit 0
fi

echo "Checking initial dependencies..."
type python >/dev/null 2>&1 || { echo >&2 " - python is missing"; exit 1; }
type pip >/dev/null 2>&1 || { echo >&2 " - pip is missing"; exit 1; }
type npm >/dev/null 2>&1 || { echo >&2 " - npm (node.js) is missing"; exit 1; }
type node >/dev/null 2>&1 || { echo >&2 " - node is missing - you may need to do 'ln -s /usr/bin/nodejs /usr/bin/node'"; exit 1; }
type grunt >/dev/null 2>&1 || { echo >&2 " - grunt is missing - run 'npm install grunt -g grunt-cli'"; exit 1; }
type dev_appserver.py >/dev/null 2>&1 || { echo >&2 " - GAE for python is missing. https://cloud.google.com/appengine/downloads"; exit 1; }

python - <<EOF
import sys
if sys.version_info.major == 3 and sys.version_info.minor == 11:
    sys.exit(0)
else:
    print("Unsupported version of Python. Supported: 3.11.*")
    sys.exit(1)
EOF

echo "Symlinking site-packages to ./lib"
sitepackages=`python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())"`
ln -fs $sitepackages lib

echo "Installing python requirements in the current virtualenv..."
pip install -r requirements.txt

echo "Installing node requirements..."
npm install

if [[ -f resources/algeng.dawg.pickle && -f resources/ordalisti.dawg.pickle ]]; then
    echo "Pickle files available"
else
    echo "Some pickle files not available, running dawgbuilder..."
    python utils/dawgbuilder.py all
fi


echo "Generated resource files:"
git clean --dry-run -X resources | awk '{ print $3 }'

echo "Generate css and js"
grunt make

echo "Ready. Next steps:"
echo "------------------"
echo "Run: grunt watch"
echo "Run: runserver.sh"
echo "  or"
echo "Run: setup-dev.sh tmux"

