"""

    DAWG file list extractor (container build helper)

    Copyright © 2026 Miðeind ehf.
    Original author: Vilhjálmur Þorsteinsson

    The Creative Commons Attribution-NonCommercial 4.0
    International Public License (CC-BY-NC 4.0) applies to this software.
    For further information, see https://github.com/mideind/Netskrafl

    Prints the names of the DAWG vocabulary files that the application
    loads, one per line, derived from the _ALL_DAWGS list in src/wordbase.py.
    Used by the Dockerfile's dawg-downloader stage to fetch exactly the
    vocabularies the app needs from the CDN.

    ---------------------------------------------------------------------
    Why this parses wordbase.py instead of importing it
    ---------------------------------------------------------------------
    This is admittedly a hack: reading a Python source file with `ast`
    to recover a value that an import would hand us directly. It is
    nonetheless the right trade-off here, because importing wordbase is
    impossible in the build stage that needs this list:

      * The dawg-downloader stage is a bare python:3.11-slim image with
        only `curl` added. wordbase imports `config`, `languages` and
        `dawgdictionary`, none of whose dependencies are installed there.
      * Worse, importing `config` does real work at module scope: it
        fetches the project's client secret from Google Secret Manager
        and asserts on its contents (src/config.py:236-243). A build
        stage would need GCP credentials and network egress to GCP just
        to learn a list of filenames.

    Parsing keeps the download list in lockstep with the application code
    (adding or removing a DAWG in wordbase.py is picked up automatically)
    at zero dependency cost. The alternative - a hardcoded list in the
    Dockerfile - is what this replaced; it had silently drifted before.

    ---------------------------------------------------------------------
    Why this lives in a file instead of a Dockerfile heredoc
    ---------------------------------------------------------------------
    It was originally a `RUN python - <<'EOF'` heredoc inside the
    Dockerfile. Digital Ocean's App Platform builds with kaniko, which
    does not support heredocs in RUN instructions: it passes only the
    first line to the shell and discards the body. `python -` then read
    empty stdin, exited 0, and wrote an empty list - so the build
    produced an image with no vocabularies at all, and failed only later
    at the COPY step, with a misleading message. BuildKit handles
    heredocs fine, so this was invisible in local builds.

    Keeping the code in a real file also makes it testable and type-checkable.

"""

from __future__ import annotations

from typing import List

import ast
import sys


DEFAULT_SOURCE = "src/wordbase.py"
DAWG_SUFFIX = ".bin.dawg"
TARGET_NAME = "_ALL_DAWGS"


def dawg_names(source_path: str) -> List[str]:
    """Extract the DAWG file names from the _ALL_DAWGS literal in the
    given wordbase.py source file, without importing it.

    _ALL_DAWGS is an annotated assignment of a list of (name, alphabet)
    tuples, so we look for an ast.AnnAssign whose target is that name and
    read the first element of each tuple. Anything that does not match
    that exact shape is skipped, and the caller treats an empty result as
    an error - if wordbase.py is ever restructured, the build must fail
    loudly rather than silently download nothing."""
    with open(source_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=source_path)

    names: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        target = node.target
        if not isinstance(target, ast.Name) or target.id != TARGET_NAME:
            continue
        if not isinstance(node.value, ast.List):
            continue
        for elt in node.value.elts:
            # Each entry is a (dawg_name, alphabet) tuple; we want the name
            if not isinstance(elt, ast.Tuple) or not elt.elts:
                continue
            first = elt.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.append(first.value + DAWG_SUFFIX)

    return names


def main() -> int:
    source_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    names = dawg_names(source_path)
    if not names:
        print(
            f"error: no {TARGET_NAME} entries found in {source_path}; "
            "has the definition been restructured?",
            file=sys.stderr,
        )
        return 1
    print("\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())

