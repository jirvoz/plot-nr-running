#!/bin/bash

#Process kernel trace reports with sched_update_nr_running events.
#Copyright (C) 2020  Jirka Hladky <hladky DOT jiri AT gmail DOT com>
#
#This program is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program.  If not, see <https://www.gnu.org/licenses/>.

LANG=C

#{{{ trap - signal handling
# Terminate child processes and stop. Long commands are started through
# run_child, because bash runs the trap only after a foreground command
# finishes. Not trapping EXIT, as signalling on normal exits (usage, errors)
# could interrupt the calling shell when the script shares its process group.

trap_with_arg() { # from https://stackoverflow.com/a/2183063/804678
  local func="$1"; shift
  for sig in "$@"; do
# shellcheck disable=SC2064
    trap "$func $sig" "$sig"
  done
}

# shellcheck disable=SC2329  # invoked through trap
stop() {
  trap - SIGINT SIGTERM SIGHUP
  printf '\nFunction stop(), part of trap handling in plot-nr-running.sh: %s\n' "received $1, killing children"
  # Background children ignore SIGINT, so always terminate them with SIGTERM
  pkill -TERM -P $$
  exit 1
}

trap_with_arg 'stop' SIGINT SIGTERM SIGHUP

# Run command in background and wait for it, a signal interrupts the wait
run_child() {
  "$@" &
  wait $!
}
#}}}

function usage_msg() {
  printf "Usage: %s: --lscpu=LSCPU_FILE TRACE_FILE ... [TRACE_FILE] ...\n\n" "$0"
  printf "Process kernel trace reports with sched_update_nr_running events.\n"
  printf "Example:\n%s --lscpu=lscpu.txt *trace.xz\n\n" "$0"
  printf " TRACE_FILE [TRACE_FILE]- kernel trace files with sched_update_nr_running events (mandatory)\n"
  printf " --lscpu=LSCPU_FILE     - lscpu file (generated with 'lscpu' command on server where kernel tracing was done\n"
  printf " --dry                  - dry run.\n"
  printf " --parallel=MAX_JOBS    - Use GNU parallel to start parallel processing (one job per one input file).\n"
  printf "                          Specify maximum number of parallel jobs. Use 0 to use all available CPUs.\n"
  printf "                          Note: plotting large trace files consumes lots of memory.\n"
  printf "                                Make sure there is enough RAM for parallel processing.\n"
  printf " -h | --help            - This message\n\n"
  exit 1
}

if [ "$#" -lt "2" ]; then
    usage_msg
fi

argDry=0;
argLscpu=""
argParallel=0
argParallelJobs=0
failed=0
ARGLIST=$(getopt -o 'h' --long 'lscpu:,dry,parallel:,help' -n "$0" -- "$@") || usage_msg
eval set -- "${ARGLIST}"
while true
do
  case "$1" in
  --lscpu)      shift; argLscpu=$1;;
  --dry)        argDry=1;;
  --parallel)   shift;argParallel=1;argParallelJobs=$1;;
  -h|--help)    usage_msg;;
  --)           shift; break;;
  *)            usage_msg;;
  esac
  shift
done

[[ -z "$argLscpu" ]] && { echo "lscpu=LSCPU_FILE is mandatory"; usage_msg; }
[[ -z "$1" ]] && { echo "No kernel trace files to process provided."; usage_msg; }

SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
#This is needed to avoid _tkinter.TclError: couldn't connect to display "localhost:10.0" type of error
unset DISPLAY

if [[ "$argParallel" == "0" ]]; then

  for file in "$@"; do
    out_file="${file%.*}.png"
    out_file1="${file%.*}.info"
    echo "Processing file '$file', output in '${out_file}' and '${out_file1}'"
    COMMAND=("${SCRIPT_DIR}/plot-nr-running.py" "--lscpu-file" "$argLscpu" "--image-file" "$out_file" "$file")
    COMMAND1=("${SCRIPT_DIR}/check-nr-running.py" "--lscpu-file" "$argLscpu" "$file")
    
    if [[ "$argDry" == "1" ]]; then
      printf "'%s' " "${COMMAND[@]}"
      echo
      printf "'%s' " "${COMMAND1[@]}"
      printf " > '%s'\n" "$out_file1"
      continue
    fi

    run_child "${COMMAND[@]}"
    ret_code=$?

    if [[ "$ret_code" -ne 0 ]]; then
      failed=1
      echo "Failed to process ${file}. The command was:"
      printf "%s\n" "${COMMAND[*]}"
    fi

    run_child "${COMMAND1[@]}" > "$out_file1"
    ret_code=$?

    if [[ "$ret_code" -ne 0 ]]; then
      failed=1
      echo "Failed to process ${file}. The command was:"
      printf "%s" "${COMMAND1[*]}"
      printf " > '%s'\n" "$out_file1"
    fi
  done

else
  command -v "parallel" >/dev/null 2>&1 || { echo >&2 "GNU parallel is required, but it's not installed."; exit 1; }
  declare -a parOpt=("--memfree=4G")
  # --dry-run prints the commands itself, --verbose would print them twice
  if [[ "$argDry" == "1" ]]; then parOpt+=("--dry-run"); else parOpt+=("--verbose"); fi
  (( argParallelJobs > 0 )) && parOpt+=("--jobs=$argParallelJobs")
  COMMAND=("parallel" "${parOpt[@]}" "${SCRIPT_DIR}/check-nr-running.py" "--lscpu=$argLscpu" "{}" ">" "{.}.info" ":::" "$@")
  printf "'%s' " "${COMMAND[@]}"
  echo
  run_child "${COMMAND[@]}" || failed=1

  COMMAND=("parallel" "${parOpt[@]}" "${SCRIPT_DIR}/plot-nr-running.py" "--lscpu=$argLscpu" "--image-file" "{.}.png" "{}" ">" "{.}.log" ":::" "$@")
  printf "'%s' " "${COMMAND[@]}"
  echo
  run_child "${COMMAND[@]}" || failed=1
fi

trap - SIGINT SIGTERM SIGHUP
exit "$failed"
