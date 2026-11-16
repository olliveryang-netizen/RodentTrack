#!/bin/bash
# RodentTrack launcher for Linux:  bash start_linux.sh
cd "$(dirname "$0")" || exit 1
exec bash ./scripts/launch_unix.sh
