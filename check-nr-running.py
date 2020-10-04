#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Analyzes of kernel trace reports with sched_update_nr_running events.
Copyright (C) 2020  Jirka Hladky <hladky DOT jiri AT gmail DOT com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import lzma
import re
import argparse
from collections import defaultdict
import sys
import pprint
from prettytable import PrettyTable
import numpy

def read_nodes(lscpu_file):
    numa_cpus = {}
    NUMA_re=re.compile(r'NUMA.*CPU\(s\):')
    for line in lscpu_file:
        # Find number of CPUs and NUMA nodes:
        if line[:7] == 'CPU(s):':
            cpu_nb = int(line[7:])
        elif line[:13] == 'NUMA node(s):':
            nodes_nb = int(line[13:])

        # Find NUMA nodes associated with CPUs:
        elif NUMA_re.search(line):
            words = line.split()
            cpus = words[-1].split(',')
            for cpu in cpus:
                if '-' in cpu:
                    w = cpu.split('-')
                    for i in range(int(w[0]), int(w[1]) + 1):
                        numa_cpus.setdefault(int(words[1][4:]), []).append(i)
                else:
                    numa_cpus.setdefault(int(words[1][4:]), []).append(int(cpu))

    return numa_cpus

parser = argparse.ArgumentParser(description="Analyze kernel trace report with sched_update_nr_running events. "
        "Report CPU utilization based on trace report and check for inconsitency in data (missed events)")
parser.add_argument("input_file", nargs="?", type=argparse.FileType('r'), default=sys.stdin)
parser.add_argument("--lscpu-file", type=argparse.FileType('r'), default=None,
                    help="File with output of lscpu from observed machine")

try:
    args = parser.parse_args()
except SystemExit:
    sys.exit(1)

numa_cpus = {}
if args.lscpu_file:
    numa_cpus = read_nodes(args.lscpu_file)
#pprint.pprint(numa_cpus)



if args.input_file.name.endswith(".xz"):
    args.input_file.close()
    data_file = lzma.open(args.input_file.name, 'rt')
else:
    data_file = args.input_file

reg_exp = re.compile(r"^cpus=(\d+)$")
line = data_file.readline()
line_count = 1
match = reg_exp.findall(line)
if match:
    cpus_count = int(match[0])
else:
    print("ERROR: Couldn't get number of CPUs from the trace file.")
    print("       Unexpected trace file format. First line is expected to have form '{}'".format(reg_exp.pattern))
    print("       Input line: '{}'".format(line.rstrip('\n')))
    print("       Exiting")
    sys.exit(1)

cpu_state = dict()
cpu_run_intervals = defaultdict(list)
cpu_nr_running = dict()
inconsistent_events = dict()
inconsistent_events = defaultdict(lambda:0, inconsistent_events)
previous_line = dict()
events_count = 0

reg_exp = re.compile(r"^.*-(\d+).*\s(\d+[.]\d+): sched_update_nr_running: cpu=(\d+) change=([-]?\d+) nr_running=(\d+)")
for line in data_file:
    line_count += 1
    match = reg_exp.findall(line)

    # Check the correct event
    if not match:
        if "sched_update_nr_running:" in line:
            print("WARNING: Line number {} contains 'sched_update_nr_running:' string, but does not match findall regex '{}'!".format(line_count,reg_exp.pattern))
            print(line, end='')
        continue

    events_count += 1
    pid = int(match[0][0])
    point_time = float(match[0][1])
    cpu = int(match[0][2])
    change = int(match[0][3])
    nr_running = int(match[0][4])

    prev_nr_running = nr_running - change
    if prev_nr_running < 0:
        print("WARNING: Detected line with nr_running - change < 0", "nr_running", nr_running, "change", change, "nr_running - change", prev_nr_running)
        print(line, end='')

    if events_count == 1:
        start_time = point_time

    recorded_inconsistent_event = False
#Check for any unexpected events        
    if cpu in cpu_nr_running:
        detected_change = nr_running - cpu_nr_running[cpu]
        if detected_change != change:
            recorded_inconsistent_event = True
            inconsistent_events[cpu] += 1
            print('WARNING: Detected missed event number',  sum(inconsistent_events.values()), '- number', inconsistent_events[cpu],' for cpu', cpu)
            print('\tchange ', change, 'computed change ', detected_change, 'nr_running ', nr_running, 'old nr_running ', cpu_nr_running[cpu]) 
            print('\tPrevious line:', previous_line[cpu], end='')
            print('\tCurrent line: ',  line, end='')

    if recorded_inconsistent_event == False and cpu in cpu_state:
        old_state = cpu_state[cpu]
        if (old_state == "Running" and prev_nr_running == 0) or (old_state == "Idle" and prev_nr_running >0):
            recorded_inconsistent_event = True
            inconsistent_events[cpu] += 1
            print("WARNING: Detected inconsistent data. Previous state was", old_state,", which does not correspond to computed previous nr_running value", prev_nr_running)
            print('\tPrevious line:', previous_line[cpu], end='')
            print('\tCurrent line: ',  line, end='')

    cpu_nr_running[cpu] = nr_running
    previous_line[cpu] = line

    if nr_running>0:
        current_state="Running"
    else:
        current_state="Idle"

    if cpu in cpu_state:
        #Known state
        old_state = cpu_state[cpu]
        if current_state == old_state:
            continue
        else:
            cpu_state[cpu] =  current_state
            if old_state == "Idle":
                #Record time when CPU went to running state
                runtime=(point_time,None)
                cpu_run_intervals[cpu].append(runtime)
            else:
                #Record time when CPU went to idle state
                start,end = cpu_run_intervals[cpu][-1]
                runtime = (start, point_time)
                cpu_run_intervals[cpu][-1]=runtime
    else:
        cpu_state[cpu] = current_state
        #Compute previous state
        if prev_nr_running > 0:
            old_state="Running"
        else:
            old_state="Idle"

        if current_state == old_state:
            if current_state == "Running":
                runtime=(start_time,None)
                cpu_run_intervals[cpu].append(runtime)
                continue
        else:
            if current_state == "Running":
                #CPU went from Idle to Running
                #To proper account for idle interval, let's pretend it CPU was running at start_time
                runtime=(start_time, start_time)
                cpu_run_intervals[cpu].append(runtime)
                #Record time when CPU went to running state
                runtime=(point_time,None)
                cpu_run_intervals[cpu].append(runtime)
            else:
                #CPU went from running to idle
                runtime=(start_time,point_time)
                cpu_run_intervals[cpu].append(runtime)
