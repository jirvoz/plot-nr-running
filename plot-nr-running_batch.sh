#!/bin/bash

#Batch processing of trace reports
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
  printf '\nFunction stop(), part of trap handling in plot-nr-running_batch.sh: %s\n' "received $1, killing children"
  kill -s SIGINT -- -$BASHPID
}

trap_with_arg 'stop' EXIT SIGINT SIGTERM SIGHUP
#}}}

function usage_msg() {
  printf "Usage: %s: --lscpu=LSCPU_FILE TRACE_FILE ... [TRACE_FILE] ...\n\n" "$0"
  printf "Search for kernel trace reports with sched_update_nr_running events and process them with plot-nr-running.sh script.\n"
  printf "Example:\n%s --pattern=4.18.0-228.el8.bz1861444.test.cki.kt1 --parallel=4 --new --dry\n\n" "$0"
  printf " TRACE_FILE [TRACE_FILE]- kernel trace files with sched_update_nr_running events (mandatory)\n"
  printf " --lscpu=LSCPU_FILE     - lscpu filename. Default: lscpu.txt\n"
  printf "                          Script expects that LSCPU_FILE has the same name in each processed directory.\n"
  printf " --topdir=TOP_DIR       - TOP_DIR is the top directory where find will start the search for kernel trace files.\n"
  printf "                          Default: current directory.\n"
  printf " --pattern=DIR_PATTERN  - Limit search to directories with this pattern: find TOP_DIR -name TRACE_NAME -wholename *DIR_PATTERN*\n"
  printf " --tracename=TRACE_NAME - find is searching for files with TRACE_NAME pattern: find TOP_DIR --name TRACE_NAME\n"
  printf "                          The same pattern will be passed to plot-nr-running.sh script."
  printf "                          Default: *.trace.xz"
  printf " --new                  - Process only new trace files, for which no png output exists.\n"
  printf "                          Replaces the last filename extension (suffix) after the dot with png.\n"
  printf "                          Example: For trace file 'report.trace.xz' it checks for 'report.trace.png'\n"
  printf " --dry                  - dry run.\n"
  printf " --parallel=MAX_JOBS    - Use GNU parallel to start parallel processing (one job per one input file).\n"
  printf "                          Specify maximum number of parallel jobs. Use 0 to use all available CPUs.\n"
  printf "                          Note: plotting large trace files consumes lots of memory.\n"
  printf "                                Make sure there is enough RAM for parallel processing.\n"
  printf " -v | --verbose         - Verbose mode.\n"
  printf " -h | --help            - This message\n\n"
  exit 1
}

argVerbose=0; argNew=0; argDry=0; argLscpu="lscpu.txt"; argParallel=0; argParallelJobs=0; argTopdir="./"; argPattern=""; argTrace="*.trace.xz"
ARGLIST=$(getopt -o 'vh' --long 'lscpu:,topdir:,pattern:,tracename:,new,dry,parallel:,verbose,help' -n "$0" -- "$@") || usage_msg
eval set -- "${ARGLIST}"
while true
do
  case "$1" in
  --lscpu)      shift; argLscpu=$1;;
  --topdir)     shift; argTopdir=$1;;
  --pattern)    shift; argPattern=$1;;
  --tracename)  shift; argTrace=$1;;
  --new)        argNew=1;;
  --dry)        argDry=1;;
  --parallel)   shift;argParallel=1;argParallelJobs=$1;;
  --verbose)    argVerbose=1;;
  -h|--help)    usage_msg;;
  --)           shift; break;;
  *)            usage_msg;;
  esac
  shift
done

SOURCE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
if [[ ! -x "${SOURCE_DIR}/plot-nr-running.sh" ]]; then
  echo "Expects \"${SOURCE_DIR}/plot-nr-running.sh\" to exist and to be executable"
  exit 1
fi

TOP_FIND=("find" "$argTopdir" "-type" "f" "-name" "${argTrace}")
[[ -n "$argPattern" ]] && TOP_FIND+=("-wholename" "*${argPattern}*")
TOP_FIND+=("-printf" "%h\n")

LOCAL_FIND=("find" "./" "-maxdepth" "1" "-type" "f" "-name" "${argTrace}")

printf "find command:\n"
printf "%s " "${TOP_FIND[@]}"
printf "\n"

