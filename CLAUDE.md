# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

Netskrafl is an Icelandic crossword game website and backend server built with:
- **Backend**: Python 3.11 + Flask web server for Google App Engine
- **Frontend**: HTML5/JavaScript/TypeScript client with Ajax communication
- **Database**: Google Cloud NDB (schemaless NoSQL), but being migrated to PostgreSQL
- **Build System**: Grunt for TypeScript/JavaScript/CSS compilation
- **Testing**: pytest framework

It supports (1) Netskrafl, a web-based game currently offered in Icelandic only,
and (2) is the backend for Explo, a multilingual mobile app client
(React Native app, in a separate repository).

## Common Development Commands

### Development Setup
```bash
# Install Python dependencies
pip install -r requirements.txt

# For local development, also install
pip install icegrams

# Install Node.js dependencies
npm install

# Generate DAWG vocabulary files (takes a few minutes)
python utils/dawgbuilder.py all

# Build frontend assets
grunt make

# Start development server
./runserver.sh  # or runserver.bat on Windows

# Watch for file changes during development
grunt  # runs grunt watch by default
```

### Testing

Tests require Google Cloud credentials and environment variables. Use the appropriate
configuration for each project:

```bash
# Run tests for explo-dev (multi-locale, full test coverage)
PROJECT_ID=explo-dev \
GOOGLE_APPLICATION_CREDENTIALS="<path-to-explo-dev-credentials.json>" \
GOOGLE_CLOUD_PROJECT=explo-dev \
RUNNING_LOCAL=true \
REDISHOST=127.0.0.1 \
REDISPORT=6379 \
FIREBASE_DB_URL="<explo-dev-firebase-url>" \
SINGLE_PAGE=TRUE \
venv/bin/pytest test/ -v

# Run tests for netskrafl (Icelandic only - some multi-locale tests will fail)
PROJECT_ID=netskrafl \
GOOGLE_APPLICATION_CREDENTIALS="<path-to-netskrafl-credentials.json>" \
GOOGLE_CLOUD_PROJECT=netskrafl \
RUNNING_LOCAL=true \
REDISHOST=127.0.0.1 \
REDISPORT=6379 \
FIREBASE_DB_URL="<netskrafl-firebase-url>" \
venv/bin/pytest test/ -v

# Run specific test file
venv/bin/pytest test/test_elo.py

# Type checking with pyright (preferred)
venv/bin/pyright src/

```

Note: The explo-dev configuration should be used for full test coverage as it supports
multiple locales. The netskrafl configuration only supports Icelandic (`is_IS`) and
some tests that require other locales will fail.

The actual values for credentials paths and Firebase URLs can be found in `.vscode/launch.json`.

## Architecture Overview

### Backend Structure (src/)
- **main.py**: Flask app entry point and configuration
- **web.py**: HTML page routes and responsive web content
- **api.py**: JSON API endpoints for client communication
- **skraflgame.py**: Core Game class and game state management
- **skrafluser.py**: User class and user management
- **skraflmechanics.py**: Game mechanics and move validation
- **skraflplayer.py**: Robot player AI implementation using Appel & Jacobson algorithm
- **dawgdictionary.py**: DAWG (Directed Acyclic Word Graph) navigation for word validation
- **languages.py**: Language-specific tile sets, bags, and vocabularies
- **skrafldb.py**: Database persistence layer using Google Cloud NDB
- **auth.py/authmanager.py**: Authentication and user session management
- **secret_manager.py**: Google Cloud Secret Manager integration

### Frontend Structure (static/)
- **src/**: TypeScript source files
  - **page.ts**: Main page logic and UI management
  - **game.ts**: Game board and gameplay interactions
  - **model.ts**: Data models and state management
- **js/**: Legacy JavaScript files
- **built/**: Compiled JavaScript output (netskrafl.js, explo.js)
- **templates/**: Jinja2 HTML templates

### Key Data Files
- **resources/*.bin.dawg**: Compressed vocabulary files for different languages
- **resources/ordalisti.*.txt**: Source vocabulary lists
- **static/skrafl-*.less**: LESS stylesheets compiled to CSS

### Game Engine
The game uses a sophisticated robot player based on the classic Appel & Jacobson
"World's Fastest Scrabble Program" algorithm. The DAWG structure enables efficient
word validation and move generation. The engine is language-agnostic, supporting
multiple languages through separate DAWG files and tile sets.

## Development Notes

- The codebase supports two game variants (Netskrafl, Explo) with shared core logic
  but a few differences in the backend APIs, for instance in player authentication
- Currently, Netskrafl only supports Icelandic
- Explo supports Icelandic, English, Polish, and Norwegian (bokmål and nynorsk)
- Netskrafl is a web-based game with real-time multiplayer capabilities
- The Netskrafl web frontend supports responsive UIs for desktop and mobile browsers
- Explo has a mobile app client (React Native app, implemented in the explo-front repository)
  that communicates with a separate instance of the Netskrafl/Explo game server
- Real-time gameplay uses WebSocket-like communication via Firebase
- Elo rating system tracks player performance
- Google App Engine deployment with multiple environments (Netskrafl/Explo, demo/live)
- A project is underway to migrate from Google Cloud to a containerized deployment,
  probably on Digital Ocean, with PostgreSQL replacing Google NDB

## Coding Standards

- The #!/usr/bin/env python3 shebang is not required and should be omitted.
- Use `from __future__ import annotations` to enable postponed evaluation of type annotations.
- Use `from typing import ...` to import type hints. Place this immediately after
  the `from __future__ import annotations` line. Other imports then follow after these two.
- Use type hints for all function parameters and return types.
- Use strict typing in all cases except where third party libraries do not support it.
  In that case, use `# type: ignore` to suppress type checking errors, but try to use
  `cast(T, ...)` liberally and immediately to limit propagation of 'Any' or 'Unknown' types.
- Otherwise, avoid casts, type ignores and `Any` types as much as possible. If you find
  yourself needing to use them, consider whether the code can be refactored to avoid them.
- Python source files should end with an empty line (i.e., two newlines at the end - `\n\n`).
- Use datetime.now(UTC) for timestamps, not datetime.now() or datetime.utcnow().
- Empty lines should only contain newlines, no spaces or tabs.

## Gotchas

- When running locally in development, a separate local Redis instance is used for Cloud
  Datastore caching. *This may cause cache incoherency* with the production environment.
  Especially, if running local utility scripts that modify the production database,
  the production cache may need to be cleared via Google Cloud Console.
  *Please remind the user about this if you can, when you see that utility programs
  are being run locally.* Also, adding comments to utility programs to this effect is useful.
- `netskrafl_lint.py` is **not** a linter - it is a separate utility program.
  Do not invoke it for code quality checks. Only run it when specifically asked.
