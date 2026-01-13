"""

    Tests for Netskrafl / Explo Word Game
    Copyright © 2025 Miðeind ehf.

    This module tests several APIs by submitting HTTP requests
    to the Netskrafl / Explo server.

"""

from typing import Dict

from collections import defaultdict
from datetime import UTC, datetime, timedelta
import functools

from utils import CustomClient, login_user
from utils import client, client1, client2, u1, u2, u3_gb  # type: ignore  # noqa: F401

from skraflgame import ClientStateDict

# The K constant used in the Elo calculation
ELO_K: float = 20.0  # For established players
BEGINNER_K: float = 32.0  # For beginning players


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
    now = datetime.now(UTC)
    now = datetime(year=now.year, month=now.month, day=now.day, tzinfo=UTC)

    for ix, sm in enumerate(resp.json["elo_30_days"]):
        ts = datetime.fromisoformat(sm["ts"]).replace(tzinfo=UTC)
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
        ts = datetime.fromisoformat(sm["ts"]).replace(tzinfo=UTC)
        assert (now - ts).days == ix
        assert sm["elo"] == 1210
        assert sm["human_elo"] == 1220
        assert sm["manual_elo"] == 1230

    for ix in reversed(range(6, 16)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"]).replace(tzinfo=UTC)
        assert (now - ts).days == ix
        assert sm["elo"] == 1240
        assert sm["human_elo"] == 1250
        assert sm["manual_elo"] == 1260

    for ix in reversed(range(0, 6)):
        sm = slist[ix]
        ts = datetime.fromisoformat(sm["ts"]).replace(tzinfo=UTC)
        assert (now - ts).days == ix
        assert sm["elo"] == 1270
        assert sm["human_elo"] == 1280
        assert sm["manual_elo"] == 1290

    resp = client.post("/logout")
    assert resp.status_code == 200


def play_game(
    client1: CustomClient,
    client2: CustomClient,
    u1: str,
    u2: str,
    locale: str,
) -> str:
    """Simulate an entire game between two users in a given
    locale. Return the index (0 or 1) of the winning player."""

    # Set the locale of User 1 to the specified locale
    # using the /setuserpref API
    resp = client1.post(
        "/setuserpref",
        json=dict(
            locale=locale,
        ),
    )
    assert resp.status_code == 200
    assert resp.json is not None
    assert "did_update" in resp.json
    assert isinstance(resp.json["did_update"], bool)

    # User 1 challenges User 2
    resp = client1.post(
        "/challenge",
        json=dict(
            action="issue",
            destuser=u2,
        ),
    )
    assert resp.status_code == 200
    assert resp.json is not None
    assert resp.json["result"] == 0  # Error.LEGAL

    # Start the game (this also accepts and deletes the challenge)
    resp = client2.post("/initgame", json=dict(opp=u1))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True
    assert "uuid" in resp.json
    game_uuid = resp.json["uuid"]
    # Ascertain that the game was initiated with the correct locale
    assert "locale" in resp.json
    assert resp.json["locale"] == locale
    # Find out which player is to move first (this is random)
    assert "to_move" in resp.json
    player_to_move = resp.json["to_move"]
    to_move = 0 if player_to_move == u2 else 1

    # Submit two simulated moves (one per player) via
    # /submitmove, and then complete the game by having
    # a player resign (submit a 'RSGN' move)
    MOVES = [
        # Horizontal first move
        ["D4=t", "D5=e", "D6=s", "D7=t"],
        # Vertical second move
        ["E4=e", "F4=s", "G4=t"],
        # Resignation move
        ["rsgn"],
    ]

    # It is client2 who initates the game and is player 0 by default
    clients = [client2, client1] if to_move == 0 else [client1, client2]

    for i, m in enumerate(MOVES):
        # Alternate between clients, submitting moves
        client = clients[i % 2]
        resp = client.post(
            "/submitmove",
            json=dict(
                uuid=game_uuid,
                moves=m,
                mcount=i,
                validate=False,
            ),
        )
        assert resp.status_code == 200
        assert resp.json is not None
        assert "result" in resp.json
        if m[0] == "rsgn":
            # Final move is a resignation; result is Error.GAME_OVER
            assert resp.json["result"] == 99  # Error.GAME_OVER
            # In this case, we leave to_move as it was
        else:
            assert resp.json["result"] == 0  # Error.LEGAL
            to_move = 1 - to_move

    # The winner is the one who did not make the resignation move
    winner = 1 - to_move
    # Check that the game is now over, by calling the /gamestate endpoint
    resp = clients[winner].post("/gamestate", json=dict(
        game=game_uuid,
        delete_zombie=1,
    ))
    assert resp.status_code == 200
    assert resp.json is not None
    assert "ok" in resp.json
    assert resp.json["ok"] == True
    assert "game" in resp.json
    game: ClientStateDict = resp.json["game"]
    # The game should be over now
    assert game.get("result") == 99  # Error.GAME_OVER
    scores = game.get("scores", [0, 0])
    winning_user = u2 if winner == 0 else u1
    if game.get("userid", ["", ""])[0] == winning_user:
        assert scores[0] > scores[1]
    else:
        assert scores[1] > scores[0]
    # Return the index of the winning player,
    # i.e. the one who did not resign
    return winning_user


def check_ratings(
    locale: str,
    client1: CustomClient,
    client2: CustomClient,
    rating1: Dict[str, int],
    rating2: Dict[str, int],
) -> None:
    """Check that the Elo ratings of the two players are as expected,
    for the given locale"""
    # First, set the locale of the users
    resp = client1.post(
        "/setuserpref",
        json=dict(
            locale=locale,
        ),
    )
    assert resp.status_code == 200
    assert resp.json is not None
    assert "did_update" in resp.json
    assert isinstance(resp.json["did_update"], bool)
    resp = client2.post(
        "/setuserpref",
        json=dict(
            locale=locale,
        ),
    )
    assert resp.status_code == 200
    assert resp.json is not None
    assert "did_update" in resp.json
    assert isinstance(resp.json["did_update"], bool)
    # Check the stats of the first user
    resp = client1.post("/userstats")
    assert resp.status_code == 200
    assert resp.json is not None
    assert "locale" in resp.json
    assert resp.json["locale"] == locale
    assert "locale_elo" in resp.json
    r = resp.json["locale_elo"]
    assert r["elo"] == rating1[locale]
    assert r["human_elo"] == rating1[locale]
    assert r["manual_elo"] == 1200
    # Check the stats of the second user
    resp = client2.post("/userstats")
    assert resp.status_code == 200
    assert resp.json is not None
    assert "locale" in resp.json
    assert resp.json["locale"] == locale
    assert "locale_elo" in resp.json
    r = resp.json["locale_elo"]
    assert r["elo"] == rating2[locale]
    assert r["human_elo"] == rating2[locale]
    assert r["manual_elo"] == 1200


def test_elo_locale(
    client1: CustomClient, client2: CustomClient, u1: str, u2: str
) -> None:
    # Delete the two test users to start with a clean slate
    from skrafldb import UserModel, Client
    with Client.get_context():
        UserModel.delete(u1)
        UserModel.delete(u2)

    # Log in on client1 as user 1
    resp = login_user(client1, 1)
    assert resp.status_code == 200
    # Log in on client2 as user 2
    resp = login_user(client2, 2)
    assert resp.status_code == 200
    # Make life a little more convenient
    play = functools.partial(play_game, client1, client2, u1, u2)
    # Play a sequence of games in different locales
    locales = ["en_US", "en_US", "nb_NO", "nb_NO", "en_US", "is_IS"]
    winners = list(map(lambda locale: (locale, play(locale)), locales))
    # Manually calculate the Elo ratings of the two players
    rating1: Dict[str, int] = defaultdict(lambda: 1200)
    rating2: Dict[str, int] = defaultdict(lambda: 1200)
    # Elo rating multiplication constant
    K = BEGINNER_K
    for locale, winner in winners:
        elo1 = rating1[locale]
        elo2 = rating2[locale]
        # Calculate the predicted outcome via the standard Elo formula
        q1: float = 10.0 ** (float(elo1) / 400.0)
        q2: float = 10.0 ** (float(elo2) / 400.0)
        exp1 = q1 / (q1 + q2)
        exp2 = q2 / (q1 + q2)
        act1, act2 = (1.0, 0.0) if winner == u1 else (0.0, 1.0)
        adj1 = int(round((act1 - exp1) * K))
        adj2 = int(round((act2 - exp2) * K))
        # logging.info(
        #     f"Locale {locale}: {u1} ({elo1}) vs. {u2} ({elo2}) -> "
        #     f"{act1}-{act2} ({exp1:.3f}-{exp2:.3f}) -> "
        #     f"{adj1:+}, {adj2:+}"
        # )
        rating1[locale] = elo1 + adj1
        rating2[locale] = elo2 + adj2
    # Check the Elo ratings of the two players in the tested locales
    for locale in set(locales):
        check_ratings(locale, client1, client2, rating1, rating2)
    # Check that the ratings remain at 1200 for pl_PL (no games played)
    empty_rating: Dict[str, int] = defaultdict(lambda: 1200)
    check_ratings("pl_PL", client1, client2, empty_rating, empty_rating)

    # Log out on both clients
    resp = client1.post("/logout")
    assert resp.status_code == 200
    resp = client2.post("/logout")
    assert resp.status_code == 200


def test_elo_rating(
    client1: CustomClient, u1: str,
) -> None:
    """Test the /rating_locale endpoint"""
    # Log in on client1 as user 1
    resp = login_user(client1, 1)
    assert resp.status_code == 200

    for locale in ("en_US", "nb_NO", "is_IS"):
        # Set the locale of User 1 to the specified locale
        # using the /setuserpref API
        resp = client1.post(
            "/setuserpref",
            json=dict(
                locale=locale,
            ),
        )
        assert resp.status_code == 200
        assert resp.json is not None
        assert "did_update" in resp.json
        assert isinstance(resp.json["did_update"], bool)
        # Obtain the current Elo ratings for the users' locale
        resp = client1.post("/rating_locale")
        assert resp.status_code == 200
        assert resp.json is not None
        assert "rating" in resp.json

    # Log out on client1
    resp = client1.post("/logout")
    assert resp.status_code == 200
