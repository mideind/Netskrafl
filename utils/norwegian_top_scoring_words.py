
# Utility program to create a list of top-scoring Norwegian
# words, according to the Explo letter values.

import sys
import os
import functools

basepath = os.path.dirname(__file__)
fpath = functools.partial(os.path.join, basepath)


"""
The new, improved Norwegian tile set was designed
by Taral Guldahl Seierstad and is used here
by kind permission. Thanks Taral!
"""

SCORES = {
    "a": 1,
    "b": 3,
    "c": 8,
    "d": 2,
    "e": 1,
    "f": 4,
    "g": 2,
    "h": 3,
    "i": 1,
    "j": 5,
    "k": 2,
    "l": 1,
    "m": 2,
    "n": 1,
    "o": 2,
    "p": 3,
    "r": 1,
    "s": 1,
    "t": 1,
    "u": 3,
    "v": 3,
    "w": 10,
    "y": 3,
    "æ": 6,
    "ø": 4,
    "å": 3,
}
ALPHABET = frozenset(SCORES.keys())


def valid_word(word: str) -> bool:
    """Check if a word is valid according to the Norwegian alphabet"""
    return 3 <= len(word) <= 15 and all(c in ALPHABET for c in word)


def generate_top_scoring_words() -> None:
    """Read the nsf2023.txt file, containing valid Norwegian words,
    into a Python set."""
    vocabulary_file = fpath("../resources/nsf2023.txt")
    try:
        voc_f = open(vocabulary_file, "r", encoding="utf-8")
    except IOError:
        print(f"Cannot open vocabulary file {vocabulary_file}", file=sys.stderr)
        return
    norwegian_words = set(s for line in voc_f if (s := line.strip()) and valid_word(s))
    voc_f.close()

    # Calculate the score of each word, by summing the scores of its letters
    word_scores = {word: sum(SCORES[c] for c in word) for word in norwegian_words}
    # Sort the list in descending order of score
    sorted_words = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)
    # Output the sorted list to a CSV file
    output_file = fpath("../resources/norwegian_top_scoring_words.csv")
    try:
        out_f = open(output_file, "w", encoding="utf-8", newline="\n")
    except IOError:
        print(f"Cannot open output file {output_file}", file=sys.stderr)
        return
    for word, score in sorted_words:
        print(f"{score},{word}", file=out_f)
    out_f.close()


# Main program
if __name__ == "__main__":
    generate_top_scoring_words()
