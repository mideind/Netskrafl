# -*- coding: utf-8 -*-

""" Skrafldb - persistent data management for the Netskrafl application

    Copyright (C) 2020 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The GNU General Public License, version 3, applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module stores data in the Google App Engine NDB
    (see https://developers.google.com/appengine/docs/python/ndb/).

    The data model is as follows:

    UserModel:
        nickname : string
        inactive : boolean
        prefs : dict
        timestamp : timestamp

    MoveModel:
        coord : string
        tiles : string # Blanks are denoted by '?' followed by meaning
        score : integer
        rack : string # Contents of rack after move
        timestamp : timestamp

    GameModel:
        player0 : key into UserModel
        player1 : key into UserModel
        irack0 : string # Initial rack
        irack1 : string
        rack0 : string # Current rack
        rack1 : string
        score0 : integer
        score1 : integer
        to_move : integer # Whose move is it, 0 or 1
        over : boolean # Is the game over?
        timestamp : timestamp # Start time of game
        ts_last_move : timestamp # Time of last move
        moves : array of MoveModel

    FavoriteModel:
        parent = key into UserModel
        destuser: key into UserModel

    ChallengeModel:
        parent = key into UserModel
        destuser : key into UserModel
        timestamp : timestamp
        prefs : dict

    According to the NDB documentation, an ideal index for a query
    should contain - in the order given:
    1) Properties used in equality filters
    2) Property used in an inequality filter (only one allowed)
    3) Properties used for ordering

"""

# pylint: disable=too-many-lines

import logging
import uuid

from datetime import datetime

# The following is a hack/workaround for a Google bug
import six; reload(six)

from google.cloud import ndb

from languages import Alphabet
from cache import memcache


class Client:

    """ Wrapper for the ndb client instance singleton """

    _client = ndb.Client()
    _global_cache = ndb.RedisCache(memcache.get_redis_client())

    def __init__(self):
        pass

    @classmethod
    def get_context(cls):
        """ Return the ndb client instance singleton """
        return cls._client.context(global_cache=cls._global_cache)


class Context:
    """ Wrapper for NDB context operations """

    def __init__(self):
        pass

    @staticmethod
    def disable_cache():
        """ Disable the NDB in-context cache """
        ndb.get_context().set_cache_policy(False)


class Unique:
    """ Wrapper for generation of unique id strings for keys """

    def __init__(self):
        pass

    @staticmethod
    def id():
        """ Generates unique id strings """
        return str(uuid.uuid1())  # Random UUID


def iter_q(q, chunk_size=50, limit=0, projection=None):
    """ Generator for iterating through a query using a cursor """
    if 0 < limit < chunk_size:
        # Don't fetch more than we want
        chunk_size = limit
    items, next_cursor, more = q.fetch_page(chunk_size, projection=projection)
    count = 0
    while items:
        for item in items:
            yield item
            count += 1
            if limit and count >= limit:
                # A limit was set and we'we reached it: stop
                return
        if not more or not next_cursor:
            # The query is exhausted: stop
            return
        # Get the next chunk
        items, next_cursor, more = q.fetch_page(
            chunk_size, start_cursor=next_cursor, projection=projection
        )


