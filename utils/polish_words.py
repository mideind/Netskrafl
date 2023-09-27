
# Utility program to read a list of frequent
# Polish words from the file polish_frequent_words.txt,
# which are in descending order by frequency. Each
# line contains the frequency count as a number, followed
# by a space, and then the word in question.
# We want to read the file and output all valid words that
# are at least 3 characters long and no longer than 12 characters.
# We want to limit the output to N words, where N is a
# command-line parameter.

from typing import Set

import sys
import os
import functools

basepath = os.path.dirname(__file__)
fpath = functools.partial(os.path.join, basepath)

# Check for the correct number of command-line parameters.
if len(sys.argv) != 2:
    print("Usage: python polish_words.py N", file=sys.stderr)
    sys.exit(1)

# Get the number of words to output from the command-line.
try:
    num_words = int(sys.argv[1])
except ValueError:
    print("The number of words must be an integer", file=sys.stderr)
    sys.exit(1)

# Read the osps37.txt file, containing valid Polish words,
# into a Python set.
full_path = fpath("../resources/osps37.txt")
try:
    f = open(full_path, "r", encoding="utf-8")
except IOError:
    print(f"Cannot open vocabulary file {full_path}", file=sys.stderr)
    sys.exit(1)

# Read the file into a set
polish_words = set(s.lower() for line in f if (s := line.strip()))
f.close()

# Open the output file
full_path = fpath(f"../resources/polish_top_{num_words}.txt")
try:
    out_f = open(full_path, "w", encoding="utf-8", newline="\n")
except IOError:
    print(f"Cannot open output file {full_path}", file=sys.stderr)
    sys.exit(1)

# Create the correct path to the input file.
# The file is located in the resources directory, one
# level up from the src directory where this source file
# is located.
# full_path = os.path.join(basepath, "../resources/polish_frequent_words.txt")
full_path = "/Users/Lenovo/Dropbox/resources/polish_frequent_words.txt"

# Open the file for reading.
try:
    f = open(full_path, "r", encoding="utf-8")
except IOError:
    print(f"Cannot open input file {full_path}", file=sys.stderr)
    sys.exit(1)

# Read the file, one line at a time.
# We will use a counter to keep track of how many words
# we have output so far.
result: Set[str] = set()

for line in f:
    # Split the line into a list of words.
    words = line.split()
    # The first word is the frequency count, which we don't need.
    # The second word is the Polish word.
    polish_word = words[1]
    # Check if the word is at least 3 characters long, at most 12 characters long,
    # and is in the vocabulary.
    if not (3 <= len(polish_word) <= 12):
        continue
    u = polish_word.lower()
    if u not in polish_words:
        continue
    # Output the word.
    result.add(u)
    # Check if we have output the required number of words.
    if len(result) >= num_words:
        break

# Close the input file.
f.close()

ALPHABET = "aąbcćdeęfghijklłmnńoóprsśtuwyzźż"

# Sort the result list, using the Polish alphabet.
rlist = list(result)
rlist.sort(key=lambda w: tuple(map(ALPHABET.index, w)))

# Output the result list
for w in rlist:
    print(w, file=out_f)

# Close the output file.
out_f.close()
