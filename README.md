## Netskrafl - an Icelandic crossword game website

[![Join the chat at https://gitter.im/Netskrafl/Lobby](https://badges.gitter.im/Netskrafl/Lobby.svg)](https://gitter.im/Netskrafl/Lobby?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

### English summary

This repository contains the implementation of an Icelandic crossword game
in the genre of SCRABBLE®. The game, which is free-to-play, is accessible
on the web at [https://malstadur.mideind.is/netskrafl](https://malstadur.mideind.is/netskrafl).

![Screenshot from mobile UI](/resources/ScreencapMobile.PNG?raw=true "Screenshot from mobile UI")

The game backend is implemented in Python 3.11 for the
[Google App Engine Standard Environment](https://cloud.google.com/appengine/docs/standard).

The frontend is a tablet- and smartphone-friendly web client in HTML5
and JavaScript connecting via Ajax to a Flask-based web server on the backend.

The game contains a robot crossword player written in Python. The algorithm is based
on Appel & Jacobson's classic paper
["The World's Fastest Scrabble Program"](http://www.cs.cmu.edu/afs/cs/academic/class/15451-s06/www/lectures/scrabble.pdf).
At maximum strength level, the robot always plays the highest-scoring move
possible but additional and alternative strategies can be plugged in relatively easily.
At the lowest strength level, the robot is limited to a set of common words, about a
quarter of the size of the entire word database.

The software has a range of features such as immediate tile-by-tile feedback
on word validity and score,
real-time synchronized games with clocks, Elo scoring of players, an online chat window,
and the ability to view player track records.

The game uses a word database encoded in a Directed Acyclic Word Graph (DAWG).
For Icelandic, the graph contains 2.4 million word forms. Further information
about the DAWG implementation can be found in README.md in the
[Skrafl repository](https://github.com/vthorsteinsson/Skrafl) on GitHub.

The source code for the game server is located in the ```src/``` directory.
The main source files are as follows:

The main entry point for the Flask web server is in ```main.py```.

The game mechanics are mostly found in ```skraflmechanics.py```.

The robot player is implemented in ```skraflplayer.py```.

The DAWG navigation code is in ```dawgdictionary.py```.

Language-specific tile sets, bags and vocabularies are handled in ```languages.py```.

The Game and User classes are found in ```skraflgame.py``` and ```skrafluser.py```, respectively.

The persistence layer, using the schemaless App Engine NDB database, is in ```skrafldb.py```.

The various Flask HTML templates are found in ```templates/*.html```.

The DAWG-compressed vocabularies are stored in ```resources/*.bin.dawg```.


### Client Authentication

The Netskrafl server supports three types of clients, each with its own authentication mechanism:

#### 1. Direct Web Access (Same-Origin)

The classic Netskrafl web interface served directly from the server. Users authenticate
via OAuth2 (Google, Facebook, or Apple), and the server maintains session state using
secure HTTP-only cookies with `SameSite=Lax`.

- **Auth mechanism**: Flask session cookies
- **Login endpoints**: `/login` (initiates OAuth2 flow), `/oauth2callback`
- **Session lifetime**: 90 days

#### 2. Explo Mobile App (React Native)

The Explo mobile app (iOS/Android) uses the same OAuth2 providers but through
native mobile SDKs. After initial authentication, the server issues an Explo JWT token
that can be used for subsequent logins without repeating the OAuth2 flow.

- **Auth mechanism**: Session cookies (stored in native HTTP client)
- **Login endpoints**: `/oauth_google`, `/oauth_apple`, `/oauth_fb`, `/oauth_explo`
- **Token lifetime**: 30 days (configurable)

#### 3. Cross-Origin Web Clients (e.g., Málstaður)

Third-party web applications that embed Netskrafl functionality cannot use cookies
due to browser `SameSite` restrictions on cross-origin requests. Instead, these clients
authenticate using Bearer tokens in the `Authorization` header.

- **Auth mechanism**: JWT Bearer token (`Authorization: Bearer <token>`)
- **Login endpoint**: `/login_malstadur` (returns JWT token in response)
- **Token lifetime**: 30 days (configurable)

**Authentication flow for cross-origin clients:**

1. Client calls `POST /login_malstadur` with user credentials, a signed JWT from the parent application,
   and `bearer_auth: true` to opt in to Bearer token authentication
2. Server validates the JWT, finds or creates the user, and returns a response containing an Explo `token`
3. Client stores the token and includes it in subsequent API requests as `Authorization: Bearer <token>`
4. Server validates the token on each request via the `session_user()` function

The `bearer_auth` flag controls whether the server sets a session cookie:
- `bearer_auth: true` - No session cookie is set; client must use Bearer token for subsequent requests
- `bearer_auth: false` or omitted - Session cookie is set for backwards compatibility with legacy clients

The CORS configuration allows all origins with the `Authorization` header permitted,
enabling cross-origin clients to authenticate without cookies.


### To build and run locally

#### Follow these steps:

0. Install [Python 3.11](https://www.python.org/downloads/release/python-3116/),
preferably in a [virtualenv](https://pypi.python.org/pypi/virtualenv).

1. Download the [Google App Engine SDK](https://cloud.google.com/appengine/downloads)
(GAE) for Python and follow the installation instructions.

2. ```git clone https://github.com/mideind/Netskrafl``` to your GAE application directory.

3. Install the Python packages. For development, create a virtualenv with
[uv](https://docs.astral.sh/uv/) and install the dev requirements, which
include the runtime packages (`requirements.txt`, the ones deployed to GAE),
the PostgreSQL backend packages (`requirements-pg.txt`, used by the container
image) and the local tooling (icegrams, pytest, pyright):
   ```
   uv venv --python 3.11 venv
   uv pip install --python venv/bin/python -r requirements-dev.txt
   ```

4. Run ```python utils/dawgbuilder.py all``` to generate the DAWG ```*.bin.dawg``` files. This may
take a couple of minutes.

5. You will need a secret session key for Flask. The secret session key is stored in Google Cloud secret manager.
For information on Flask sessions see [Flask Session documentation](https://flask.palletsprojects.com/en/3.0.x/quickstart/#sessions).
For further details on secrets stored and used at runtime, see the
[Google Cloud Secret Manager documentation](https://cloud.google.com/secret-manager/docs/creating-and-accessing-secrets), and the source file ```src/secret_manager.py```.

6. Install [Node.js](https://nodejs.org/en/download/) if you haven't already.
Run ```npm install``` to install Node dependencies. Run ```npm install grunt -g grunt-cli```
to install Grunt and its command line interface globally.

7. In a separate terminal window, but in the Netskrafl directory, run ```grunt make```.
Then run ```grunt``` to start watching changes of js and css files.

8. Run either ```runserver.bat``` or ```./runserver.sh```.

#### Or, alternatively:

Run ```./setup-dev.sh``` (tested on Debian based Linux and OS X).


### Deploying to Google App Engine

The project has multiple deployment targets, each with its own deploy script and
App Engine configuration file. All deployments use the `--no-promote` flag, meaning
the new version is deployed but does not receive traffic until manually promoted
via the Google Cloud Console.

**Prerequisites:**
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed and configured
- Appropriate credentials in the `resources/` directory
- Run tests before deploying (see CLAUDE.md for test configuration)

**Deployment commands:**

| Target | Script | Project | Description |
|--------|--------|---------|-------------|
| Netskrafl | `./deploy-netskrafl.sh default <version>` | netskrafl | Production Icelandic web game |
| Netskrafl Demo | `./deploy-demo.sh default <version>` | netskrafl | Demo/staging environment |
| Explo Dev | `./deploy-explo.sh default <version>` | explo-dev | Explo development/testing |
| Explo Live | `./deploy-explo-live.sh default <version>` | explo-live | Explo production |

Each script:
1. Builds frontend assets via `grunt make`
2. Deploys to Google App Engine with the specified version
3. For Netskrafl, optionally updates the `update_online_status` Cloud Scheduler job

**Example:**
```bash
# Deploy version "v42" to Netskrafl production
./deploy-netskrafl.sh default v42

# Deploy to Explo development
./deploy-explo.sh default v42
```

After deployment, promote the new version to receive traffic in the
[Google Cloud Console](https://console.cloud.google.com/appengine/versions).


### Generating a new vocabulary file

The Icelandic vocabularies are generated from the *Kristínarsnið* (augmented
format) of the [Icelandic BÍN database](https://bin.arnastofnun.is/gogn/mimisbrunnur/)
(read the licensing information!), which can be fetched as follows:

```bash
$ wget -O KRISTINsnid.csv.zip https://bin.arnastofnun.is/django/api/nidurhal/?file=KRISTINsnid.csv.zip
$ unzip KRISTINsnid.csv.zip
$ rm KRISTINsnid.csv.sha256sum
```

The following instructions assume a PostgreSQL database with the
```is-IS``` ICU collation, for example created with
```createdb --locale-provider=icu --icu-locale=is-IS --template=template0 bin```.
The fields of *Kristínarsnið* are documented
[here in English](https://bin.arnastofnun.is/DMII/LTdata/k-format/).
The following ```psql``` commands create a table for the data and copy the
downloaded file into it:

```sql
begin transaction read write;
create table kristinarsnid (
   stofn varchar, utg integer, ordfl varchar, fl varchar, einkunn integer,
   malsnid varchar, malfraedi varchar, millivisun integer, birting varchar,
   ordmynd varchar, beyging varchar, beinkunn integer, bmalsnid varchar,
   bgildi varchar, aukafletta varchar
);
\copy kristinarsnid from 'KRISTINsnid.csv' with (format csv, delimiter ';')
commit;
```

BÍN grades each headword (```einkunn```) and each inflectional form
(```beinkunn```). Grade 1 is the norm, while grades 4 and above mark
spellings that BÍN considers incorrect, such as *svasi* (correctly *Svasi*)
or *allskonar* (correctly *alls konar*). These are excluded, except for
widely used variant spellings (such as *pítsa* and *kortér*) whose headwords
are listed in ```resources/ordalisti.variants.txt```. That file was compiled
by hand in September 2026 from the grade 4 headwords that had word forms in
the frequency-filtered Amlóði vocabulary, keeping only those common enough
that most players will expect them to be accepted. Load it as follows:

```sql
begin transaction read write;
create table ordalisti_variants (stofn varchar, ordfl varchar);
\copy ordalisti_variants from '~/github/Netskrafl/resources/ordalisti.variants.txt' with (format csv, delimiter ';')
commit;
```

To generate a new vocabulary file (```ordalisti.full.sorted.txt```),
first use the following ```psql``` command to create a view:

```sql
begin transaction read write;
create or replace view skrafl as
   select stofn, utg, ordfl, fl, ordmynd, beyging from kristinarsnid
   where ordmynd ~ '^[aábdðeéfghiíjklmnoóprstuúvxyýþæö]{3,15}$'
   and fl <> 'bibl'
   and not ((beyging like 'SP-%-FT') or (beyging like 'SP-%-FT2'))
   and (coalesce(einkunn, 0) < 4
      or (stofn, ordfl) in (select stofn, ordfl from ordalisti_variants))
   and coalesce(beinkunn, 0) < 4;
commit;
```

To explain, this extracts all 3-15 letter word forms containing only Icelandic lowercase
alphabetic characters, omitting the *bibl* (Biblical) category (which contains mostly
obscure proper names and derivations thereof), plural question
forms (*spurnarmyndir í fleirtölu*) and incorrect spellings.

Then, to generate the vocabulary file from the ```psql``` command line:

```sql
\copy (select distinct ordmynd from skrafl order by ordmynd) to '~/github/Netskrafl/resources/ordalisti.full.sorted.txt';
```

The robot *Miðlungur* uses a stricter subset of BÍN: only headwords and
inflectional forms of grade 1 (except singular question forms, which BÍN
grades 2), no archaic, poetic, dialectal, rare, erroneous or offensive
headwords or forms (by ```malsnid``` and ```bmalsnid```), no subordinate
variant forms (```bgildi = 'VIK'```), and no words longer than 10 letters.
Define it with the following view:

```sql
begin transaction read write;
create or replace view ksnid_midlungur as
	select stofn, utg, ordfl, fl, ordmynd, beyging
	from kristinarsnid
	where (malsnid is null or (malsnid <> ALL (ARRAY['SKALD','GAM','FORN','URE','STAD','SJALD','OTOK','VILLA','NID','OVID'])))
		and (bmalsnid is null or (bmalsnid <> ALL (ARRAY['SKALD','GAM','FORN','URE','STAD','SJALD','OTOK','VILLA','NID','OVID'])))
		and (bgildi is null or bgildi <> 'VIK')
		and einkunn = 1
		and (beinkunn = 1 or (beyging like 'SP-%' and beinkunn = 2));
commit;
```

You can then use the ```ksnid_midlungur``` view as the underlying table to
generate a new vocabulary file (```ordalisti.mid.sorted.txt```):

```sql
begin transaction read write;
create or replace view skrafl_midlungur as
   select stofn, utg, ordfl, fl, ordmynd, beyging from ksnid_midlungur
   where ordmynd ~ '^[aábdðeéfghiíjklmnoóprstuúvxyýþæö]{3,10}$'
   and fl <> 'bibl'
   and not ((beyging like 'SP-%-FT') or (beyging like 'SP-%-FT2'));
commit;
```

And, finally, to generate the Miðlungur vocabulary file
from the ```psql``` command line:

```sql
\copy (select distinct ordmynd from skrafl_midlungur order by ordmynd) to '~/github/Netskrafl/resources/ordalisti.mid.sorted.txt';
```

The vocabulary of the weakest robot, *Amlóði*, is derived from
```ordalisti.aml.sorted.txt``` by ```python utils/dawgbuilder.py icelandic_filter```,
which keeps only words that are frequent in the Icelandic Gigaword Corpus
and also belong to the Miðlungur vocabulary (and thus have at most 10 letters).
Run it after regenerating ```ordalisti.mid.sorted.txt```, and then
```python utils/dawgbuilder.py skrafl``` to build the DAWG files.

### Original Author
Vilhjálmur Þorsteinsson, Reykjavík, Iceland.

Contact me via GitHub for queries or information regarding Netskrafl.

Please contact me if you have plans for using Netskrafl as a basis for your
own game website and prefer not to operate under the conditions of the
CC-BY-NC 4.0 license (see below).

### License

*Netskrafl - an Icelandic crossword game website*

*Copyright © 2025 Miðeind ehf.*

This set of programs is licensed under the *Creative Commons*
*Attribution-NonCommercial 4.0 International Public License* (CC-BY-NC 4.0).

The full text of the license is available here:
[https://creativecommons.org/licenses/by-nc/4.0/legalcode](https://creativecommons.org/licenses/by-nc/4.0/legalcode).

### Data sources

The Icelandic word database used in Netskrafl is derived from the
[Database of Modern Icelandic Inflection (DMII)](https://bin.arnastofnun.is/gogn/mimisbrunnur/) by the Árni Magnússon Institute of Reykjavík, Iceland.

The DMII is published under the [*Creative Commons Attribution-ShareAlike 4.0 International Public License*](https://creativecommons.org/licenses/by-sa/4.0/) (CC-BY-SA 4.0). The attribution is as follows:

*Beygingarlýsing íslensks nútímamáls. Stofnun Árna Magnússonar í íslenskum fræðum. Höfundur og ritstjóri Kristín Bjarnadóttir.*

A limited number of additions and removals have been performed on the extracted DMII data to create the vocabulary used in Netskrafl. These are listed in the `ordalisti.add.txt` and `ordalisti.remove.txt` files in the `resources` directory.

### Included third party software

Netskrafl contains the *DragDropTouch.js* module by Bernardo Castilho,
which is licensed under the MIT license as follows:

	Copyright © 2016 Bernardo Castilho

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in all
	copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
	SOFTWARE.

Netskrafl contains the *jQuery UI Touch Punch* library by David Furfero, which
is licensed under the MIT license.

	Copyright © 2011 David Furfero

	The MIT license, as spelled out above, applies to this library.

### Trademarks

*SCRABBLE is a registered trademark. This software or its author are in no way
affiliated with or endorsed by the owners or licensees of the SCRABBLE trademark.*
