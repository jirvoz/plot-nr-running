#!/bin/bash

LANG=C

function usage_msg() {
  printf "Usage: %s: --lscpu=LSCPU_FILE TRACE_FILE ... [TRACE_FILE] ...\n\n" "$0"
  printf "Process kernel trace reports with sched_update_nr_running events.\n"
  printf "Example:\n%s --lscpu=lscpu.txt *trace.xz\n" "$0"
  printf " TRACE_FILE [TRACE_FILE]- kernel trace files with sched_update_nr_running events (mandatory)\n"
  printf " --lscpu=LSCPU_FILE     - lscpu file (generated with 'lscpu' command on server where kernel tracing was done\n"
  printf " --dry                  - dry run.\n"
  printf " --parallel=MAX_JOBS    - Use GNU parallel to start parallel processing (one job per one input file).\n"
  printf "                          Specify maximum number of parallel jobs. Use 0 to use all available CPUs.\n"
  printf "                          Note: plotting large trace files consumes lots of memory.\n"
  printf "                                Make sure there is enough RAM for parallel processing.\n"
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
    echo "Processing file '$file', output in '${out_file}'"
    COMMAND=("${SCRIPT_DIR}/plot-nr-running.py" "--lscpu-file" "$argLscpu" "--image-file" "$out_file" "$file")
    
    if [[ "$argDry" == "1" ]]; then
      printf "'%s' " "${COMMAND[@]}"
      echo
      continue
    fi

    "${COMMAND[@]}"
    ret_code=$?

    if [[ "$ret_code" -ne 0 ]]; then
      echo "Failed to process ${file}. The command was:"
      printf "%s\n" "${COMMAND[*]}"
    fi
  done

else
  command -v "parallel" >/dev/null 2>&1 || { echo >&2 "GNU parallel is required, but it's not installed."; exit 1; }
  declare -a parOpt=("--verbose" "--memfree=4G")
  [[ "$argDry" == "1" ]] && parOpt+=("--dry-run")
  (( argParallelJobs > 0 )) && parOpt+=("--jobs=$argParallelJobs")
  COMMAND=("parallel" "${parOpt[@]}" "${SCRIPT_DIR}/plot-nr-running.sh" "--lscpu=$argLscpu" "{}" ">" "{.}.log" ":::" "$@")
  printf "'%s' " "${COMMAND[@]}"
  echo
  "${COMMAND[@]}"
fi



