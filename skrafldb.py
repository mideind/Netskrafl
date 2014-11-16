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
        tiles : string
        score : integer

    GameModel:
        player0 : key into UserModel
        player1 : key into UserModel
        rack0 : string
        rack1 : string
        score0 : integer
        score1 : integer
        to_move : integer
        over : boolean
        timestamp : timestamp
        moves : array of MoveModel

"""

import logging
import uuid

from google.appengine.ext import ndb


class Unique:
    """ Wrapper for generation of unique id strings for keys """

    @classmethod
    def id(cls):
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
        user = cls.fetch(user_id)
        user.nickname = nickname
        user.inactive = inactive
        user.prefs = prefs
        user.put()

    @classmethod
    def fetch(cls, user_id):
        return cls.get_by_id(user_id)


class MoveModel(ndb.Model):
    """ Models a single move in a Game """

    coord = ndb.StringProperty()
    tiles = ndb.StringProperty()
    score = ndb.IntegerProperty(default = 0)


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

    # The moves so far
    moves = ndb.LocalStructuredProperty(MoveModel, repeated = True)

    def set_player(self, ix, user_id):
        """ Set a player key property to point to a given user, or None """
        k = None if user_id is None else ndb.Key(UserModel, user_id)
        if ix == 0:
            self.player0 = k
        elif ix == 1:
            self.player1 = k

    @classmethod
    def fetch(cls, uuid):
        """ Fetch a game model given its uuid """
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
