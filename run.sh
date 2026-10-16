#!/bin/sh
set -eu
cd "$(dirname "$(readlink -f "$0")")"
exec /usr/bin/python3 -m mio_linux.app "$@"