class UserModel(ndb.Model):

    """ Models an individual user """

    nickname = ndb.StringProperty()
    # Lower case nickname and full name of user - used for search
    nick_lc = ndb.StringProperty(required=False, default=None)
    name_lc = ndb.StringProperty(required=False, default=None)

    inactive = ndb.BooleanProperty()
    prefs = ndb.JsonProperty()
    timestamp = ndb.DateTimeProperty(auto_now_add=True)
    # Ready for challenges?
    ready = ndb.BooleanProperty(required=False, default=False)
    # Ready for timed challenges?
    ready_timed = ndb.BooleanProperty(required=False, default=False)
    # Elo points
    elo = ndb.IntegerProperty(required=False, default=0, indexed=True)
    # Elo points for human-only games
    human_elo = ndb.IntegerProperty(required=False, default=0, indexed=True)
    # Best total score in a game
    highest_score = ndb.IntegerProperty(required=False, default=0, indexed=True)
    highest_score_game = ndb.StringProperty(required=False, default=None)
    # Best word laid down
    best_word = ndb.StringProperty(required=False, default=None)
    best_word_score = ndb.IntegerProperty(required=False, default=0, indexed=True)
    best_word_game = ndb.StringProperty(required=False, default=None)

    @classmethod
    def create(cls, user_id, nickname, preferences=None):
        """ Create a new user """
        user = cls(id=user_id)
        user.nickname = nickname  # Default to the same nickname
        user.nick_lc = nickname.lower()
        user.inactive = False  # A new user is always active
        user.prefs = preferences or {}  # Default to no preferences
        user.ready = False  # Not ready for new challenges unless explicitly set
        user.ready_timed = False  # Not ready for timed games unless explicitly set
        return user.put().id()

    @classmethod
    def fetch(cls, user_id):
        """ Fetch a user entity by id """
        return cls.get_by_id(user_id)

    @classmethod
    def fetch_multi(cls, user_ids):
        """ Fetch multiple user entities by id list """
        # Google NDB/RPC doesn't allow more than 1000 entities per get_multi() call
        MAX_CHUNK = 1000
        result = []
        ix = 0
        user_ids = list(user_ids)
        end = len(user_ids)
        while ix < end:
            keys = [ndb.Key(UserModel, uid) for uid in user_ids[ix : ix + MAX_CHUNK]]
            len_keys = len(keys)
            if ix == 0 and len_keys == end:
                # Most common case: just a single, complete read
                return ndb.get_multi(keys)
            # Otherwise, accumulate chunks
            result.extend(ndb.get_multi(keys))
            ix += len_keys
        return result

    @staticmethod
    def put_multi(recs):
        """ Insert or update multiple user records """
        ndb.put_multi(recs)

    @classmethod
    def count(cls):
        """ Return a count of user entities """
        return cls.query().count()

    @classmethod
    def list(cls, nick_from, nick_to, max_len=100):
        """ Query for a list of users within a nickname range """

        nick_from = u"a" if nick_from is None else Alphabet.tolower(nick_from)
        nick_to = u"ö" if nick_to is None else Alphabet.tolower(nick_to)

        try:
            o_from = Alphabet.full_order.index(nick_from[0])
        except ValueError:
            o_from = 0
        try:
            o_to = Alphabet.full_order.index(nick_to[0])
        except ValueError:
            o_to = len(Alphabet.full_order) - 1

        # We do this by issuing a series of queries, each returning
        # nicknames beginning with a particular letter.
        # These shenanigans are necessary because NDB maintains its string
        # indexes by Unicode ordinal index, which is quite different from
        # the actual sort collation order we need. Additionally, the
        # indexes are case-sensitive while our query boundaries are not.

        # Prepare the list of query letters
        q_letters = []

        for i in range(o_from, o_to + 1):
            # Append the lower case letter
            q_letters.append(Alphabet.full_order[i])
            # Append the upper case letter
            q_letters.append(Alphabet.full_upper[i])

        # For aesthetic cleanliness, sort the query letters (in Unicode order)
        q_letters.sort()

        count = 0
        for q_from in q_letters:

            q_to = unichr(ord(q_from) + 1)

            q = cls.query(
                ndb.AND(UserModel.nickname >= q_from, UserModel.nickname < q_to)
            )

            # Individual letters contain >600 users as of 2015-02-12
            CHUNK_SIZE = 1000
            for um in iter_q(q, chunk_size=CHUNK_SIZE):
                if not um.inactive:
                    # This entity matches: return a dict describing it
                    yield dict(
                        id=um.key.id(),
                        nickname=um.nickname,
                        prefs=um.prefs,
                        timestamp=um.timestamp,
                        ready=um.ready,
                        ready_timed=um.ready_timed,
                        human_elo=um.human_elo
                    )
                    count += 1
                    if max_len and count >= max_len:
                        # Reached limit: done
                        return

    @classmethod
    def list_prefix(cls, prefix, max_len=50):
        """ Query for a list of users having a name or nick with the given prefix """

        if not prefix:
            # No prefix means nothing is returned
            return

        prefix = prefix.lower()
        id_set = set()

        def list_q(q, f):
            """ Yield the results of a user query """
            CHUNK_SIZE = 50
            for um in iter_q(q, chunk_size=CHUNK_SIZE):
                if not f(um).startswith(prefix):
                    # Iterated past the prefix
                    return
                if not um.inactive and not um.key.id() in id_set:
                    # This entity matches and has not already been
                    # returned: yield a dict describing it
                    yield dict(
                        id=um.key.id(),
                        nickname=um.nickname,
                        prefs=um.prefs,
                        timestamp=um.timestamp,
                        ready=um.ready,
                        ready_timed=um.ready_timed,
                        human_elo=um.human_elo
                    )
                    id_set.add(um.key.id())

        counter = 0

        # Return users with nicknames matching the prefix
        q = cls.query(UserModel.nick_lc >= prefix).order(UserModel.nick_lc)

        for ud in list_q(q, lambda um: um.nick_lc or ""):
            yield ud
            counter += 1
            if 0 < max_len <= counter:
                # Hit limit on returned users: stop iterating
                return

        # Return users with full names matching the prefix
        q = cls.query(UserModel.name_lc >= prefix).order(UserModel.name_lc)

        for ud in list_q(q, lambda um: um.name_lc or ""):
            yield ud
            counter += 1
            if 0 < max_len <= counter:
                # Hit limit on returned users: stop iterating
                return

    @classmethod
    def list_similar_elo(cls, elo, max_len=40):
        """ List users with a similar (human) Elo rating """
        # Start with max_len users with a lower Elo rating

        def fetch(q, max_len):
            """ Generator for returning query result keys """
            assert max_len > 0
            # pylint: disable=bad-continuation
            counter = 0  # Number of results already returned
            for k in iter_q(
                q, chunk_size=max_len, projection=['highest_score']
            ):
                if k.highest_score > 0:
                    # Has played at least one game: Yield the key value
                    yield k.key.id()
                    counter += 1
                    if counter >= max_len:
                        # Returned the requested number of records: done
                        return

        q = cls.query(UserModel.human_elo < elo).order(
            -UserModel.human_elo  # Descending order
        )
        lower = list(fetch(q, max_len))
        # Convert to an ascending list
        lower.reverse()
        # Repeat the query for same or higher rating
        q = cls.query(UserModel.human_elo >= elo).order(
            UserModel.human_elo  # Ascending order
        )
        higher = list(fetch(q, max_len))
        # Concatenate the upper part of the lower range with the
        # lower part of the higher range in the most balanced way
        # available (considering that either of the lower or upper
        # ranges may be empty or have fewer than max_len//2 entries)
        len_lower = len(lower)
        len_higher = len(higher)
        # Ideal balanced length from each range
        half_len = max_len // 2
        ix = 0  # Default starting index in the lower range
        if len_lower >= half_len:
            # We have enough entries in the lower range for a balanced result,
            # if the higher range allows
            # Move the start index
            ix = len_lower - half_len
            if len_higher < half_len:
                # We don't have enough entries in the upper range
                # to balance the result: move the beginning index down
                if ix >= half_len - len_higher:
                    # Shift the entire missing balance to the lower range
                    ix -= half_len - len_higher
                else:
                    # Take as much slack as possible
                    ix = 0
        # Concatenate the two slices into one result and return it
        assert max_len >= (len_lower - ix)
        result = lower[ix:] + higher[0:max_len - (len_lower - ix)]
        return result


