"""

    Test fixtures for riddle validation tests
    Copyright © 2025 Miðeind ehf.

    This module contains real riddle data for testing the riddle
    validation system.

"""

from typing import TypedDict, List


class RiddleSolutionDict(TypedDict):
    """A riddle solution"""

    move: str
    coord: str
    score: int
    description: str


class RiddleAnalysisDict(TypedDict):
    """Analysis of a riddle"""

    totalMoves: int
    bestMoveScore: int
    secondBestMoveScore: int
    averageScore: float
    isBingo: bool


class RiddleFixtureDict(TypedDict):
    """A complete riddle fixture for testing"""

    board: List[str]
    rack: str
    solution: RiddleSolutionDict
    analysis: RiddleAnalysisDict


# Riddle 1: Bingo move (vertical placement, high score)
# Solution: "þrekraun" at 1D (vertical), score 104
RIDDLE_1: RiddleFixtureDict = {
    "board": [
        "...íshemi......",
        ".....ý.........",
        ".....r.........",
        "þaGi.skyntum...",
        "...matur.r.....",
        ".........é.....",
        ".........á....s",
        "...dUlræðs....n",
        "...ú..........i",
        "...n..........f",
        "..skæfanna....f",
        "...r......gopna",
        "...a........l..",
        "...g...aðalbót.",
        ".kvittið....g..",
    ],
    "rack": "uaenrrk",
    "solution": {
        "move": "þrekraun",
        "coord": "1D",
        "score": 104,
        "description": "1D þrekraun",
    },
    "analysis": {
        "totalMoves": 833,
        "bestMoveScore": 104,
        "secondBestMoveScore": 78,
        "averageScore": 10.914765906362545,
        "isBingo": True,
    },
}


# Riddle 2: Short strategic word (vertical placement, high score with few tiles)
# Solution: "ykju" at 8L (vertical from description), score 79
# Note: The coord field "12H" appears to be incorrect; the description "8L" is the actual coordinate
RIDDLE_2: RiddleFixtureDict = {
    "board": [
        ".......æ.h....t",
        ".s.....ð.é....ú",
        ".laufaásar....b",
        ".e..o..t.aktívu",
        ".i..x..i.ð.....",
        ".p..i...miðlagi",
        "as..n..........",
        "r..ósáran......",
        "ð....tekur.....",
        "r...dunar......",
        "æ.......l......",
        "n.......s......",
        "s..............",
        "...............",
        "...............",
    ],
    "rack": "ykjitþu",
    "solution": {
        "move": "ykju",
        "coord": "8L",  # Using coordinate from description field
        "score": 79,
        "description": "8L ykju",
    },
    "analysis": {
        "totalMoves": 182,
        "bestMoveScore": 79,
        "secondBestMoveScore": 38,
        "averageScore": 14.164835164835164,
        "isBingo": False,
    },
}


# Riddle 3: Another bingo move (horizontal placement, high score)
# Solution: "frumtala" at C1 (horizontal), score 82
RIDDLE_3: RiddleFixtureDict = {
    "board": [
        ".......s......M",
        ".......j......e",
        ".......a......i",
        ".......l.systan",
        "....þruskar...t",
        "...gré...n...ha",
        "....æ....n...ak",
        "..dólpur.s...fa",
        "..i.u....æ...i.",
        "..l.ð....i.....",
        "..k.u..........",
        ".táLmunar......",
        "..a............",
        "...............",
        "...............",
    ],
    "rack": "atlmrfu",
    "solution": {
        "move": "frumtala",
        "coord": "C1",
        "score": 82,
        "description": "C1 frumtala",
    },
    "analysis": {
        "totalMoves": 1291,
        "bestMoveScore": 82,
        "secondBestMoveScore": 66,
        "averageScore": 10.760650658404337,
        "isBingo": True,
    },
}


# List of all riddle fixtures for parametrized tests
ALL_RIDDLES = [RIDDLE_1, RIDDLE_2, RIDDLE_3]
