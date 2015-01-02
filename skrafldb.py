# -*- coding: utf-8 -*-

""" Skrafldb - persistent data management for the Netskrafl application

    Author: Vilhjalmur Thorsteinsson, 2014

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

"""

import logging
import uuid
from datetime import datetime, timedelta

from google.appengine.ext import ndb
from google.appengine.api import channel

from languages import Alphabet


class Unique:
    """ Wrapper for generation of unique id strings for keys """

    @staticmethod
    def id():
        """ Generates unique id strings """
        return str(uuid.uuid1()) # Random UUID


class UserModel(ndb.Model):

    """ Models an individual user """

    nickname = ndb.StringProperty()
    inactive = ndb.BooleanProperty()
    prefs = ndb.JsonProperty()
    timestamp = ndb.DateTimeProperty(auto_now_add = True)

    @classmethod
    def create(cls, user_id, nickname):
        """ Create a new user """
        user = cls(id = user_id)
        user.nickname = nickname # Default to the same nickname
        user.inactive = False # A new user is always active
        user.prefs = { } # No preferences
        return user.put().id()

    @classmethod
    def update(cls, user_id, nickname, inactive, prefs):
        """ Update an existing user entity """
        user = cls.fetch(user_id)
        user.nickname = nickname
        user.inactive = inactive
        user.prefs = prefs
        user.put()

    @classmethod
    def fetch(cls, user_id):
        """ Fetch a user entity by id """
        return cls.get_by_id(user_id)

    @classmethod
    def list(cls, nick_from, nick_to, max_len = 50):
        """ Query for a list of users within a nickname range """

        q = cls.query().order(UserModel.nickname)

        nick_from = u"" if nick_from is None else Alphabet.tolower(nick_from)
        nick_to = u"" if nick_to is None else Alphabet.tolower(nick_to)
        counter = 0
        o_from = 0 if not nick_from else Alphabet.full_order.index(nick_from[0])
        o_to = 255 if not nick_to else Alphabet.full_order.index(nick_to[0])

        for um in q.fetch():
            if not um.inactive:
                nick = Alphabet.tolower(um.nickname)
                if len(nick) > 0 and nick[0] in Alphabet.full_order:
                    # Nicknames that do not start with an alpabetic character are not listed
                    o_nick = Alphabet.full_order.index(nick[0])
                    if o_nick >= o_from and o_nick <= o_to:
                        yield um.key.id()
                        counter += 1
                        if max_len > 0 and counter >= max_len:
                            break


class MoveModel(ndb.Model):
    """ Models a single move in a Game """

    coord = ndb.StringProperty()
    tiles = ndb.StringProperty()
    score = ndb.IntegerProperty(default = 0)
    rack = ndb.StringProperty(required = False, default = None)
    timestamp = ndb.DateTimeProperty(required = False, default = None)