class MoveModel(ndb.Model):
    """ Models a single move in a Game """

    coord = ndb.StringProperty()
    tiles = ndb.StringProperty()
    score = ndb.IntegerProperty(default=0)
    rack = ndb.StringProperty(required=False, default=None)
    timestamp = ndb.DateTimeProperty(required=False, default=None)


class GameModel(ndb.Model):
    """ Models a game between two users """

    # The players
    player0 = ndb.KeyProperty(kind=UserModel)
    player1 = ndb.KeyProperty(kind=UserModel)

    # The racks
    rack0 = ndb.StringProperty()
    rack1 = ndb.StringProperty()

    # The scores
    score0 = ndb.IntegerProperty()
    score1 = ndb.IntegerProperty()

    # Whose turn is it next, 0 or 1?
    to_move = ndb.IntegerProperty()

    # How difficult should the robot player be (if the opponent is a robot)?
    # None or 0 = most difficult
    robot_level = ndb.IntegerProperty(required=False, indexed=False, default=0)

    # Is this game over?
    over = ndb.BooleanProperty()

    # When was the game started?
    timestamp = ndb.DateTimeProperty(auto_now_add=True)

    # The timestamp of the last move in the game
    ts_last_move = ndb.DateTimeProperty(required=False, default=None)

    # The moves so far
    moves = ndb.LocalStructuredProperty(MoveModel, repeated=True, indexed=False)

    # The initial racks
    irack0 = ndb.StringProperty(required=False, default=None)
    irack1 = ndb.StringProperty(required=False, default=None)

    # Game preferences, such as duration, alternative bags or boards, etc.
    prefs = ndb.JsonProperty(required=False, default=None)

    # Count of tiles that have been laid on the board
    tile_count = ndb.IntegerProperty(required=False, indexed=False, default=None)

    # Elo statistics properties - only defined for finished games
    # Elo points of both players when game finished, before adjustment
    elo0 = ndb.IntegerProperty(required=False, indexed=False, default=None)
    elo1 = ndb.IntegerProperty(required=False, indexed=False, default=None)
    # Adjustment of Elo points of both players as a result of this game
    elo0_adj = ndb.IntegerProperty(required=False, indexed=False, default=None)
    elo1_adj = ndb.IntegerProperty(required=False, indexed=False, default=None)
    # Human-only Elo points of both players when game finished
    # (not defined if robot game)
    human_elo0 = ndb.IntegerProperty(required=False, indexed=False, default=None)
    human_elo1 = ndb.IntegerProperty(required=False, indexed=False, default=None)
    # Human-only Elo point adjustment as a result of this game
    human_elo0_adj = ndb.IntegerProperty(required=False, indexed=False, default=None)
    human_elo1_adj = ndb.IntegerProperty(required=False, indexed=False, default=None)

    def set_player(self, ix, user_id):
        """ Set a player key property to point to a given user, or None """
        k = None if user_id is None else ndb.Key(UserModel, user_id)
        if ix == 0:
            self.player0 = k
        elif ix == 1:
            self.player1 = k

    @classmethod
    def fetch(cls, game_uuid, use_cache=True):
        """ Fetch a game entity given its uuid """
        if not use_cache:
            return cls.get_by_id(game_uuid, use_cache=False, use_global_cache=False)
        # Default caching policy if caching is not explictly prohibited
        return cls.get_by_id(game_uuid)

    @classmethod
    def list_finished_games(cls, user_id, versus=None, max_len=10):
        """ Query for a list of recently finished games for the given user """
        assert user_id is not None
        if user_id is None:
            return []

        def game_callback(gm):
            """ Map a game entity to a result dictionary with useful info about the game """
            game_uuid = gm.key.id()
            u0 = None if gm.player0 is None else gm.player0.id()
            u1 = None if gm.player1 is None else gm.player1.id()
            if u0 == user_id:
                # Player 0 is the source player, 1 is the opponent
                opp = u1
                sc0, sc1 = gm.score0, gm.score1
                elo_adj = gm.elo0_adj
                human_elo_adj = gm.human_elo0_adj
            else:
                # Player 1 is the source player, 0 is the opponent
                assert u1 == user_id
                opp = u0
                sc1, sc0 = gm.score0, gm.score1
                elo_adj = gm.elo1_adj
                human_elo_adj = gm.human_elo1_adj
            return dict(
                uuid=game_uuid,
                ts=gm.timestamp,
                ts_last_move=gm.ts_last_move or gm.timestamp,
                opp=opp,
                robot_level=gm.robot_level,
                sc0=sc0,
                sc1=sc1,
                elo_adj=elo_adj,
                human_elo_adj=human_elo_adj,
                prefs=gm.prefs
            )

        k = ndb.Key(UserModel, user_id)

        if versus:
            # Add a filter on the opponent
            v = ndb.Key(UserModel, versus)
            q0 = cls.query(ndb.AND(GameModel.player1 == k, GameModel.player0 == v))
            q1 = cls.query(ndb.AND(GameModel.player0 == k, GameModel.player1 == v))
        else:
            # Plain filter on the player
            q0 = cls.query(GameModel.player0 == k)
            q1 = cls.query(GameModel.player1 == k)

        # pylint: disable=singleton-comparison
        q0 = q0.filter(GameModel.over == True).order(-GameModel.ts_last_move)
        q1 = q1.filter(GameModel.over == True).order(-GameModel.ts_last_move)

        # Issue two asynchronous queries in parallel
        qf = (q0.fetch_async(max_len), q1.fetch_async(max_len))
        # Wait for both of them to finish
        ndb.Future.wait_all(qf)

        # Combine the two query result lists and call game_callback() on each item
        rlist = map(game_callback, qf[0].get_result() + qf[1].get_result())

        # Return the newest max_len games
        return sorted(rlist, key=lambda x: x["ts_last_move"], reverse=True)[0:max_len]

    @classmethod
    def iter_live_games(cls, user_id, max_len=10):
        """ Query for a list of active games for the given user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        # pylint: disable=singleton-comparison
        q = (
            cls
            .query(ndb.OR(GameModel.player0 == k, GameModel.player1 == k))
            .filter(GameModel.over == False)
            .order(-GameModel.ts_last_move)
        )

        def game_callback(gm):
            """ Map a game entity to a result tuple with useful info about the game """
            game_uuid = gm.key.id()
            u0 = None if gm.player0 is None else gm.player0.id()
            u1 = None if gm.player1 is None else gm.player1.id()
            if u0 == user_id:
                # Player 0 is the source player, 1 is the opponent
                opp = u1
                sc0, sc1 = gm.score0, gm.score1
                my_turn = gm.to_move == 0
            else:
                # Player 1 is the source player, 0 is the opponent
                assert u1 == user_id
                opp = u0
                sc1, sc0 = gm.score0, gm.score1
                my_turn = gm.to_move == 1
            # Obtain a count of the tiles that have been laid down
            tc = gm.tile_count
            if tc is None:
                # Not stored: we must count the tiles manually
                # This will not be 100% accurate as tiles will be double-counted
                # if they are a part of two words
                tc = 0
                for m in gm.moves:
                    if m.coord:
                        # Normal tile move
                        tc += len(m.tiles.replace(u'?', u''))
            return dict(
                uuid=game_uuid,
                ts=gm.ts_last_move or gm.timestamp,
                opp=opp,
                robot_level=gm.robot_level,
                my_turn=my_turn,
                sc0=sc0,
                sc1=sc1,
                prefs=gm.prefs,
                tile_count=tc
            )

        for gm in q.fetch(max_len):
            yield game_callback(gm)


class FavoriteModel(ndb.Model):
    """ Models the fact that a user has marked another user as a favorite """

    MAX_FAVORITES = 100  # The maximum number of favorites that a user can have

    # The originating (source) user is the parent/ancestor of the relation
    destuser = ndb.KeyProperty(kind=UserModel)

    def set_dest(self, user_id):
        """ Set a destination user key property """
        k = None if user_id is None else ndb.Key(UserModel, user_id)
        self.destuser = k

    @classmethod
    def list_favorites(cls, user_id, max_len=MAX_FAVORITES):
        """ Query for a list of favorite users for the given user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        q = cls.query(ancestor=k)
        for fm in q.fetch(max_len, read_consistency=ndb.EVENTUAL):
            yield None if fm.destuser is None else fm.destuser.id()

    @classmethod
    def has_relation(cls, srcuser_id, destuser_id):
        """ Return True if destuser is a favorite of user """
        if srcuser_id is None or destuser_id is None:
            return False
        ks = ndb.Key(UserModel, srcuser_id)
        kd = ndb.Key(UserModel, destuser_id)
        q = cls.query(ancestor=ks).filter(FavoriteModel.destuser == kd)
        return q.get(keys_only=True) is not None

    @classmethod
    def add_relation(cls, src_id, dest_id):
        """ Add a favorite relation between the two users """
        fm = FavoriteModel(parent=ndb.Key(UserModel, src_id))
        fm.set_dest(dest_id)
        fm.put()

    @classmethod
    def del_relation(cls, src_id, dest_id):
        """ Delete a favorite relation between a source user and a destination user """
        ks = ndb.Key(UserModel, src_id)
        kd = ndb.Key(UserModel, dest_id)
        while True:
            # There might conceivably be more than one relation,
            # so repeat the query/delete cycle until we don't find any more
            q = cls.query(ancestor=ks).filter(FavoriteModel.destuser == kd)
            fmk = q.get(keys_only=True)
            if fmk is None:
                return
            fmk.delete()


