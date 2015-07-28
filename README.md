## Netskrafl - an Icelandic crossword game website

### English summary

This repository contains the implementation of an Icelandic crossword game
inspired by SCRABBLE(tm).
The game is accessible on the web at [http://netskrafl.is](http://netskrafl.is) and
[http://netskrafl.appspot.com](http://netskrafl.appspot.com)

The game backend is implemented in Python 2.7 for Google AppEngine but the core code is also
compatible with Python 3.x and PyPy.

The frontend is a tablet- and smartphone-friendly web client in HTML5 and JavaScript connecting
via Ajax to a Flask-based web server on the backend.

The game contains a robot crossword player written in Python. The algorithm is based
on Appel & Jacobson's classic paper
["The World's Fastest Scrabble Program"](http://www.cs.cmu.edu/afs/cs/academic/class/15451-s06/www/lectures/scrabble.pdf).
At maximum strength level, the robot always plays the highest-scoring move possible but additional and
alternative strategies can be plugged in relatively easily. At the lowest strength level, the
robot is limited to a set of common words, about a quarter of the size of the entire word database.

The software has a range of features such as immediate tile-by-tile feedback on word validity and score,
real-time synchronized games with clocks, Elo scoring of players, an online chat window,
and the ability to view player track records.

The game uses a word database encoded in a Directed Acyclic Word Graph (DAWG).
For Icelandic, the graph contains almost 2.3 million word forms. Further information
about the DAWG implementation can be found in README.md in the
[Skrafl repository](https://github.com/vthorsteinsson/Skrafl) on GitHub.

The game mechanics are mostly found in ```skraflmechanics.py```.

The robot player is implemented in ```skraflplayer.py```.

The DAWG navigation code is in ```dawgdictionary.py```.

Particulars to the Icelandic language are found in ```languages.py```.

The main Flask web server is in ```netskrafl.py```.

The Game and User classes are found in ```skraflgame.py```.

The persistence layer, using the schemaless App Engine NDB database, is in ```skrafldb.py```.

The client JavaScript code is in ```static/netskrafl.js```.

The various Flask HTML templates are found in ```templates/*.html```.

The word database is in ```resources/ordalisti.text.dawg```.


### To build and run locally

1. Download the [Google App Engine SDK](https://cloud.google.com/appengine/downloads) for Python.

2. Run ```npm install``` to install node dependencies.

3. Run ```grunt watch```. Note that some release files, i.e. ```*.css``` and ```*.min.js``` are only created when the corresponding source files, i.e. ```*.less``` and ```*.js```, are modified.

4. Run ```python dawgbuilder.py``` to generate the DAWG ```*.pickle``` files.

5. Run ```pip install -t lib -r requirements.txt``` to install Python packages for Google Apps to use.

6. Create a secret session key for Flask in `resources/secret_key.bin` (see [How to generate good secret keys](http://flask.pocoo.org/docs/0.10/quickstart/), you need to scroll down to find the heading).

7. Run either ```runserver.bat``` or ```runserver.sh```.

### Author
Vilhjalmur Thorsteinsson


*SCRABBLE is a registered trademark. This software or its author are in no way affiliated
with or endorsed by the owners or licensees of the SCRABBLE trademark.*
