#!/usr/bin/env python
from __future__ import print_function
import os
import sys


file_path = "resources/secret_key.bin"


# noinspection Restricted_Python_calls
def generate():
    print("Generating session token, using os.urandom")
    random_bytes = os.urandom(64)
    with open(file_path, "wb") as f:
        f.write(random_bytes)


def read():
    print("Contents of {}".format(file_path))
    with open(file_path, "rb") as f:
        random_bytes = f.read()
        print(random_bytes.decode('base64'))


if len(sys.argv) > 1 and sys.argv[1] == "read":
    read()
else:
    generate()

