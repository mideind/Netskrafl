
# Utility program to read a list of frequent
# Polish words from the file polish_frequent_words.txt,
# which are in descending order by frequency. Each
# line contains the frequency count as a number, followed
# by a space, and then the word in question.
# We want to read the file and output all valid words that
# are at least 3 characters long and no longer than 12 characters.
# We want to limit the output to N words, where N is a
# command-line parameter.

from collections import defaultdict
from typing import Set

import sys
import os
import functools

basepath = os.path.dirname(__file__)
fpath = functools.partial(os.path.join, basepath)

ALPHABET = "aąbcćdeęfghijklłmnńoóprsśtuwyzźż"
DEFAULT_INPUT_FILE = fpath("../resources/polish_frequent_words.txt")


def read_polish_vocabulary() -> Set[str]:
    """Read the osps37.txt file, containing valid Polish words,
    into a Python set."""
    vocabulary_file = fpath("../resources/osps37.txt")
    try:
        voc_f = open(vocabulary_file, "r", encoding="utf-8")
    except IOError:
        print(f"Cannot open vocabulary file {vocabulary_file}", file=sys.stderr)
        return set()
    polish_words = set(s.lower() for line in voc_f if (s := line.strip()))
    voc_f.close()
    return polish_words


def generate_top_words(num_words: int, input_file: str) -> bool:
    """Generate a list of top Polish words."""

    if not (polish_words := read_polish_vocabulary()):
        return False

    # Open the output file
    output_file = fpath(f"../resources/polish_top_{num_words}.txt")
    try:
        out_f = open(output_file, "w", encoding="utf-8", newline="\n")
    except IOError:
        print(f"Cannot open output file {output_file}", file=sys.stderr)
        return False

    # Open the input file for reading
    try:
        in_f = open(input_file, "r", encoding="utf-8")
    except IOError:
        print(f"Cannot open input file {input_file}", file=sys.stderr)
        return False

    # Read the file, one line at a time.
    # We will use a counter to keep track of how many words
    # we have output so far.
    result: Set[str] = set()

    for line in in_f:
        # Split the line into a list of words
        words = line.split()
        # The first word is the frequency count, which we don't need.
        # The second word is the Polish word
        polish_word = words[1]
        # Check if the word is at least 3 characters long, at most 12 characters long,
        # and is in the vocabulary
        if not (3 <= len(polish_word) <= 12):
            continue
        u = polish_word.lower()
        if u not in polish_words:
            continue
        # Output the word
        result.add(u)
        # Check whether we have output the required number of words
        if len(result) >= num_words:
            break

    # Close the input file.
    in_f.close()

    # Sort the result list, using the Polish alphabet.
    rlist = list(result)
    rlist.sort(key=lambda w: tuple(map(ALPHABET.index, w)))

    # Output the result list
    for w in rlist:
        print(w, file=out_f)

    # Close the output file.
    out_f.close()
    return True


def read_pol_news(input_file: str) -> bool:
    """Read a file with words occurring in Polish news, outputting
    a filtered word frequency list in descending order. The input file
    contains lines with three columns, separated by whitespace:
    an integer index, the word, and the frequency count. We want
    to read each line, ignore the index, ignore all words that contain
    characters other than those in ALPHABET, build a frequency dictionary
    of the remaining words and output that in descending order of frequency
    to an output text file, in UTF-8.
    """
    # Open the input file for reading
    try:
        in_f = open(input_file, "r", encoding="utf-8")
    except IOError:
        print(f"Cannot open input file {input_file}", file=sys.stderr)
        return False
    # Open the output file
    output_file = fpath("../resources/pol_news_freq.txt")
    try:
        out_f = open(output_file, "w", encoding="utf-8", newline="\n")
    except IOError:
        print(f"Cannot open output file {output_file}", file=sys.stderr)
        return False
    # Read the Polish vocabulary
    if not (polish_words := read_polish_vocabulary()):
        return False

    # Read the input file, one line at a time
    freq_dict: defaultdict[str, int] = defaultdict(int)
    for line in in_f:
        # Split the line into a list of words
        words = line.split()
        # The first word is the index, which we don't need.
        # The second word is the Polish word
        # The last word is the frequency count
        if len(words) != 3:
            # Reject malformed lines (probably multiple words)
            continue
        polish_word = words[1]
        if not (3 <= len(polish_word) <= 15):
            # Only consider words between 3 and 15 characters long
            continue
        freq = int(words[2])
        # Check whether the word is in the Polish vocabulary
        if polish_word not in polish_words:
            # Check whether its lowercase version is in the vocabulary
            polish_word_lower = polish_word.lower()
            if polish_word_lower == polish_word:
                continue
            polish_word = polish_word_lower
            if polish_word not in polish_words:
                continue
        # Update the frequency dictionary
        freq_dict[polish_word] += freq
    # Close the input file.
    in_f.close()
    # Sort the frequency dictionary by frequency in descending order
    sorted_freq = sorted(freq_dict.items(), key=lambda x: x[1], reverse=True)
    # Output the sorted frequency list
    for word, freq in sorted_freq:
        print(f"{freq} {word}", file=out_f)
    # Close the output file.
    out_f.close()
    return True


# read_pol_news(sys.argv[1])
# sys.exit(0)


# Main program
if __name__ == "__main__":
    # Check for the correct number of command-line parameters.
    nargs = len(sys.argv)
    if not (2 <= nargs <= 3):
        print("Usage: python polish_words.py N [input file]", file=sys.stderr)
        sys.exit(1)

    # Get the number of words to output from the command-line.
    try:
        num_words = int(sys.argv[1])
    except ValueError:
        print("The number of words must be an integer", file=sys.stderr)
        sys.exit(1)

    input_file: str
    if nargs == 3:
        input_file = sys.argv[2]
    else:
        input_file = DEFAULT_INPUT_FILE

    if not generate_top_words(num_words, input_file):
        sys.exit(1)
