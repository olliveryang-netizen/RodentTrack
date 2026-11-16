#!/bin/bash
# RodentTrack launcher for macOS: double-click this file.
# If macOS says it cannot be opened: right-click -> Open, or run  bash start_mac.command  in Terminal.
cd "$(dirname "$0")" || exit 1
exec bash ./scripts/launch_unix.sh