class ChallengeModel(ndb.Model):
    """ Models a challenge issued by a user to another user """

    # The challenging (source) user is the parent/ancestor of the relation

    # The challenged user
    destuser = ndb.KeyProperty(kind=UserModel)

    # The parameters of the challenge (time, bag type, etc.)
    prefs = ndb.JsonProperty()

    # The time of issuance
    timestamp = ndb.DateTimeProperty(auto_now_add=True)

    def set_dest(self, user_id):
        """ Set a destination user key property """
        k = None if user_id is None else ndb.Key(UserModel, user_id)
        self.destuser = k

    @classmethod
    def has_relation(cls, srcuser_id, destuser_id):
        """ Return True if srcuser has issued a challenge to destuser """
        if srcuser_id is None or destuser_id is None:
            return False
        ks = ndb.Key(UserModel, srcuser_id)
        kd = ndb.Key(UserModel, destuser_id)
        q = cls.query(ancestor=ks).filter(ChallengeModel.destuser == kd)
        return q.get(keys_only=True) is not None

    @classmethod
    def find_relation(cls, srcuser_id, destuser_id):
        """ Return (found, prefs) where found is True if srcuser has challenged destuser """
        if srcuser_id is None or destuser_id is None:
            # noinspection PyRedundantParentheses
            return (False, None)
        ks = ndb.Key(UserModel, srcuser_id)
        kd = ndb.Key(UserModel, destuser_id)
        q = cls.query(ancestor=ks).filter(ChallengeModel.destuser == kd)
        cm = q.get()
        if cm is None:
            # Not found
            # noinspection PyRedundantParentheses
            return (False, None)
        # Found: return the preferences associated with the challenge (if any)
        return (True, cm.prefs)

    @classmethod
    def add_relation(cls, src_id, dest_id, prefs):
        """ Add a challenge relation between the two users """
        cm = ChallengeModel(parent=ndb.Key(UserModel, src_id))
        cm.set_dest(dest_id)
        cm.prefs = {} if prefs is None else prefs
        cm.put()

    @classmethod
    def del_relation(cls, src_id, dest_id):
        """ Delete a challenge relation between a source user and a destination user """
        ks = ndb.Key(UserModel, src_id)
        kd = ndb.Key(UserModel, dest_id)
        prefs = None
        found = False
        while True:
            # There might conceivably be more than one relation,
            # so repeat the query/delete cycle until we don't find any more
            q = cls.query(ancestor=ks).filter(ChallengeModel.destuser == kd)
            cm = q.get()
            if cm is None:
                # Return the preferences of the challenge, if any
                return (found, prefs)
            # Found the relation in question: store the associated preferences
            found = True
            if prefs is None:
                prefs = cm.prefs
            cm.key.delete()

    @classmethod
    def list_issued(cls, user_id, max_len=20):
        """ Query for a list of challenges issued by a particular user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        # List issued challenges in ascending order by timestamp (oldest first)
        q = cls.query(ancestor=k).order(ChallengeModel.timestamp)

        def ch_callback(cm):
            """ Map an issued challenge to a tuple of useful info """
            id0 = None if cm.destuser is None else cm.destuser.id()
            return (id0, cm.prefs, cm.timestamp)

        for cm in q.fetch(max_len):
            yield ch_callback(cm)

    @classmethod
    def list_received(cls, user_id, max_len=20):
        """ Query for a list of challenges issued to a particular user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        # List received challenges in ascending order by timestamp (oldest first)
        q = cls.query(ChallengeModel.destuser == k).order(ChallengeModel.timestamp)

        def ch_callback(cm):
            """ Map a received challenge to a tuple of useful info """
            p0 = cm.key.parent()
            id0 = None if p0 is None else p0.id()
            return (id0, cm.prefs, cm.timestamp)

        for cm in q.fetch(max_len):
            yield ch_callback(cm)


