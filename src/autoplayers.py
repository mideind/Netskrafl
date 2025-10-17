"""

    Autoplayers - the robot inventory of the Netskrafl/Explo game

    Copyright © 2025 Miðeind ehf.
    Author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    This module defines the available autoplayers (robots) for the game.

"""

from typing import List, NamedTuple, Protocol, Dict, Any

from functools import lru_cache

from config import NETSKRAFL
from skraflplayer import AutoPlayer, AutoPlayer_Custom, AutoPlayerKwargs
from skraflmechanics import State


class AutoPlayerCtor(Protocol):

    """ AutoPlayer instance constructor """

    def __call__(self, robot_level: int, state: State, **kwargs: Any) -> AutoPlayer:
        ...


class AutoPlayerTuple(NamedTuple):

    """ Description of an available AutoPlayer """

    name: str
    description: str
    level: int
    ctor: AutoPlayerCtor
    kwargs: AutoPlayerKwargs


AutoPlayerList = List[AutoPlayerTuple]


# By convention, a robot level that always plays the highest-scoring word
TOP_SCORE = 0
# By convention, a robot level that plays medium-heavy words
MEDIUM = 8
# By convention, a robot level that uses only common words
COMMON = 15
# By convention, a robot level that is adaptive
ADAPTIVE = 20

# The available autoplayers (robots) for each locale.
# The list for each locale should be ordered in ascending order by level.

# Legacy autoplayers matching the old 'netskrafl' branch (as of Feb 3, 2025)
# Used to exactly replicate the behavior of the deployed GAE backend
AUTOPLAYERS_IS_CLASSIC: AutoPlayerList = [
    AutoPlayerTuple(
        "Fullsterkur",
        "Velur stigahæsta leik í hverri stöðu",
        TOP_SCORE,
        AutoPlayer,
        {},
    ),
    AutoPlayerTuple(
        "Miðlungur",
        "Forðast allra sjaldgæfustu orðin; velur úr 10 stigahæstu leikjum",
        MEDIUM,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="midlungur",
            pick_from=10,
        ),
    ),
    AutoPlayerTuple(
        "Amlóði",
        "Forðast sjaldgæf orð og velur úr 20 leikjum sem koma til álita",
        COMMON,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="amlodi",
            pick_from=20,
        ),
    ),
]

AUTOPLAYERS_IS: AutoPlayerList = [
    AutoPlayerTuple(
        "Fullsterkur",
        "Velur stigahæsta leik í hverri stöðu",
        TOP_SCORE,
        AutoPlayer,
        {},
    ),
    AutoPlayerTuple(
        "Miðlungur",
        "Forðast allra sjaldgæfustu orðin; velur úr 20 stigahæstu leikjum",
        MEDIUM,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="midlungur",
            pick_from=20,
        ),
    ),
    AutoPlayerTuple(
        "Hálfdrættingur",
        "Forðast sjaldgæf orð; velur úr 20 stigahæstu leikjum",
        COMMON,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="amlodi",
            pick_from=20,
            adaptive=True,
            # Cuts off the top 6 moves (20*0.3) to select typically from 14 moves
            discard_best_ratio_winning=0.3,
            # Cuts off the top 2 moves (20*0.1) to select typically from 18 moves
            discard_best_ratio_losing=0.1,
        ),
    ),
    AutoPlayerTuple(
        "Amlóði",
        "Forðast sjaldgæf orð og velur úr 30 leikjum sem koma til álita",
        ADAPTIVE,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="amlodi",
            # Considers a maximum of 30 candidate moves, in descending score order
            pick_from=30,
            adaptive=True,
            # Cuts off the top 9 moves (30*0.3) to select typically from 21 moves
            discard_best_ratio_winning=0.3,
            # Cuts off the top 6 moves (30*0.2) to select typically from 24 moves
            discard_best_ratio_losing=0.2,
        ),
    ),
]

