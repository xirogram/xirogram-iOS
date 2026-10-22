#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Run the interactive builder with python3
exec python3 "$DIR/build_local.py" "$@"