class StatsModel(ndb.Model):
    """ Models statistics about users """

    # The user associated with this statistic or None if robot
    user = ndb.KeyProperty(kind=UserModel, indexed=True, required=False, default=None)
    robot_level = ndb.IntegerProperty(required=False, default=0)

    # The timestamp of this statistic
    timestamp = ndb.DateTimeProperty(indexed=True, auto_now_add=True)

    games = ndb.IntegerProperty()
    human_games = ndb.IntegerProperty()

    elo = ndb.IntegerProperty(indexed=True, default=1200)
    human_elo = ndb.IntegerProperty(indexed=True, default=1200)

    score = ndb.IntegerProperty(indexed=False)
    human_score = ndb.IntegerProperty(indexed=False)

    score_against = ndb.IntegerProperty(indexed=False)
    human_score_against = ndb.IntegerProperty(indexed=False)

    wins = ndb.IntegerProperty(indexed=False)
    losses = ndb.IntegerProperty(indexed=False)

    human_wins = ndb.IntegerProperty(indexed=False)
    human_losses = ndb.IntegerProperty(indexed=False)

    MAX_STATS = 100

    def set_user(self, user_id, robot_level=0):
        """ Set the user key property """
        k = None if user_id is None else ndb.Key(UserModel, user_id)
        self.user = k
        self.robot_level = robot_level

    @classmethod
    def create(cls, user_id, robot_level=0):
        """ Create a fresh instance with default values """
        sm = cls()
        sm.set_user(user_id, robot_level)
        sm.timestamp = None
        sm.elo = 1200
        sm.human_elo = 1200
        sm.games = 0
        sm.human_games = 0
        sm.score = 0
        sm.human_score = 0
        sm.score_against = 0
        sm.human_score_against = 0
        sm.wins = 0
        sm.losses = 0
        sm.human_wins = 0
        sm.human_losses = 0
        return sm

    def copy_from(self, src):
        """ Copy data from the src instance """
        # user and robot_level are assumed to be in place already
        assert hasattr(self, "user")
        assert hasattr(self, "robot_level")
        self.timestamp = src.timestamp
        self.elo = src.elo
        self.human_elo = src.human_elo
        self.games = src.games
        self.human_games = src.human_games
        self.score = src.score
        self.human_score = src.human_score
        self.score_against = src.score_against
        self.human_score_against = src.human_score_against
        self.wins = src.wins
        self.losses = src.losses
        self.human_wins = src.human_wins
        self.human_losses = src.human_losses

    def populate_dict(self, d):
        """ Copy statistics data to the given dict """
        d["elo"] = self.elo
        d["human_elo"] = self.human_elo
        d["games"] = self.games
        d["human_games"] = self.human_games
        d["score"] = self.score
        d["human_score"] = self.human_score
        d["score_against"] = self.score_against
        d["human_score_against"] = self.human_score_against
        d["wins"] = self.wins
        d["losses"] = self.losses
        d["human_wins"] = self.human_wins
        d["human_losses"] = self.human_losses

    @staticmethod
    def dict_key(d):
        """ Return a dictionary key that works for human users and robots """
        if d["user"] is None:
            return "robot-" + str(d["robot_level"])
        return d["user"]

    @staticmethod
    def user_id_from_key(k):
        """ Decompose a dictionary key into a (user_id, robot_level) tuple """
        if k is not None and k.startswith("robot-"):
            return (None, int(k[6:]))
        return (k, 0)

    @classmethod
    def _list_by(cls, prop, makedict, timestamp=None, max_len=MAX_STATS):
        """ Returns the Elo ratings at the indicated time point (None = now),
            in descending order  """

        max_fetch = max_len * 2
        check_false_positives = True

        if timestamp is None:
            timestamp = datetime.utcnow()
            max_fetch = max_len
            # No need to check false positives if querying newest records
            check_false_positives = False

        # Use descending Elo order
        # Ndb doesn't allow us to put an inequality filter on the timestamp here
        # so we need to fetch irrespective of timestamp and manually filter
        q = cls.query().order(-prop)

        result = dict()
        CHUNK_SIZE = 100
        lowest_elo = None

        # The following loop may yield an incorrect result since there may
        # be newer stats records for individual users with lower Elo scores
        # than those scanned to create the list. In other words, there may
        # be false positives on the list (but not false negatives, i.e.
        # there can't be higher Elo scores somewhere that didn't make it
        # to the list). We attempt to address this by fetching double the
        # number of requested users, then separately checking each of them for
        # false positives. If we have too many false positives, we don't return
        # the full requested number of result records.

        for sm in iter_q(q, CHUNK_SIZE):
            if sm.timestamp <= timestamp:
                # Within our time range
                d = makedict(sm)
                ukey = cls.dict_key(d)
                if (ukey not in result) or (d["timestamp"] > result[ukey]["timestamp"]):
                    # Fresh entry or newer (and also lower) than the previous one
                    result[ukey] = d
                    if (lowest_elo is None) or (d["elo"] < lowest_elo):
                        lowest_elo = d["elo"]
                    if len(result) >= max_fetch:
                        # We have double the number of entries requested: done
                        break  # From for loop

        false_pos = 0
        # Do another loop through the result to check for false positives
        if check_false_positives:
            for ukey, d in result.items():
                sm = cls.newest_before(timestamp, d["user"], d["robot_level"])
                assert sm is not None  # We should always have an entity here
                nd = makedict(sm)
                # This may be None if a default record was created
                nd_ts = nd["timestamp"]
                if (nd_ts is not None) and nd_ts > d["timestamp"]:
                    # This is a newer one than we have already
                    # It must be a lower Elo score, or we would already have it
                    assert nd["elo"] <= d["elo"]
                    assert lowest_elo is not None
                    if nd["elo"] < lowest_elo:
                        # The entry didn't belong on the list at all
                        false_pos += 1
                    # Replace the entry with the newer one (which will lower it)
                    result[ukey] = nd
            logging.info(u"False positives are {0}".format(false_pos))

        if false_pos > max_len:
            # Houston, we have a problem: the original list was way off
            # and the corrections are not sufficient;
            # truncate the result accordingly
            logging.error(u"False positives caused ratings list to be truncated")
            max_len -= false_pos - max_len
            if max_len < 0:
                max_len = 0

        # Sort in descending order by Elo, and finally rank and return the result
        result_list = sorted(result.values(), key=lambda x: -x["elo"])[0:max_len]
        for ix, d in enumerate(result_list):
            d["rank"] = ix + 1

        return result_list

    @classmethod
    def list_elo(cls, timestamp=None, max_len=MAX_STATS):
        """ Return the top Elo-rated users for all games (including robots) """

        def _makedict(sm):
            return dict(
                user=None if sm.user is None else sm.user.id(),
                robot_level=sm.robot_level,
                timestamp=sm.timestamp,
                games=sm.games,
                elo=sm.elo,
                score=sm.score,
                score_against=sm.score_against,
                wins=sm.wins,
                losses=sm.losses
            )

        return cls._list_by(StatsModel.elo, _makedict, timestamp, max_len)

    @classmethod
    def list_human_elo(cls, timestamp=None, max_len=MAX_STATS):
        """ Return the top Elo-rated users for human-only games """

        def _makedict(sm):
            return dict(
                user=None if sm.user is None else sm.user.id(),
                robot_level=sm.robot_level,
                timestamp=sm.timestamp,
                games=sm.human_games,
                elo=sm.human_elo,
                score=sm.human_score,
                score_against=sm.human_score_against,
                wins=sm.human_wins,
                losses=sm.human_losses
            )

        return cls._list_by(StatsModel.human_elo, _makedict, timestamp, max_len)

    _NB_CACHE = dict()
    _NB_CACHE_STATS = dict(hits=0, misses=0)

    @classmethod
    def clear_cache(cls):
        """ Reset the cache """
        cls._NB_CACHE = dict()
        cls._NB_CACHE_STATS = dict(hits=0, misses=0)

    @classmethod
    def log_cache_stats(cls):
        """ Show cache statistics in the log """
        hits = cls._NB_CACHE_STATS["hits"]
        misses = cls._NB_CACHE_STATS["misses"]
        total = hits + misses
        logging.info(
            "Cache hits {0} or {1:.2f}%".format(
                hits, 100.0 * hits / total if total != 0 else 0.0
            )
        )
        logging.info(
            "Cache misses {0} or {1:.2f}%".format(
                misses, 100.0 * misses / total if total != 0 else 0.0
            )
        )

    @classmethod
    def newest_before(cls, ts, user_id, robot_level=0):
        """ Returns the newest available stats record for the user at or before the given time """
        cache = cls._NB_CACHE
        key = (user_id, robot_level)
        if ts:
            if key in cache:
                for c_ts, c_val in cache[key].items():
                    if c_ts >= ts >= c_val.timestamp:
                        cls._NB_CACHE_STATS["hits"] += 1
                        sm = cls.create(user_id, robot_level)
                        sm.copy_from(c_val)
                        return sm
            else:
                cache[key] = dict()
        cls._NB_CACHE_STATS["misses"] += 1
        sm = cls.create(user_id, robot_level)
        if ts:
            # Try to query using the timestamp
            if user_id is None:
                k = None
            else:
                k = ndb.Key(UserModel, user_id)
            # Use a common query structure and index for humans and robots
            q = cls.query(
                ndb.AND(StatsModel.user == k, StatsModel.robot_level == robot_level)
            )
            q = q.filter(StatsModel.timestamp <= ts).order(-StatsModel.timestamp)
            sm_before = q.get()
            if sm_before is not None:
                # Found: copy the stats
                sm.copy_from(sm_before)
            cache[key][ts] = sm
        return sm

    @classmethod
    def newest_for_user(cls, user_id):
        """ Returns the newest available stats record for the user """
        if user_id is None:
            return None
        k = ndb.Key(UserModel, user_id)
        # Use a common query structure and index for humans and robots
        q = (
            cls
            .query(ndb.AND(StatsModel.user == k, StatsModel.robot_level == 0))
            .order(-StatsModel.timestamp)
        )
        sm = q.get()
        if sm is None:
            # No record in the database: return a default entity
            sm = cls.create(user_id)
        return sm

    @staticmethod
    def put_multi(recs):
        """ Insert or update multiple stats records """
        ndb.put_multi(recs)

    @classmethod
    def delete_ts(cls, timestamp):
        """ Delete all stats records at a particular timestamp """
        ndb.delete_multi(
            cls
            .query(StatsModel.timestamp == timestamp)
            .iter(keys_only=True)
        )


