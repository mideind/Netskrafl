# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Project Overview

Netskrafl is an Icelandic crossword game website built with:
- **Backend**: Python 3.11 + Flask web server for Google App Engine
- **Frontend**: HTML5/JavaScript/TypeScript client with Ajax communication
- **Database**: Google Cloud NDB (schemaless NoSQL)
- **Build System**: Grunt for TypeScript/JavaScript/CSS compilation
- **Testing**: pytest framework

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
```bash
# Run tests with pytest
pytest test/

# Run specific test file
pytest test/test_elo.py

# Type checking
mypy src/
```

### Linting and Code Quality
```bash
# JavaScript linting (via Grunt)
grunt jshint

# TypeScript compilation
cd static && tsc
```

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
The game uses a sophisticated robot player based on the classic Appel & Jacobson "World's Fastest Scrabble Program" algorithm. The DAWG structure enables efficient word validation and move generation. The engine is language-agnostic, supporting multiple languages through separate DAWG files and tile sets.

## Development Notes

- The codebase supports multiple game variants (Netskrafl, Explo) with shared core logic
  but a few differences in the backend APIs, for instance in player authentication
- Currently, Netskrafl only supports Icelandic
- Explo supports Icelandic, English, Polish, and Norwegian (bokmål and nynorsk)
- Netskrafl is a web-based game with real-time multiplayer capabilities
- Explo is an app client (React Native app, implemented in the explo-front repository)
  that communicates with a separate instance of the game server
- Real-time gameplay uses WebSocket-like communication via Firebase
- Elo rating system tracks player performance
- Google App Engine deployment with multiple environments (Netskrafl/Explo, demo/live)
- Frontend supports responsive design for mobile/tablet devices

## Coding Standards

- The #!/usr/bin/env python3 shebang is not required and should be omitted.
- Use `from __future__ import annotations` to enable postponed evaluation of type annotations.
- Use `from typing import ...` to import type hints. Place this immediately after
  the `from __future__ import annotations` line.
- Use type hints for all function parameters and return types.
- Use strict typing in all cases except where third party libraries do not support it.
  In that case, use `# type: ignore` to suppress type checking errors, but try to use
  cast(T, ...) liberally and immediately to limit propagation of 'Any' or 'Unknown' types.
- Finish Python source file with an empty line.
- Use datetime.now(UTC) for timestamps, not datetime.now() or datetime.utcnow().
