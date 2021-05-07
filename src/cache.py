# -*- coding: utf-8 -*-

"""

    Cache - Redis cache wrapper for the Netskrafl application

    Copyright (C) 2020 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    This module wraps Redis caching in a thin wrapper object,
    roughly emulating memcache.

    This module is necessitated by the move from the Standard environment
    (Python 2 based) to the Flexible environment (Python 3 based) of the
    Google App Engine. The Flexible environment no longer supports the
    memcache module which was integral to the Standard environment. Thus,
    a move to Memorystore/Redis was needed.

    Since Redis only supports numeric and string value types, we need to
    employ some shenanigans to JSON-encode and decode composite Python objects.

"""

import os
import redis
import json
import importlib
import logging
from datetime import datetime


# A cache of imported modules, used to create fresh instances
# when de-serializing JSON objects
_modules = dict()

# Custom serializers
_serializers = {
    ("datetime", "datetime"): (
        lambda dt: (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second),
        lambda args: datetime(*args)
    )
}


def serialize(obj):
    """ Return a JSON-serializable representation of an object """
    cls = obj.__class__
    cls_name = cls.__name__
    module_name = cls.__module__
    serializer = None
    if hasattr(obj, "to_serializable"):
        # The object implements its own serialization
        s = obj.to_serializable()
    elif hasattr(obj, "__dict__"):
        # Use the object's __dict__ if it's there
        s = obj.__dict__
    else:
        # Use a custom serializer
        serializer = _serializers.get((module_name, cls_name))
        # If we don't have one, that's a problem
        assert serializer is not None
        # Apply the serializer to the object
        s = serializer[0](obj)
    # Do some sanity checks: we must be able to recreate
    # an instance of this class during de-serialization
    assert module_name and module_name != "__main__"
    assert serializer is not None or hasattr(cls, "from_serializable")
    # Return a serialization wrapper dict with enough info
    # for deserialization
    return dict(
        __cls__=cls_name,
        __module__=module_name,
        __obj__=s
    )


def _dumps(obj):
    """ Returns the given object in JSON format, using the custom serializer
        for composite objects """
    return json.dumps(
        obj,
        default=serialize, ensure_ascii=False, separators=(',', ':')
    )


def _loads(j):
    """ Return an instance of a serializable class,
        initialized from a JSON string """
    if j is None:
        return None
    d = json.loads(j)
    if not isinstance(d, dict):
        # This is a primitive object (number, string, list)
        return d
    cls_name = d.get("__cls__")
    if cls_name is None:
        # This is not a custom-serialized instance:
        # return it as-is, i.e. as a plain dict
        return d
    # Obtain the module containing the object's class
    module_name = d["__module__"]
    # Check whether we have a custom serializer for this (module, class) combo
    serializer = _serializers.get((module_name, cls_name))
    if serializer is not None:
        # Yes, we do: apply it to recreate the object
        return serializer[1](d["__obj__"])
    # No custom serializer: we should have a from_serializable() class method
    m = _modules.get(module_name)
    if m is None:
        # Not already imported: do it now
        m = _modules[module_name] = importlib.import_module(module_name)
        assert m is not None, "Unable to import module {0}".format(module_name)
    # Find the class within the module
    cls = getattr(m, cls_name)
    assert cls is not None, (
        "Unable to find class {0} in module {1}".format(cls_name, module_name)
    )
    # ...and create the instance by calling from_serializable() on the class
    return cls.from_serializable(d["__obj__"])


class RedisWrapper:

    """ Wrapper class around the Redis client,
        making it appear as a simplified memcache instance """

    def __init__(self, redis_host=None, redis_port=None):
        redis_host = redis_host or os.environ.get('REDISHOST', 'localhost')
        redis_port = redis_port or int(os.environ.get('REDISPORT', 6379))
        # Create a Redis client instance
        self._client = redis.Redis(
            host=redis_host, port=redis_port, retry_on_timeout=True
        )

    def get_redis_client(self):
        """ Return the underlying Redis client instance """
        return self._client

    def _call_with_retry(self, func, errval, *args, **kwargs):
        """ Call a client function, attempting one retry
            upon a connection error """
        attempts = 0
        while attempts < 2:
            try:
                ret = func(*args, **kwargs)
                # No error: return
                return ret
            except redis.client.ConnectionError:
                if attempts == 0:
                    logging.warning(
                        "Retrying Redis call after connection error")
                else:
                    logging.error(
                        "Redis connection error persisted after retrying")
                attempts += 1
        return errval

    def add(self, key, value, time=None, namespace=None):
        """ Add a value to the cache, under the given key
            and within the given namespace, with an optional
            expiry time in seconds """
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return self._call_with_retry(self._client.set, None, key, _dumps(value), ex=time)

    def set(self, key, value, time=None, namespace=None):
        """ Set a value in the cache, under the given key
            and within the given namespace, with an optional
            expiry time in seconds. This is an alias for self.add(). """
        return self.add(key, value, time, namespace)

    def get(self, key, namespace=None):
        """ Fetch a value from the cache, under the given key and within
            the given namespace. Returns None if the key is not found. """
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return _loads(self._call_with_retry(self._client.get, None, key))

    def delete(self, key, namespace=None):
        """ Delete a value from the cache """
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return self._call_with_retry(self._client.delete, False, key)


# Create a global singleton wrapper instance with default parameters,
# emulating a part of the memcache API.

# If we're running on the local
# development server (GAE emulator), connect to a local Redis server.
if os.environ.get('SERVER_SOFTWARE', '').startswith('Development'):
    memcache = RedisWrapper(redis_host="127.0.0.1")
else:
    memcache = RedisWrapper()
