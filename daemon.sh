#!/usr/bin/env bash
# Deadweight vit dans votre instance : il se reveille seul et regarde.
INTERVAL="${DW_INTERVAL:-900}"
printf '\033[1mDeadweight daemon\033[0m  reveil toutes les %ss  (Ctrl+C pour arreter)\n' "$INTERVAL"
while true; do
  printf '\n\033[2m%s  reveil\033[0m\n' "$(date '+%H:%M:%S')"
  ./run.sh "$@" 2>&1 | tail -n 14
  printf '\033[2msommeil %ss...\033[0m\n' "$INTERVAL"
  sleep "$INTERVAL"
done