#    if cpu == 67:
#        print(line,end='')
#        pprint.pprint(cpu_run_intervals[67])
#        print(current_state)
                
stop_time = point_time
for cpu in cpu_state:
    if cpu_state[cpu] == "Running":
        start,end = cpu_run_intervals[cpu][-1]
        runtime = (start, stop_time)
        cpu_run_intervals[cpu][-1]=runtime
    else:
        #To proper account for the last idle interval
        #let's pretend that as the end of measurement, CPU went to Running state
        runtime = (stop_time, stop_time)
        cpu_run_intervals[cpu].append(runtime)

#print("Start and stop times")
#pprint.pprint([start_time, stop_time])
#for cpu in [67,68]:
#    print("runtime intervals for cpu", cpu)
#    pprint.pprint(cpu_run_intervals[cpu])

#Create utilization table            
cpu_util_table = PrettyTable(['CPU', 'Runtime (s)', 'Runtime %', 'Idle (s)', 'Idle %','Total time (s)'])
cpu_util = dict()

for idx,cpu in enumerate(sorted(cpu_run_intervals)):
    time=[numpy.float64(0.0),numpy.float64(0.0)]
    last_idle_transition=-1.0
    #element 0 => runtime
    #element 1 => idle time
    for intervals in cpu_run_intervals[cpu]:
        start,end = intervals
        if end:
            time[0] += end-start
            if last_idle_transition >= 0.0:
                time[1] += start - last_idle_transition
            last_idle_transition = end
        else:
            #Undefined end time - code should be never get into this state
            print("ERROR - end time of runtime interval for cpu", cpu, "is undefined")
            print("Code should never get into this state. Please contact authors")
            print("Runtime interval:")
            pprint.pprint(cpu_run_intervals[cpu][idx])
            
    cpu_util[cpu]=time
    total = time[0] + time[1]
    result = [cpu,
        '{:4.1f}'.format(time[0]), '{:4.1f}'.format(time[0]/total*100.0),
        '{:4.1f}'.format(time[1]), '{:4.1f}'.format(time[1]/total*100.0),
        '{:4.1f}'.format(total)]
    cpu_util_table.add_row(result)

print(cpu_util_table)

numa_util_table = PrettyTable(['NUMA node', 'Runtime %', 'Idle %'])

if numa_cpus:
    numa_util = dict()
    for node in sorted(numa_cpus.keys()):
        if not node in numa_util:
            numa_util[node] = numpy.zeros(2)
        for cpu in numa_cpus[node]:
            if not cpu in cpu_util:
                #Cpu was idle whole time
                cpu_util[cpu]=[numpy.float64(0.0),numpy.float64(stop_time-start_time)]
            numa_util[node] += cpu_util[cpu]
        total = numa_util[node][0] + numa_util[node][1]
        result = [node,
            '{:4.1f}'.format(numa_util[node][0]/total*100),
            '{:4.1f}'.format(numa_util[node][1]/total*100)]
        numa_util_table.add_row(result)
    print(numa_util_table)

average_util = numpy.zeros(2)
for cpu in cpu_util:
    average_util += cpu_util[cpu]

average_util_table = PrettyTable(['Average', 'Runtime %', 'Idle %'])
total = average_util[0] + average_util[1]
result = ['',
    '{:4.1f}'.format(average_util[0]/total*100),
    '{:4.1f}'.format(average_util[1]/total*100)]
average_util_table.add_row(result)
print(average_util_table)


# Info about missed events    
if inconsistent_events:
    missed_events_table = PrettyTable(['Unexpected events', 'Unexpected events %', 'Average # of unexp. events per CPU','Worst CPU', 'Worst CPU results', 'Best CPU','Best CPU results'])
    me_summary = dict()
    me_summary["total"] = sum(inconsistent_events.values())
    me_summary["worst_cpu"] = max(inconsistent_events, key=inconsistent_events.get)
    me_summary["best_cpu"] = min(inconsistent_events, key=inconsistent_events.get)
    me_summary["average"] = me_summary["total"] / len(inconsistent_events)
    missed_events_table.add_row( [me_summary["total"],
            '{:.2g}%'.format(me_summary["total"]/events_count*100.0),
            '{:.2g}'.format(me_summary["average"]),
            me_summary["worst_cpu"], inconsistent_events[me_summary["worst_cpu"]],
            me_summary["best_cpu"], inconsistent_events[me_summary["best_cpu"]] ])
    print(missed_events_table)
    print("Total sched_update_nr_running events:", events_count)

else:
    print("No unexpected events found\n")