class GameModel(ndb.Model):
    """ Models a game between two users """

    # The players
    player0 = ndb.KeyProperty(kind = UserModel)
    player1 = ndb.KeyProperty(kind = UserModel)

    # The racks
    rack0 = ndb.StringProperty(indexed = False)
    rack1 = ndb.StringProperty(indexed = False)

    # The scores
    score0 = ndb.IntegerProperty()
    score1 = ndb.IntegerProperty()

    # Whose turn is it next, 0 or 1?
    to_move = ndb.IntegerProperty()

    # How difficult should the robot player be (if the opponent is a robot)?
    # None or 0 = most difficult
    robot_level = ndb.IntegerProperty(required = False, indexed = False, default = 0)

    # Is this game over?
    over = ndb.BooleanProperty()

    # When was the game started?
    timestamp = ndb.DateTimeProperty(auto_now_add = True)

    # The timestamp of the last move in the game
    ts_last_move = ndb.DateTimeProperty(required = False, default = None)

    # The moves so far
    moves = ndb.LocalStructuredProperty(MoveModel, repeated = True)

    # The initial racks
    irack0 = ndb.StringProperty(required = False, indexed = False, default = None)
    irack1 = ndb.StringProperty(required = False, indexed = False, default = None)

    def set_player(self, ix, user_id):
        """ Set a player key property to point to a given user, or None """
        k = None if user_id is None else ndb.Key(UserModel, user_id)
        if ix == 0:
            self.player0 = k
        elif ix == 1:
            self.player1 = k

    @classmethod
    def fetch(cls, uuid):
        """ Fetch a game entity given its uuid """
        return cls.get_by_id(uuid)

    @classmethod
    def find_live_game(cls, user_id):
        """ Query to find a live (ongoing) game for the given user, if it exists """
        assert user_id is not None
        if user_id is None:
            return None
        k = ndb.Key(UserModel, user_id)
        q = cls.query(ndb.OR(GameModel.player0 == k, GameModel.player1 == k)).filter(GameModel.over == False)
        reskey = q.get(keys_only = True)
        logging.info(u"Loaded game {0} for user {1}".format(u"[not found]" if reskey is None else reskey.id(), user_id).encode("latin-1"))
        return None if reskey is None else reskey.id()

    @classmethod
    def find_finished_game(cls, user_id):
        """ Query to find any finished game for the given user, if it exists """
        # Used mostly for debugging purposes
        assert user_id is not None
        if user_id is None:
            return None
        k = ndb.Key(UserModel, user_id)
        q = cls.query(ndb.OR(GameModel.player0 == k, GameModel.player1 == k)).filter(GameModel.over == True)
        reskey = q.get(keys_only = True)
        logging.info(u"Loaded game {0} for user {1}".format(u"[not found]" if reskey is None else reskey.id(), user_id).encode("latin-1"))
        return None if reskey is None else reskey.id()

    @classmethod
    def list_finished_games(cls, user_id, max_len = 10):
        """ Query for a list of recently finished games for the given user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        q = cls.query(ndb.OR(GameModel.player0 == k, GameModel.player1 == k)).filter(GameModel.over == True).order(-GameModel.timestamp)

        def game_callback(gm):
            """ Map a game entity to a result tuple with useful info about the game """
            uuid = gm.key.id()
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
                uuid = uuid,
                ts = gm.timestamp,
                opp = opp,
                sc0 = sc0,
                sc1 = sc1,
                robot_level = gm.robot_level)

        for gm in q.fetch(max_len):
            yield game_callback(gm)


    @classmethod
    def list_live_games(cls, user_id, max_len = 10):
        """ Query for a list of active games for the given user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        q = cls.query(ndb.OR(GameModel.player0 == k, GameModel.player1 == k)).filter(GameModel.over == False)
        # Used to be .order(-GameModel.timestamp) but we want the displayed list to be sorted by ts_last_move

        def game_callback(gm):
            """ Map a game entity to a result tuple with useful info about the game """
            uuid = gm.key.id()
            u0 = None if gm.player0 is None else gm.player0.id()
            u1 = None if gm.player1 is None else gm.player1.id()
            if u0 == user_id:
                # Player 0 is the source player, 1 is the opponent
                opp = u1
                sc0, sc1 = gm.score0, gm.score1
                my_turn = (gm.to_move == 0)
            else:
                # Player 1 is the source player, 0 is the opponent
                assert u1 == user_id
                opp = u0
                sc1, sc0 = gm.score0, gm.score1
                my_turn = (gm.to_move == 1)
            return dict(
                uuid = uuid,
                ts = gm.ts_last_move or gm.timestamp,
                opp = opp,
                my_turn = my_turn,
                sc0 = sc0,
                sc1 = sc1,
                robot_level = gm.robot_level)

        for gm in q.fetch(max_len):
            yield game_callback(gm)