AUTOPLAYERS_EN_US: AutoPlayerList = [
    AutoPlayerTuple(
        "Freyja",
        "Always plays the highest-scoring move",
        TOP_SCORE,
        AutoPlayer,
        {},
    ),
    AutoPlayerTuple(
        "Idun",
        "Picks one of 20 highest-scoring possible moves",
        MEDIUM,
        AutoPlayer_Custom,
        AutoPlayerKwargs(pick_from=20),
    ),
    AutoPlayerTuple(
        "Frigg",
        "Plays one of 20 possible words from a medium vocabulary",
        COMMON,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="otcwl2014.mid",
            pick_from=20,
            adaptive=True,
            discard_best_ratio_winning=0.3,  # Cuts off the top 6 moves (20*0.3)
            discard_best_ratio_losing=0.1,  # Cuts off the top 2 moves (20*0.1)
        ),
    ),
    AutoPlayerTuple(
        "Sif",
        "Plays one of 30 possible words from a basic vocabulary",
        ADAPTIVE,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="otcwl2014.aml",
            pick_from=30,
            adaptive=True,
            discard_best_ratio_winning=0.3,  # Cuts off the top 9 moves (30*0.3)
            discard_best_ratio_losing=0.2,  # Cuts off the top 6 moves (30*0.2)
        ),
    ),
]

AUTOPLAYERS_EN: AutoPlayerList = [
    AutoPlayerTuple(
        "Freyja",
        "Always plays the highest-scoring move",
        TOP_SCORE,
        AutoPlayer,
        {},
    ),
    AutoPlayerTuple(
        "Idun",
        "Picks one of 20 highest-scoring possible moves",
        MEDIUM,
        AutoPlayer_Custom,
        AutoPlayerKwargs(pick_from=20),
    ),
    AutoPlayerTuple(
        "Frigg",
        "Plays one of 20 possible words from a medium vocabulary",
        COMMON,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="sowpods.mid",
            pick_from=20,
            adaptive=True,
            discard_best_ratio_winning=0.3,
            discard_best_ratio_losing=0.1,
        ),
    ),
    AutoPlayerTuple(
        "Sif",
        "Plays one of 30 possible words from a basic vocabulary",
        ADAPTIVE,
        AutoPlayer_Custom,
        # Since Sif is adaptive, she will pick from the top 30 (=2*15)
        # moves if she has more points than the human opponent
        AutoPlayerKwargs(
            vocab="sowpods.aml",
            pick_from=30,
            adaptive=True,
            discard_best_ratio_winning=0.3,
            discard_best_ratio_losing=0.2,
        ),
    ),
]

AUTOPLAYERS_NB: AutoPlayerList = [
    AutoPlayerTuple(
        "Freyja",
        "Velger alltid trekket som gir høyest poeng",
        TOP_SCORE,
        AutoPlayer,
        {},
    ),
    AutoPlayerTuple(
        "Idunn",
        "Velger ett av de 20 trekkene som gir høyest poeng",
        MEDIUM,
        AutoPlayer_Custom,
        AutoPlayerKwargs(pick_from=20),
    ),
    AutoPlayerTuple(
        "Frigg",
        "Spiller ett av 20 mulige ord fra et middels ordtilfang",
        COMMON,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="nsf2023.mid",
            pick_from=20,
            adaptive=True,
            discard_best_ratio_winning=0.25,
            discard_best_ratio_losing=0.1,
        ),
    ),
    AutoPlayerTuple(
        "Sif",
        "Spiller ett av 24 mulige vanlige ord fra et begrenset ordtilfang",
        ADAPTIVE,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="nsf2023.aml",
            pick_from=24,
            adaptive=True,
            discard_best_ratio_winning=0.25,  # Cuts off the top 6 moves (24*0.25)
            discard_best_ratio_losing=0.125,  # Cuts off the top 3 moves (24*0.125)
        ),
    ),
]

