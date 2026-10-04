#!/bin/bash
# Finder starts .command files with a minimal PATH. Prefer Python.org's Tk build.
export PATH="/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")" || exit 1

fail() {
    printf '\n%s\nSee docs/MAC_SETUP.md for installation instructions.\n' "$1"
    read -r -p "Press Return to close... "
    exit 1
}

command -v python3 >/dev/null 2>&1 || fail "Python 3 is missing. Install Python from python.org."
python3 -c 'import tkinter' 2>/dev/null || fail "This Python installation has no Tk interface. Install the macOS Python.org installer."
command -v git >/dev/null 2>&1 || fail "Git is missing. Install Git using Homebrew."
git lfs version >/dev/null 2>&1 || fail "Git LFS is missing. Install it using Homebrew."
command -v gh >/dev/null 2>&1 || fail "GitHub CLI is missing. Install it using Homebrew."

python3 tools/cad.py gui
status=$?
if [ "$status" -ne 0 ]; then
    printf '\nThe interface could not start. Check the error above and docs/MAC_SETUP.md.\n'
    read -r -p "Press Return to close... "
fi
exit "$status"
