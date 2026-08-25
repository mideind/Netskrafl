"""Decode spike: REST runQuery JSON -> Entity proto -> ndb model instance,
field-compared against ground truth fetched via the normal ndb client.

Read-only against the netskrafl production Datastore.
"""

from __future__ import annotations


from typing import Any, Dict, List, Tuple

import sys
import requests
from google.auth.transport.requests import Request
from google.cloud import ndb
from google.cloud.datastore_v1.types import entity as entity_types
from google.cloud.ndb import model as ndb_model
from google.oauth2 import service_account
from google.protobuf import json_format

import skrafldb_ndb  # noqa: F401  -- registers all NDB model kinds

PROJECT = "netskrafl"
CREDS_PATH = "credentials/netskrafl/service-account.json"
URL = f"https://datastore.googleapis.com/v1/projects/{PROJECT}:runQuery"

creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH, scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
creds.refresh(Request())
HDRS = {"Authorization": f"Bearer {creds.token}"}
sess = requests.Session()


def rest_query(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    r = sess.post(URL, json={"query": query}, headers=HDRS, timeout=120)
    r.raise_for_status()
    return r.json()["batch"].get("entityResults", [])


def decode(entity_json: Dict[str, Any]) -> Any:
    """REST JSON entity -> datastore_v1 Entity proto -> ndb model instance."""
    pb = entity_types.Entity.pb(entity_types.Entity())
    json_format.ParseDict(entity_json, pb)
    wrapped = entity_types.Entity.wrap(pb)
    return ndb_model._entity_from_protobuf(wrapped)


def compare(a: Any, b: Any) -> List[str]:
    """Per-property comparison of two ndb model instances."""
    diffs: List[str] = []
    if type(a) is not type(b):
        return [f"type mismatch: {type(a)} vs {type(b)}"]
    if a._key != b._key:
        diffs.append(f"key: {a._key} vs {b._key}")
    names = sorted(set(a._properties.keys()) | set(b._properties.keys()))
    for name in names:
        prop = a._properties.get(name) or b._properties.get(name)
        code_name = prop._code_name or name
        va = getattr(a, code_name, None)
        vb = getattr(b, code_name, None)
        if va != vb:
            diffs.append(f"{name}: {va!r} != {vb!r}")
    return diffs


# ---- Sample selection -------------------------------------------------------

samples: List[Tuple[str, Dict[str, Any]]] = []  # (label, entity_json)

def add(label: str, kind: str, query: Dict[str, Any]) -> None:
    query["kind"] = [{"name": kind}]
    for er in rest_query(query):
        samples.append((label, er["entity"]))

add("game-oldest", "GameModel",
    {"order": [{"property": {"name": "timestamp"}, "direction": "ASCENDING"}], "limit": 4})
add("game-newest", "GameModel",
    {"order": [{"property": {"name": "timestamp"}, "direction": "DESCENDING"}], "limit": 4})
add("game-mid", "GameModel", {"limit": 4})  # key order, effectively random UUIDs
add("user-oldest", "UserModel",
    {"order": [{"property": {"name": "timestamp"}, "direction": "ASCENDING"}], "limit": 3})
add("user-newest", "UserModel",
    {"order": [{"property": {"name": "timestamp"}, "direction": "DESCENDING"}], "limit": 3})
add("chat", "ChatModel", {"limit": 3})
add("stats", "StatsModel", {"limit": 3})
add("elo", "EloModel", {"limit": 2})
add("challenge", "ChallengeModel", {"limit": 2})

print(f"collected {len(samples)} sample entities\n")

# ---- Decode via REST path, fetch ground truth via ndb client ----------------

client = ndb.Client(project=PROJECT, credentials=creds)
failures = 0
with client.context() as ctx:
    for label, ejson in samples:
        try:
            m = decode(ejson)
        except Exception as e:
            print(f"FAIL  {label:<12} decode error: {e!r}")
            failures += 1
            continue
        key = m._key
        truth = key.get(use_cache=False, use_global_cache=False)
        if truth is None:
            print(f"FAIL  {label:<12} {key} ground-truth fetch returned None")
            failures += 1
            continue
        diffs = compare(m, truth)
        extra = ""
        if m._get_kind() == "GameModel":
            ts = getattr(m, "timestamp", None)
            extra = f" ts={ts:%Y-%m-%d} moves={len(m.moves)} robot={m.robot_level > 0 or not m.player1}"
        if diffs:
            failures += 1
            print(f"FAIL  {label:<12} {key.id()}{extra}")
            for d in diffs[:6]:
                print(f"      - {d}")
        else:
            eq = "==" if m == truth else "!= (Model.__eq__ disagrees)"
            print(f"ok    {label:<12} {str(key.id())[:36]:<36}{extra}  [{eq}]")

print(f"\n{len(samples)} samples, {failures} failures")
sys.exit(1 if failures else 0)

