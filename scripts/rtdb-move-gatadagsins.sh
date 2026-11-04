#!/usr/bin/env bash
#
# One-off helper for moving the netskrafl project's Realtime Database from the
# US default instance to the EU instance netskrafl-eu (europe-west1).
#
# Only the gatadagsins/ subtree is copied. game/, user/ and connection/ are
# not: clients ignore the value they receive on first attach to those paths,
# Datastore holds the real state, and presence re-registers on connect.
#
# Usage, run from the repository root, at the switch:
#   scripts/rtdb-move-gatadagsins.sh export   # old -> $DIR/gatadagsins-before.json
#   scripts/rtdb-move-gatadagsins.sh import   # $DIR/gatadagsins-before.json -> new (replaces the subtree)
#   scripts/rtdb-move-gatadagsins.sh verify   # new instance == before-export?
#   ... switch databaseURL (secret + Málstaður), move all GAE traffic at once ...
#   scripts/rtdb-move-gatadagsins.sh diff     # re-export old, list paths written since the export
#
# Writes to the old instance after the export (from the old servers or from
# browser tabs still pointing at it) show up in 'diff' and must be merged into
# the new instance by hand.

set -euo pipefail

OLD=https://netskrafl.firebaseio.com
NEW=https://netskrafl-eu.europe-west1.firebasedatabase.app
NODE=gatadagsins
DIR=${RTDB_MOVE_DIR:-$HOME/rtdb-move}
export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=${CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE:-credentials/netskrafl/service-account.json}

mkdir -p "$DIR"
TOKEN=$(gcloud auth print-access-token)

fetch() {
    # fetch BASE_URL OUTFILE: download $NODE as canonical (key-sorted) JSON
    curl -sS --fail -m 300 -H "Authorization: Bearer $TOKEN" "$1/$NODE.json" | jq -S -c . > "$2"
    echo "$1/$NODE -> $2 ($(wc -c < "$2") bytes)"
}

leaf_paths() {
    # All leaf paths with their values, one per line, for a readable diff
    jq -r 'paths(scalars) as $p | "\($p | map(tostring) | join("/")) = \(getpath($p) | tojson)"' "$1" | sort
}

case "${1:-}" in
    export)
        fetch "$OLD" "$DIR/gatadagsins-before.json"
        ;;
    import)
        test -s "$DIR/gatadagsins-before.json" || { echo "Run 'export' first" >&2; exit 1; }
        curl -sS --fail -m 300 -X PUT -H "Authorization: Bearer $TOKEN" \
            --data-binary @"$DIR/gatadagsins-before.json" "$NEW/$NODE.json?print=silent"
        echo "Imported $DIR/gatadagsins-before.json into $NEW/$NODE"
        ;;
    verify)
        fetch "$NEW" "$DIR/gatadagsins-new.json"
        if cmp -s "$DIR/gatadagsins-before.json" "$DIR/gatadagsins-new.json"; then
            echo "OK: the new instance matches the export"
        else
            echo "MISMATCH between the export and the new instance" >&2; exit 1
        fi
        ;;
    diff)
        fetch "$OLD" "$DIR/gatadagsins-after.json"
        if cmp -s "$DIR/gatadagsins-before.json" "$DIR/gatadagsins-after.json"; then
            echo "OK: no writes to the old instance since the export"
        else
            echo "Changed on the old instance since the export ('<' before, '>' now):"
            diff <(leaf_paths "$DIR/gatadagsins-before.json") <(leaf_paths "$DIR/gatadagsins-after.json") || true
        fi
        ;;
    *)
        echo "Usage: $0 export|import|verify|diff" >&2
        exit 2
        ;;
esac
