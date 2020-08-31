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
# Kill the whole process group, thus killing also descendants.
# Specifying signal EXIT is useful when using set -e
# See also http://stackoverflow.com/questions/360201/how-do-i-kill-background-processes-jobs-when-my-shell-script-exits

trap_with_arg() { # from https://stackoverflow.com/a/2183063/804678
  local func="$1"; shift
  for sig in "$@"; do
# shellcheck disable=SC2064
    trap "$func $sig" "$sig"
  done
}

stop() {
  trap - SIGINT EXIT
  printf '\nFunction stop(), part of trap handling in plot-nr-running.sh: %s\n' "received $1, killing children"
  kill -s SIGINT -- -$BASHPID
}

trap_with_arg 'stop' EXIT SIGINT SIGTERM SIGHUP
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
      printf " > '%s\n'" "$out_file1"
      continue
    fi

    "${COMMAND[@]}"
    ret_code=$?

    if [[ "$ret_code" -ne 0 ]]; then
      echo "Failed to process ${file}. The command was:"
      printf "%s\n" "${COMMAND[*]}"
    fi

    "${COMMAND1[@]}" > "$out_file1"
    ret_code=$?

    if [[ "$ret_code" -ne 0 ]]; then
      echo "Failed to process ${file}. The command was:"
      printf "%s" "${COMMAND1[*]}"
      printf " > '%s\n'" "$out_file1"
    fi
  done

else
  command -v "parallel" >/dev/null 2>&1 || { echo >&2 "GNU parallel is required, but it's not installed."; exit 1; }
  declare -a parOpt=("--verbose" "--memfree=4G")
  [[ "$argDry" == "1" ]] && parOpt+=("--dry-run")
  (( argParallelJobs > 0 )) && parOpt+=("--jobs=$argParallelJobs")
  COMMAND=("parallel" "${parOpt[@]}" "${SCRIPT_DIR}/check-nr-running.py" "--lscpu=$argLscpu" "{}" ">" "{.}.info" ":::" "$@")
  printf "'%s' " "${COMMAND[@]}"
  echo
  "${COMMAND[@]}"

  COMMAND=("parallel" "${parOpt[@]}" "${SCRIPT_DIR}/plot-nr-running.py" "--lscpu=$argLscpu" "--image-file" "{.}.png" "{}" ">" "{.}.log" ":::" "$@")
  printf "'%s' " "${COMMAND[@]}"
  echo
  "${COMMAND[@]}"
fi

trap - EXIT SIGINT SIGTERM SIGHUP
