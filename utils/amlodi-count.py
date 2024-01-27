
# Utility program to read the vocabulary of the easiest robot,
# Amlóði, annotate each word with its frequency in the icegrams
# trigrams database, and output the words in order of increasing
# frequency.

from typing import List, Tuple

import sys
import os
import functools
import heapq

import icegrams

basepath = os.path.dirname(__file__)
fpath = functools.partial(os.path.join, basepath)

# Read the ordalisti.aml.sorted.txt file, where each word occupies one line.
# Look up each word in the icegrams trigrams database, and store the word
# together with its frequency. Sort the words by frequency, and output
# the words in order of increasing frequency.

full_path = fpath("../resources/ordalisti.aml.sorted.txt")
ngrams = icegrams.ngrams.Ngrams()
h: List[Tuple[int, str]] = []

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

try:
    with open(full_path, "r", encoding="utf-8") as f:
        for line in f:
            word = line.strip()
            if not word:
                continue
            freq = ngrams.freq(word)
            # Add the (word, freq) tuple to a sorted heap.
            heapq.heappush(h, (freq, word))

    # Pop the (word, freq) tuples from the heap in order of increasing frequency.
    while h:
        freq, word = heapq.heappop(h)
        print(f"{word} {freq}")

except IOError:
    print(f"Cannot open vocabulary file {full_path}", file=sys.stderr)
    sys.exit(1)