class RatingModel(ndb.Model):
    """ Models tables of user ratings """

    # Typically "all" or "human"
    kind = ndb.StringProperty(required=True)

    # The ordinal rank
    rank = ndb.IntegerProperty(required=True)

    user = ndb.KeyProperty(kind=UserModel, required=False, default=None)
    robot_level = ndb.IntegerProperty(required=False, default=0)

    games = ndb.IntegerProperty(required=False, default=0)
    elo = ndb.IntegerProperty(required=False, default=1200)
    score = ndb.IntegerProperty(required=False, default=0)
    score_against = ndb.IntegerProperty(required=False, default=0)
    wins = ndb.IntegerProperty(required=False, default=0)
    losses = ndb.IntegerProperty(required=False, default=0)

    rank_yesterday = ndb.IntegerProperty(required=False, default=0)
    games_yesterday = ndb.IntegerProperty(required=False, default=0)
    elo_yesterday = ndb.IntegerProperty(required=False, default=1200)
    score_yesterday = ndb.IntegerProperty(required=False, default=0)
    score_against_yesterday = ndb.IntegerProperty(required=False, default=0)
    wins_yesterday = ndb.IntegerProperty(required=False, default=0)
    losses_yesterday = ndb.IntegerProperty(required=False, default=0)

    rank_week_ago = ndb.IntegerProperty(required=False, default=0)
    games_week_ago = ndb.IntegerProperty(required=False, default=0)
    elo_week_ago = ndb.IntegerProperty(required=False, default=1200)
    score_week_ago = ndb.IntegerProperty(required=False, default=0)
    score_against_week_ago = ndb.IntegerProperty(required=False, default=0)
    wins_week_ago = ndb.IntegerProperty(required=False, default=0)
    losses_week_ago = ndb.IntegerProperty(required=False, default=0)

    rank_month_ago = ndb.IntegerProperty(required=False, default=0)
    games_month_ago = ndb.IntegerProperty(required=False, default=0)
    elo_month_ago = ndb.IntegerProperty(required=False, default=1200)
    score_month_ago = ndb.IntegerProperty(required=False, default=0)
    score_against_month_ago = ndb.IntegerProperty(required=False, default=0)
    wins_month_ago = ndb.IntegerProperty(required=False, default=0)
    losses_month_ago = ndb.IntegerProperty(required=False, default=0)

    @classmethod
    def get_or_create(cls, kind, rank):
        """ Get an existing entity or create a new one if it doesn't exist """
        k = ndb.Key(cls, kind + ":" + str(rank))
        rm = k.get()
        if rm is None:
            # Did not already exist in the database:
            # create a fresh instance
            rm = cls(id=kind + ":" + str(rank))
        rm.kind = kind
        rm.rank = rank
        return rm

    def assign(self, dict_args):
        """ Populate attributes from a dict """
        for key, val in dict_args.items():
            if key == "user":
                # Re-pack the user id into a key
                setattr(self, key, None if val is None else ndb.Key(UserModel, val))
            else:
                setattr(self, key, val)

    @classmethod
    def list_rating(cls, kind):
        """ Iterate through the rating table of a given kind, in ascending order by rank """
        CHUNK_SIZE = 100
        q = cls.query(RatingModel.kind == kind).order(RatingModel.rank)
        for rm in iter_q(q, CHUNK_SIZE, limit=100):
            v = dict(
                rank=rm.rank,
                games=rm.games,
                elo=rm.elo,
                score=rm.score,
                score_against=rm.score_against,
                wins=rm.wins,
                losses=rm.losses,
                rank_yesterday=rm.rank_yesterday,
                games_yesterday=rm.games_yesterday,
                elo_yesterday=rm.elo_yesterday,
                score_yesterday=rm.score_yesterday,
                score_against_yesterday=rm.score_against_yesterday,
                wins_yesterday=rm.wins_yesterday,
                losses_yesterday=rm.losses_yesterday,
                rank_week_ago=rm.rank_week_ago,
                games_week_ago=rm.games_week_ago,
                elo_week_ago=rm.elo_week_ago,
                score_week_ago=rm.score_week_ago,
                score_against_week_ago=rm.score_against_week_ago,
                wins_week_ago=rm.wins_week_ago,
                losses_week_ago=rm.losses_week_ago,
                rank_month_ago=rm.rank_month_ago,
                games_month_ago=rm.games_month_ago,
                elo_month_ago=rm.elo_month_ago,
                score_month_ago=rm.score_month_ago,
                score_against_month_ago=rm.score_against_month_ago,
                wins_month_ago=rm.wins_month_ago,
                losses_month_ago=rm.losses_month_ago
            )

            # Stringify a user id
            if rm.user is None:
                if rm.robot_level < 0:
                    v["userid"] = ""
                else:
                    v["userid"] = "robot-" + str(rm.robot_level)
            else:
                v["userid"] = rm.user.id()

            yield v

    @staticmethod
    def put_multi(recs):
        """ Insert or update multiple ratings records """
        ndb.put_multi(recs)


