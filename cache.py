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


# A cache of imported modules, used to create fresh instances
# when de-serializing JSON objects
_modules = dict()


def serialize(obj):
    """ Return a JSON-serializable representation of an object """
    if hasattr(obj, "to_serializable"):
        # Custom serialization
        s = obj.to_serializable()
    else:
        # By default, use the object's __dict__
        s = obj.__dict__
    # TODO: Eventually, special cases for common primitive
    # types such as timestamps may be added here
    cls = obj.__class__
    # Do some sanity checks: we must be able to recreate
    # an instance of this class during de-serialization
    assert cls.__module__ and cls.__module__ != "__main__"
    assert hasattr(cls, "from_serializable")
    # Return a serialization wrapper dict with enough info
    # for deserialization
    return dict(
        __cls__=cls.__name__,
        __module__=cls.__module__,
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
    """ Return an instance of a serializable class, initialized from a JSON string """
    if j is None:
        return None
    d = json.loads(j)
    if not isinstance(d, dict):
        # This is a primitive object (number, string)
        return d
    cls_name = d.get("__cls__")
    if cls_name is None:
        # This is not a custom-serialized instance: return it as-is
        return d
    # Obtain the module containing the object's class
    module_name = d["__module__"]
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
        self._client = redis.Redis(host=redis_host, port=redis_port)

    def get_redis_client(self):
        """ Return the underlying Redis client instance """
        return self._client

    def add(self, key, value, time=None, namespace=None):
        """ Add a value to the cache, under the given key
            and within the given namespace, with an optional
            expiry time in seconds """
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return self._client.set(key, _dumps(value), ex=time)

    def set(self, key, value, time=None, namespace=None):
        """ Set a value in the cache, under the given key
            and within the given namespace, with an optional
            expiry time in seconds """
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return self._client.set(key, _dumps(value), ex=time)

    def get(self, key, namespace=None):
        """ Fetch a value from the cache, under the given key and within
            the given namespace. Returns None if the key is not found. """
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return _loads(self._client.get(key))


# Create a global singleton wrapper instance with default parameters,
# emulating a part of the memcache API.

# If we're running on the local
# development server (GAE emulator), connect to a local Redis server.
if os.environ.get('SERVER_SOFTWARE', '').startswith('Development'):
    memcache = RedisWrapper(redis_host="localhost")
else:
    memcache = RedisWrapper()
