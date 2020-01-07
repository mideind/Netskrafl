"""
    `appengine_config` gets loaded when starting a new application instance.
"""

import os.path
import pkg_resources
from google.appengine.ext import vendor

# Add `lib` subdirectory to `sys.path`, so our `main` module can load
# third-party libraries.

path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')

vendor.add(path)

# Add libraries to pkg_resources working set to find the distribution.
pkg_resources.working_set.add_entry(path)

PRODUCTION_MODE = not os.environ.get('SERVER_SOFTWARE', 'Development').startswith('Development')
if not PRODUCTION_MODE:
    import os
    import sys
    if os.name == 'nt':
        os.name = None
        sys.platform = ''