read -r -p "Continue? [y/n] " response
[[ ! $response =~ ^[Yy]$ ]] && exit 1

mapfile -t FOUND_DIRS < <( "${TOP_FIND[@]}" | sort -u )

if (( argNew == 1 )); then

  if (( argVerbose == 1 )); then
    echo "Checking the following directories for unprocessed trace files:"
    printf "'%s'\n" "${FOUND_DIRS[@]}"
    echo
  fi

  UNPROCESSED_DIRS=()
  for DIR in "${FOUND_DIRS[@]}"; do
    pushd "$DIR" >/dev/null || exit 1
    mapfile -t FILES < <( "${LOCAL_FIND[@]}" )
    for file in "${FILES[@]}"; do
      out_file="${file%.*}.png"
      if [[ ! -e "$out_file" ]]; then
        UNPROCESSED_DIRS+=("$DIR")
        if (( argVerbose == 1 )); then
          echo "Found unprocessed file '$file' in '$DIR'. Including '$DIR' for further processing."
        fi
        break
      fi
    done
    popd >/dev/null || exit 1
  done
  FOUND_DIRS=("${UNPROCESSED_DIRS[@]}")
fi

(( ${#FOUND_DIRS[@]} == 0 )) && { echo "No directories to process found. Please refine the find command."; exit 1; }

echo "Found the following directories to process:"
echo "========================================================================="
printf "'%s'\n" "${FOUND_DIRS[@]}"
echo "========================================================================="

PROCESS_COMMAND=("${SOURCE_DIR}/plot-nr-running.sh" "--lscpu" "$argLscpu")
(( argDry == 1 )) && PROCESS_COMMAND+=("--dry")
(( argParallel == 1 )) && PROCESS_COMMAND+=("--parallel" "$argParallelJobs")
printf "Command to be executed in each directory:\n"
printf "%s " "${PROCESS_COMMAND[@]}"
printf "\$(%s)\n" "${LOCAL_FIND[*]}"
(( argNew == 1 )) && printf "Already processed trace reports will be excluded.\n"

read -r -p "Continue? [y/n] " response
[[ ! $response =~ ^[Yy]$ ]] && exit 1

OK_DIR=()
FAIL_DIR=()

for DIR in "${FOUND_DIRS[@]}"; do
  pushd "$DIR" >/dev/null || { FAIL_DIR+=("$DIR"); break; }
  echo "Processing directory '$DIR'"
  mapfile -t FILES < <( "${LOCAL_FIND[@]}" )

  if (( argNew == 1 )); then
    UNPROCESSED_FILES=()
    for file in "${FILES[@]}"; do
      out_file="${file%.*}.png"
      if [[ ! -e "$out_file" ]]; then
        UNPROCESSED_FILES+=("$file")
      else
        if (( argVerbose == 1 )); then
          echo "Excluding file $file as processed file $out_file was found"
        fi
      fi
    done
    FILES=("${UNPROCESSED_FILES[@]}")  
  fi

  if (( ${#FILES[@]} == 0 )); then
    echo "No trace files to process found in '$DIR'."
    echo "Script should be never in this state. Please report it to authors."
  else
    if (( argVerbose == 1 )); then
      echo "Trace files to process in directory '$DIR':"
      printf "'%s'\n" "${FILES[@]}"
    fi
    printf "Running %s\n" "${PROCESS_COMMAND[*]} ${FILES[*]}"
    if "${PROCESS_COMMAND[@]}" "${FILES[@]}"; then
      echo "Successfully processed trace files from '${DIR}'"
      OK_DIR+=("$DIR")
    else
      echo "Error when processing trace files from '${DIR}'"
      FAIL_DIR+=("$DIR")
    fi
  fi

  popd >/dev/null || { echo "Critical error. popd in $(pwd) has failed. Please report it to authors"; exit 1; }
done

if (( ${#OK_DIR[@]} > 0 )); then
  echo "Successfully processed trace files from following directories:"
  printf "'%s' " "${OK_DIR[@]}"
  printf "\n"
fi

if (( ${#FAIL_DIR[@]} > 0 )); then
  echo "Error when processing trace files from following directories:"
  printf "'%s' " "${FAIL_DIR[@]}"
  printf "\n"
fi

trap - EXIT SIGINT SIGTERM SIGHUP