class FavoriteModel(ndb.Model):
    """ Models the fact that a user has marked another user as a favorite """

    # The originating (source) user is the parent/ancestor of the relation
    destuser = ndb.KeyProperty(kind = UserModel)

    def set_dest(self, user_id):
        """ Set a destination user key property """
        k = None if user_id is None else ndb.Key(UserModel, user_id)
        self.destuser = k

    @classmethod
    def list_favorites(cls, user_id, max_len = 10):
        """ Query for a list of favorite users for the given user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        q = cls.query(ancestor = k)
        for fm in q.fetch(max_len):
            yield None if fm.destuser is None else fm.destuser.id()

    @classmethod
    def has_relation(cls, srcuser_id, destuser_id):
        """ Return True if destuser is a favorite of user """
        if srcuser_id is None or destuser_id is None:
            return False
        ks = ndb.Key(UserModel, srcuser_id)
        kd = ndb.Key(UserModel, destuser_id)
        q = cls.query(ancestor = ks).filter(FavoriteModel.destuser == kd)
        return q.get(keys_only = True) != None

    @classmethod
    def add_relation(cls, src_id, dest_id):
        """ Add a favorite relation between the two users """
        fm = FavoriteModel(parent = ndb.Key(UserModel, src_id))
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
            q = cls.query(ancestor = ks).filter(FavoriteModel.destuser == kd)
            fmk = q.get(keys_only = True)
            if fmk is None:
                return
            fmk.delete()


class ChallengeModel(ndb.Model):
    """ Models a challenge issued by a user to another user """

    # The challenging (source) user is the parent/ancestor of the relation

    # The challenged user
    destuser = ndb.KeyProperty(kind = UserModel)

    # The parameters of the challenge (time, bag type, etc.)
    prefs = ndb.JsonProperty()

    # The time of issuance
    timestamp = ndb.DateTimeProperty(auto_now_add = True)

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
        q = cls.query(ancestor = ks).filter(ChallengeModel.destuser == kd)
        return q.get(keys_only = True) != None

    @classmethod
    def add_relation(cls, src_id, dest_id, prefs):
        """ Add a challenge relation between the two users """
        cm = ChallengeModel(parent = ndb.Key(UserModel, src_id))
        cm.set_dest(dest_id)
        cm.prefs = { } if prefs is None else prefs
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
            q = cls.query(ancestor = ks).filter(ChallengeModel.destuser == kd)
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
    def list_issued(cls, user_id, max_len = 20):
        """ Query for a list of challenges issued by a particular user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        # List issued challenges in ascending order by timestamp (oldest first)
        q = cls.query(ancestor = k).order(ChallengeModel.timestamp)

        def ch_callback(cm):
            """ Map a favorite relation into a list of users """
            id0 = None if cm.destuser is None else cm.destuser.id()
            return (id0, cm.prefs, cm.timestamp)

        for cm in q.fetch(max_len):
            yield ch_callback(cm)

    @classmethod
    def list_received(cls, user_id, max_len = 20):
        """ Query for a list of challenges issued to a particular user """
        assert user_id is not None
        if user_id is None:
            return
        k = ndb.Key(UserModel, user_id)
        # List received challenges in ascending order by timestamp (oldest first)
        q = cls.query(ChallengeModel.destuser == k).order(ChallengeModel.timestamp)

        def ch_callback(cm):
            """ Map a favorite relation into a list of users """
            p0 = cm.key.parent()
            id0 = None if p0 is None else p0.id()
            return (id0, cm.prefs, cm.timestamp)

        for cm in q.fetch(max_len):
            yield ch_callback(cm)


class ChannelModel(ndb.Model):
    """ Models connected clients receiving notifications via a Google App Engine channel """

    # Channel id (UUID)
    chid = ndb.StringProperty()

    # Type of channel: can be 'user' or 'game'
    kind = ndb.StringProperty()

    # The associated entity, either a userid or a game uuid
    entity = ndb.StringProperty()

    # The expiration time of the channel
    expiry = ndb.DateTimeProperty()

    # When should the next cleanup of expired channels be done?
    _CLEANUP_INTERVAL = 1 # Hours
    _next_cleanup = None

    @classmethod
    def create_new(cls, kind, entity, lifetime = None):
        """ Create a new channel and return its token """
        # Every channel is assigned a random UUID
        chid = Unique.id()
        cm = cls()
        cm.chid = chid
        cm.kind = kind
        cm.entity = entity
        if lifetime is None:
            lifetime = timedelta(hours = 2)
        cm.expiry = datetime.utcnow() + lifetime
        cm.put()
        logging.info(u"Creating channel with id {0}".format(chid).encode("latin-1"))
        return channel.create_channel(chid, duration_minutes = int(lifetime.total_seconds() / 60))

    @classmethod
    def del_expired(cls):
        """ Delete all expired channels """
        logging.info(u"Deleting all expired channels".encode("latin-1"))
        now = datetime.utcnow()
        CHUNK_SIZE = 20
        while True:
            q = cls.query(ChannelModel.expiry < now)
            # Query and delete in chunks
            count = 0
            for k in q.fetch(CHUNK_SIZE, keys_only = True):
                k.delete()
                count += 1
            if count < CHUNK_SIZE:
                # Hit end of query: We're done
                break

    @classmethod
    def send_message(cls, kind, entity, msg):
        """ Send a message to all channels matching the kind and entity """

        now = datetime.utcnow()

        # Start by checking whether a cleanup of expired channels is due
        if cls._next_cleanup is None or (now > cls._next_cleanup):
            # Yes: do the cleanup
            cls.del_expired()
            # Schedule the next one
            cls._next_cleanup = now + timedelta(hours = ChannelModel._CLEANUP_INTERVAL)

        logging.info(u"Preparing send to {0} {1}".format(kind, entity).encode("latin-1"))
        CHUNK_SIZE = 20
        q = cls.query(ChannelModel.expiry > now).filter(
            ndb.AND(ChannelModel.kind == kind, ChannelModel.entity == entity))
        offset = 0
        while q is not None:
            # Query and send message in chunks
            count = 0
            for cm in q.fetch(CHUNK_SIZE, offset = offset):
                logging.info(u"Sending channel message to {0}: {1}".format(cm.chid, msg).encode("latin-1"))
                channel.send_message(cm.chid, msg)
                count += 1
            if count < CHUNK_SIZE:
                # Hit end of query: We're done
                break
            offset += count