class ChatModel(ndb.Model):
    """ Models chat communications between users """

    # The channel (conversation) identifier
    channel = ndb.StringProperty(required=True)

    # The user originating this chat message
    user = ndb.KeyProperty(kind=UserModel, indexed=True, required=True)

    # The timestamp of this chat message
    timestamp = ndb.DateTimeProperty(indexed=True, auto_now_add=True)

    # The actual message - by convention, an empty msg from a user means that
    # the user has seen all older messages
    msg = ndb.StringProperty()

    @classmethod
    def list_conversation(cls, channel, maxlen=250):
        """ Return the newest items in a conversation """
        CHUNK_SIZE = 100
        q = cls.query(ChatModel.channel == channel).order(-ChatModel.timestamp)
        count = 0
        for cm in iter_q(q, CHUNK_SIZE):
            if cm.msg:
                # Don't return empty messages (read markers)
                yield dict(user=cm.user.id(), ts=cm.timestamp, msg=cm.msg)
                count += 1
                if count >= maxlen:
                    break

    @classmethod
    def check_conversation(cls, channel, userid):
        """ Returns True if there are unseen messages in the conversation """
        CHUNK_SIZE = 40
        q = cls.query(ChatModel.channel == channel).order(-ChatModel.timestamp)
        for cm in iter_q(q, CHUNK_SIZE):
            if (cm.user.id() != userid) and cm.msg:
                # Found a message originated by the other user
                return True
            if (cm.user.id() == userid) and not cm.msg:
                # Found an 'already seen' indicator (empty message) from the querying user
                return False
        # Gone through the whole thread without finding an unseen message
        return False

    @classmethod
    def add_msg(cls, channel, userid, msg, timestamp=None):
        """ Adds a message to a chat conversation on a channel """
        cm = cls()
        cm.channel = channel
        cm.user = ndb.Key(UserModel, userid)
        cm.msg = msg
        cm.timestamp = timestamp or datetime.utcnow()
        cm.put()
        # Return the message timestamp
        return cm.timestamp


