#!/usr/bin/env bash
# One command for the whole report:  ./run_report.sh 2026Q3 [respublika|toshkent] [options]
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$PWD/src"
[ -z "$1" ] && { echo "Usage: ./run_report.sh PERIOD [respublika|toshkent] [options]"; exit 2; }
period="$1"; scope="${2:-respublika}"; shift; [ $# -gt 0 ] && shift
python3 -m uyjoy report --period "$period" --scope "$scope" "$@"
