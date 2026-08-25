"""Decode spike, part 2: truly-recent games (via indexed ts_last_move) and
a count of GameModel entities with ts_last_move == null."""

from __future__ import annotations


from typing import Any, Dict

import sys
import requests
from google.auth.transport.requests import Request
from google.cloud import ndb
from google.cloud.datastore_v1.types import entity as entity_types
from google.cloud.ndb import model as ndb_model
from google.oauth2 import service_account
from google.protobuf import json_format

import skrafldb_ndb  # noqa: F401

PROJECT = "netskrafl"
CREDS_PATH = "credentials/netskrafl/service-account.json"
BASE = f"https://datastore.googleapis.com/v1/projects/{PROJECT}"

creds = service_account.Credentials.from_service_account_file(
    CREDS_PATH, scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
creds.refresh(Request())
HDRS = {"Authorization": f"Bearer {creds.token}"}
sess = requests.Session()


def decode(entity_json: Dict[str, Any]) -> Any:
    pb = entity_types.Entity.pb(entity_types.Entity())
    json_format.ParseDict(entity_json, pb)
    return ndb_model._entity_from_protobuf(entity_types.Entity.wrap(pb))


# --- recent games by ts_last_move (indexed), decode + ground-truth compare ---
q = {"kind": [{"name": "GameModel"}], "limit": 4,
     "order": [{"property": {"name": "ts_last_move"}, "direction": "DESCENDING"}]}
r = sess.post(f"{BASE}:runQuery", json={"query": q}, headers=HDRS, timeout=60)
r.raise_for_status()
results = r.json()["batch"]["entityResults"]

failures = 0
client = ndb.Client(project=PROJECT, credentials=creds)
with client.context():
    for er in results:
        m = decode(er["entity"])
        truth = m._key.get(use_cache=False, use_global_cache=False)
        same = (m == truth)
        print(f"{'ok  ' if same else 'FAIL'} game {m._key.id()} "
              f"ts_last_move={m.ts_last_move:%Y-%m-%d %H:%M} moves={len(m.moves)}")
        if not same:
            failures += 1

# --- count of games with ts_last_move == null --------------------------------
aq = {"aggregationQuery": {
    "nestedQuery": {
        "kind": [{"name": "GameModel"}],
        "filter": {"propertyFilter": {
            "property": {"name": "ts_last_move"}, "op": "EQUAL",
            "value": {"nullValue": None}}}},
    "aggregations": [{"count": {}}]}}
r = sess.post(f"{BASE}:runAggregationQuery", json=aq, headers=HDRS, timeout=60)
r.raise_for_status()
batch = r.json()["batch"]
cnt = batch["aggregationResults"][0]["aggregateProperties"]["property_1"]["integerValue"]
print(f"\nGameModel entities with ts_last_move == null: {cnt}")
sys.exit(1 if failures else 0)

