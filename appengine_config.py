"""`appengine_config` gets loaded when starting a new application instance."""
import os.path

# add `lib` subdirectory to `sys.path`, so our `main` module can load
# third-party libraries.
from google.appengine.ext import vendor
vendor.add(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib'))

PRODUCTION_MODE = not os.environ.get('SERVER_SOFTWARE', 'Development').startswith('Development')
if not PRODUCTION_MODE:
    import os
    import sys
    if os.name == 'nt':
        os.name = None
        sys.platform = ''
