"""

    Cache - Redis cache wrapper for the Netskrafl application

    Copyright © 2025 Miðeind ehf.
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

from __future__ import annotations

from typing import Dict, Any, Callable, List, Mapping, Optional, Tuple, Union
from types import ModuleType
from collections.abc import Collection

import os
import json
import importlib
import logging
from datetime import UTC, datetime

import redis


# A cache of imported modules, used to create fresh instances
# when de-serializing JSON objects
_modules: Dict[str, ModuleType] = dict()

# Custom serializers

DateTimeTuple = Tuple[int, int, int, int, int, int]
SerializerFunc = Callable[..., Any]
SerializerFuncTuple = Tuple[SerializerFunc, SerializerFunc]


def _serialize_dt(dt: datetime) -> DateTimeTuple:
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def _deserialize_dt(args: DateTimeTuple) -> datetime:
    return datetime(*args, tzinfo=UTC)


_serializers: Mapping[Tuple[str, str], SerializerFuncTuple] = {
    ("datetime", "datetime"): (
        _serialize_dt,
        _deserialize_dt,
    ),
    # Apparently we sometimes get this derived class from the Google
    # datastore instead of datetime.datetime, so we need an entry for
    # it. Replacing it with plain datetime.datetime is fine, btw.
    ("proto.datetime_helpers", "DatetimeWithNanoseconds"): (
        _serialize_dt,
        _deserialize_dt,
    ),
}


def serialize(obj: Any) -> Dict[str, Any]:
    """Return a JSON-serializable representation of an object"""
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
        assert serializer is not None, f"No serializer for {module_name}.{cls_name}"
        # Apply the serializer to the object
        s = serializer[0](obj)
    # Do some sanity checks: we must be able to recreate
    # an instance of this class during de-serialization
    assert module_name and module_name != "__main__"
    assert serializer is not None or hasattr(cls, "from_serializable")
    # Return a serialization wrapper dict with enough info
    # for deserialization
    return dict(__cls__=cls_name, __module__=module_name, __obj__=s)


def _dumps(obj: Any) -> str:
    """Returns the given object in JSON format, using the custom serializer
    for composite objects"""
    return json.dumps(obj, default=serialize, ensure_ascii=False, separators=(",", ":"))


def _loads(j: Optional[str]) -> Any:
    """Return an instance of a serializable class,
    initialized from a JSON string"""
    if j is None:
        return None
    d: Union[int, str, List[Any], Dict[str, Any]] = json.loads(j)
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
    assert cls is not None, "Unable to find class {0} in module {1}".format(
        cls_name, module_name
    )
    # ...and create the instance by calling from_serializable() on the class
    return cls.from_serializable(d["__obj__"])


class RedisWrapper:
    """Wrapper class around the Redis client,
    making it appear as a simplified memcache instance"""

    def __init__(
        self, redis_host: Optional[str] = None, redis_port: Optional[int] = None
    ) -> None:
        redis_host = redis_host or os.environ.get("REDISHOST", "localhost")
        redis_port = redis_port or int(os.environ.get("REDISPORT", 6379))
        assert redis_host is not None
        # Create a Redis client instance
        self._client = redis.Redis(
            host=redis_host, port=redis_port, retry_on_timeout=True
        )

    def get_redis_client(self) -> redis.Redis[bytes]:
        """Return the underlying Redis client instance"""
        return self._client

    def _call_with_retry(
        self, func: Callable[..., Any], errval: Any, *args: Any, **kwargs: Any
    ) -> Any:
        """Call a client function, attempting one retry
        upon a connection error"""
        attempts = 0
        while attempts < 2:
            try:
                ret = func(*args, **kwargs)
                # No error: return
                return ret
            except (
                redis.exceptions.ConnectionError,
                redis.exceptions.TimeoutError,
                redis.exceptions.TryAgainError,
            ) as e:
                if attempts == 0:
                    logging.warning(f"Retrying Redis call after {repr(e)}")
                else:
                    logging.error(f"Redis error {repr(e)} persisted after retrying")
                attempts += 1
        return errval

    def add(
        self,
        key: str,
        value: Any,
        time: Optional[int] = None,
        namespace: Optional[str] = None,
    ) -> Any:
        """Add a value to the cache, under the given key
        and within the given namespace, with an optional
        expiry time in seconds"""
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return self._call_with_retry(
            self._client.set, None, key, _dumps(value), ex=time
        )

    set = add  # Alias for add()

    def mset(
        self,
        mapping: Mapping[str, str],
        time: Optional[int] = None,
        namespace: Optional[str] = None,
    ) -> Any:
        """Add multiple key-value pairs to the cache, within the given namespace,
        with an optional expiry time in seconds"""
        keyfunc: Callable[[str], str]
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            keyfunc = lambda k: namespace + "|" + k
        else:
            keyfunc = lambda k: k
        mapping = {keyfunc(k): _dumps(v) for k, v in mapping.items()}
        return self._call_with_retry(self._client.mset, None, mapping, ex=time)

    def get(self, key: str, namespace: Optional[str] = None) -> Any:
        """Fetch a value from the cache, under the given key and within
        the given namespace. Returns None if the key is not found."""
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return _loads(self._call_with_retry(self._client.get, None, key))

    def mget(self, keys: List[str], namespace: Optional[str] = None) -> Any:
        """Fetch multiple values from the cache, within the given namespace.
        Returns a list of values, with None for keys that are not found."""
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            keys = [namespace + "|" + k for k in keys]
        return [_loads(v) for v in self._call_with_retry(self._client.mget, [], keys)]

    def delete(self, key: str, namespace: Optional[str] = None) -> Any:
        """Delete a value from the cache"""
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        return self._call_with_retry(self._client.delete, False, key)

    def flush(self) -> None:
        """Flush all keys from the current cache"""
        return self._call_with_retry(self._client.flushdb, None)

    def init_set(
        self,
        key: str,
        elements: Collection[str],
        *,
        time: Optional[int] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Initialize a fresh set with the given elements, optionally
        with an expiry time in seconds"""
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        try:
            # Start a pipeline (transaction is implicit with MULTI/EXEC)
            pipe = self._client.pipeline()
            # Delete the set (if it exists)
            pipe.delete(key)
            # Add users to the set
            if elements:
                pipe.sadd(key, *elements)
                # Set an expiration time of 2 minutes (120 seconds) on the set
                if time:
                    pipe.expire(key, time)
            # Execute the pipeline (transaction)
            return self._call_with_retry(pipe.execute, None) != None
        except redis.exceptions.RedisError as e:
            logging.error(f"Redis error in init_set(): {repr(e)}")
        return False

    def query_set(
        self,
        key: str,
        elements: List[str],
        *,
        namespace: Optional[str] = None,
    ) -> List[bool]:
        """Check for multiple elements in a set using the SMISMEMBER
        command, returning a list of booleans"""
        if not elements:
            return []
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        result: Optional[List[int]] = self._call_with_retry(
            self._client.smismember, None, key, elements  # type: ignore
        )
        if result is None:
            # The key is not found: no elements are present in the set
            return [False] * len(elements)
        return [bool(r) for r in result]

    def random_sample_from_set(
        self, key: str, count: int, *, namespace: Optional[str] = None
    ) -> List[str]:
        """Return a random sample of elements from the set"""
        if namespace:
            # Redis doesn't have namespaces, so we prepend the namespace id to the key
            key = namespace + "|" + key
        result = self._call_with_retry(self._client.srandmember, [], key, count)
        # The returned list contains bytes, which we need to convert to strings
        return [str(u, "utf-8") for u in result]


# Create a global singleton wrapper instance with default parameters,
# emulating a part of the memcache API.

# If we're running on a local development server, connect to a
# local Redis server (which may of course be tunneled through SSH,
# via ssh -fNL 6379:localhost:6379 user@my.redis.host)
if os.environ.get("SERVER_SOFTWARE", "").startswith("Development"):
    memcache = RedisWrapper(redis_host="127.0.0.1")
else:
    memcache = RedisWrapper()