class ZombieModel(ndb.Model):
    """ Models finished games that have not been seen by one of the players """

    # The zombie game
    game = ndb.KeyProperty(kind=GameModel)
    # The player that has not seen the result
    player = ndb.KeyProperty(kind=UserModel)

    def set_player(self, user_id):
        """ Set the player's user id """
        self.player = None if user_id is None else ndb.Key(UserModel, user_id)

    def set_game(self, game_id):
        """ Set the game id """
        self.game = None if game_id is None else ndb.Key(GameModel, game_id)

    @classmethod
    def add_game(cls, game_id, user_id):
        """ Add a zombie game that has not been seen by the player in question """
        zm = cls()
        zm.set_game(game_id)
        zm.set_player(user_id)
        zm.put()

    @classmethod
    def del_game(cls, game_id, user_id):
        """ Delete a zombie game after the player has seen it """
        kg = ndb.Key(GameModel, game_id)
        kp = ndb.Key(UserModel, user_id)
        q = cls.query(ZombieModel.game == kg).filter(ZombieModel.player == kp)
        zmk = q.get(keys_only=True)
        if not zmk:
            # No such game in the zombie list
            return
        zmk.delete()

    @classmethod
    def list_games(cls, user_id):
        """ List all zombie games for the given player """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        q = cls.query(ZombieModel.player == k)

        def z_callback(zm):
            """ Map a ZombieModel entity to a game descriptor """
            if not zm.game:
                return None
            gm = GameModel.fetch(zm.game.id())
            u0 = None if gm.player0 is None else gm.player0.id()
            u1 = None if gm.player1 is None else gm.player1.id()
            if u0 == user_id:
                # Player 0 is the source player, 1 is the opponent
                opp = u1
                sc0, sc1 = gm.score0, gm.score1
            else:
                # Player 1 is the source player, 0 is the opponent
                assert u1 == user_id
                opp = u0
                sc1, sc0 = gm.score0, gm.score1
            return dict(
                uuid=zm.game.id(),
                ts=gm.ts_last_move or gm.timestamp,
                opp=opp,
                robot_level=gm.robot_level,
                sc0=sc0,
                sc1=sc1
            )

        for zm in q.fetch():
            yield z_callback(zm)


class PromoModel(ndb.Model):
    """ Models promotions displayed to players """

    # The player that saw the promotion
    player = ndb.KeyProperty(kind=UserModel)
    # The promotion id
    promotion = ndb.StringProperty(required=True)
    # The timestamp
    timestamp = ndb.DateTimeProperty(auto_now_add=True)

    def set_player(self, user_id):
        """ Set the player's user id """
        assert user_id is not None
        self.player = ndb.Key(UserModel, user_id)

    @classmethod
    def add_promotion(cls, user_id, promotion):
        """ Add a zombie game that has not been seen by the player in question """
        pm = cls()
        pm.set_player(user_id)
        pm.promotion = promotion
        pm.put()

    @classmethod
    def list_promotions(cls, user_id, promotion):
        """ Return a list of timestamps for when the given promotion has been displayed """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        q = cls.query(PromoModel.player == k).filter(PromoModel.promotion == promotion)

        for pm in q.fetch(projection=['timestamp']):
            yield pm.timestamp

