"""

    Tests for Netskrafl / Explo Word Game
    Copyright (C) 2024 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

from datetime import datetime, timedelta

from utils import CustomClient, login_user
from utils import client, u1, u2, u3_gb  # type: ignore


def test_elo_history(client: CustomClient, u1: str) -> None:
    resp = login_user(client, 1)

    # Insert some stats
    from skrafldb import StatsModel, Client

    with Client.get_context():
        StatsModel.delete_user(u1)

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0

    assert "elo_30_days" in resp.json
    assert len(resp.json["elo_30_days"]) == 30
    now = datetime.utcnow()
    now = datetime(year=now.year, month=now.month, day=now.day)

    for ix, sm in enumerate(resp.json["elo_30_days"]):
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1200
        assert sm["human_elo"] == 1200
        assert sm["manual_elo"] == 1200

    with Client.get_context():

        sm = StatsModel.create(u1)
        sm.timestamp = now - timedelta(days=35)
        sm.elo = 1210
        sm.human_elo = 1220
        sm.manual_elo = 1230
        sm.put()
        sm = StatsModel.create(u1)
        sm.timestamp = now - timedelta(days=15)
        sm.elo = 1240
        sm.human_elo = 1250
        sm.manual_elo = 1260
        sm.put()
        sm = StatsModel.create(u1)
        sm.timestamp = now - timedelta(days=5)
        sm.elo = 1270
        sm.human_elo = 1280
        sm.manual_elo = 1290
        sm.put()

    resp = client.post("/userstats", data=dict(user=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "result" in resp.json
    assert resp.json["result"] == 0

    assert "elo_30_days" in resp.json
    slist = resp.json["elo_30_days"]
    assert len(slist) == 30

    for ix in reversed(range(16, 30)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1210
        assert sm["human_elo"] == 1220
        assert sm["manual_elo"] == 1230

    for ix in reversed(range(6, 16)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1240
        assert sm["human_elo"] == 1250
        assert sm["manual_elo"] == 1260

    for ix in reversed(range(0, 6)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"])
        assert (now - ts).days == ix
        assert sm["elo"] == 1270
        assert sm["human_elo"] == 1280
        assert sm["manual_elo"] == 1290

    resp = client.post("/logout")
    assert resp.status_code == 200