AUTOPLAYERS_NN: AutoPlayerList = [
    AutoPlayerTuple(
        "Freyja",
        "Vel alltid trekket som gjev høgast poeng",
        TOP_SCORE,
        AutoPlayer,
        {},
    ),
    AutoPlayerTuple(
        "Idunn",
        "Vel eitt av dei 20 trekka som gjev høgast poeng",
        MEDIUM,
        AutoPlayer_Custom,
        AutoPlayerKwargs(pick_from=20),
    ),
    AutoPlayerTuple(
        "Frigg",
        "Spelar eitt av 20 moglege ord frå eit middels ordtilfang",
        COMMON,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="nynorsk2024.mid",
            pick_from=20,
            adaptive=True,
            discard_best_ratio_winning=0.25,
            discard_best_ratio_losing=0.1,
        ),
    ),
    AutoPlayerTuple(
        "Sif",
        "Spelar eitt av 24 moglege vanlege ord frå eit avgrensa ordtilfang",
        ADAPTIVE,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="nynorsk2024.aml",
            pick_from=24,
            adaptive=True,
            discard_best_ratio_winning=0.25,  # Cuts off the top 6 moves (24*0.25)
            discard_best_ratio_losing=0.125,  # Cuts off the top 3 moves (24*0.125)
        ),
    ),
]

AUTOPLAYERS_PL: AutoPlayerList = [
    AutoPlayerTuple(
        "Kopernik",
        "Zawsze gra ruch z najwyższym wynikiem",
        TOP_SCORE,
        AutoPlayer,
        {},
    ),
    AutoPlayerTuple(
        "Maria",
        "Wybiera jeden z 20 najwyżej punktowanych ruchów",
        MEDIUM,
        AutoPlayer_Custom,
        AutoPlayerKwargs(pick_from=20),
    ),
    AutoPlayerTuple(
        "Stefan",
        "Gra jednym z 20 możliwych słów ze średniego słownika",
        COMMON,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="osps37.mid",
            pick_from=20,
            adaptive=True,
            discard_best_ratio_winning=0.3,
            discard_best_ratio_losing=0.1,
        ),
    ),
    AutoPlayerTuple(
        "Wisława",
        "Gra jednym z 30 możliwych słów z podstawowego słownika",
        ADAPTIVE,
        AutoPlayer_Custom,
        AutoPlayerKwargs(
            vocab="osps37.aml",
            pick_from=30,
            adaptive=True,
            discard_best_ratio_winning=0.3,  # Cuts off the top 9 moves (30*0.3)
            discard_best_ratio_losing=0.2,  # Cuts off the top 6 moves (30*0.2)
        ),
    ),
]

AUTOPLAYERS: Dict[str, AutoPlayerList] = {
    # Icelandic
    "is": AUTOPLAYERS_IS_CLASSIC if NETSKRAFL else AUTOPLAYERS_IS,
    # U.S. English
    "en_US": AUTOPLAYERS_EN_US,
    # Default English (UK & Rest Of World)
    "en": AUTOPLAYERS_EN,
    # Norwegian (Bokmål)
    "nb": AUTOPLAYERS_NB,
    # Norwegian (Nynorsk)
    "nn": AUTOPLAYERS_NN,
    # Polish
    "pl": AUTOPLAYERS_PL,
}


@lru_cache(maxsize=None)
def autoplayer_for_locale(locale: str) -> AutoPlayerList:
    """Return the list of autoplayers that are available
    for the given locale"""
    locale = locale.replace("-", "_")
    apl = AUTOPLAYERS.get(locale)
    if apl is None:
        if "_" in locale:
            # Lookup the major locale, i.e. "en" if "en_US"
            apl = AUTOPLAYERS.get(locale.split("_")[0])
        if apl is None:
            # Fall back to English
            apl = AUTOPLAYERS.get("en")
    assert apl is not None
    return apl


@lru_cache(maxsize=None)
def autoplayer_for_level(locale: str, level: int) -> AutoPlayerTuple:
    """Return the strongest autoplayer that is
    at or below the given difficulty. Note that a higher
    level number requests a weaker player."""
    apl = autoplayer_for_locale(locale)
    i = len(apl)
    while i > 0:
        i -= 1
        if level >= apl[i].level:
            return apl[i]
    return apl[0]


def autoplayer_create(state: State, robot_level: int = TOP_SCORE) -> AutoPlayer:
    """Create an AutoPlayer instance for the state's locale,
    of the desired ability level"""
    apl = autoplayer_for_level(state.locale, robot_level)
    return apl.ctor(robot_level, state, **apl.kwargs)


@lru_cache(maxsize=None)
def autoplayer_name(locale: str, level: int) -> str:
    """ Return the autoplayer name for a given level """
    return autoplayer_for_level(locale, level).name
