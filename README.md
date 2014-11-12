## Netskrafl - an Icelandic SCRABBLE(tm) website

### English summary

This repository contains the implementation of an Icelandic SCRABBLE(tm)-like word game.
The game is accessible on the web at [http://netskrafl.appspot.com](http://netskrafl.appspot.com)

The game backend is implemented in Python 2.7 for Google AppEngine but also runs under
Python 3.x and PyPy.

The frontend is a web client in HTML5 and JavaScript connecting via Ajax to a Flask-based web
server on the backend.

The game contains a SCRABBLE(tm)-playing robot written in Python. The algorithm is based
on Appel & Jacobson's classic paper "The World's fastest Scrabble Playing Program".

The game is based on a word database encoded in a Directed Acyclic Word Graph (DAWG).
For Icelandic, the graph contains almost 2.3 million word forms.

The game mechanics are mostly found in ```skraflmechanics.py```.
The robot player is implemented in ```skraflplayer.py```.
The DAWG navigation code is in ```dawgdictionary.py```.
Particulars to the Icelandic language are found in ```languages.py```.
The main Flask web server is in ```netskrafl.py```.
The client JavaScript code is in ```static/netskrafl.js```.
The word database is in ```resources/ordalisti.text.dawg```.

*SCRABBLE is a registered trademark. This software or its author are in no way affiliated
with or endorsed by the owners or licensees of the SCRABBLE trademark.*


### Author
Vilhjalmur Thorsteinsson

