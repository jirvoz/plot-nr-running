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
from prettytable import PrettyTable
import numpy
import pprint

def read_nodes(lscpu_file):
    numa_cpus = {}
    for line in lscpu_file:
        # Find number of CPUs and NUMA nodes:
        if line[:7] == 'CPU(s):':
            cpu_nb = int(line[7:])
        elif line[:13] == 'NUMA node(s):':
            nodes_nb = int(line[13:])

        # Find NUMA nodes associated with CPUs:
        elif line[:9] == 'NUMA node':
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


reg_exp=re.compile(r"^.*-(\d+).*\s(\d+[.]\d+): sched_update_nr_running: cpu=(\d+) change=([-]?\d+) nr_running=(\d+)")

if args.input_file.name.endswith(".xz"):
    args.input_file.close()
    data_file = lzma.open(args.input_file.name, 'rt')
else:
    data_file = args.input_file

cpus_count = int(data_file.readline().split('=')[1])
cpu_state = dict()
cpu_run_intervals = defaultdict(list)
cpu_nr_running = dict()
missed_events = dict()
missed_events = defaultdict(lambda:0, missed_events)
previous_line = dict()
events_count = 0

for line in data_file:
    match = reg_exp.findall(line)
    if len(match) != 1:
        if "sched_update_nr_running:" in line:
           print("Detected line with 'sched_update_nr_running:' string, but not matching findall regex!")
           print(line, end='')
        continue
    pid = int(match[0][0])
    point_time = float(match[0][1])
    cpu = int(match[0][2])
    change = int(match[0][3])
    nr_running = int(match[0][4])
    events_count += 1

    if nr_running>0:
        current_state="Running"
    else:
        current_state="Idle"

#Check for any unexpected events        
    if cpu in cpu_nr_running:
        detected_change = nr_running - cpu_nr_running[cpu]
        if detected_change != change:
            missed_events[cpu] += 1
            print('Detected missed event number',  sum(missed_events.values()), '- number', missed_events[cpu],' for cpu', cpu)
            print('\tchange ', change, 'detected_change ', detected_change, 'nr_running ', nr_running, 'old nr_running ', cpu_nr_running[cpu]) 
            print('\tPrevious line:', previous_line[cpu], end='')
            print('\tCurrent line: ',  line, end='')
    cpu_nr_running[cpu] = nr_running
    previous_line[cpu] = line

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
        cpu_state[cpu] =  current_state
        if current_state == "Running":
            #Record time when CPU went to running state
            runtime=(point_time,None)
            cpu_run_intervals[cpu].append(runtime)
        else:
            #CPU went to idle. Nothing to record
            pass

#Create utilization table            
cpu_util_table = PrettyTable(['CPU', 'Runtime (s)', 'Runtime %', 'Idle (s)', 'Idle %','Total time (s)'])
cpu_util = dict()

for cpu in sorted(cpu_run_intervals):
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
            #this is the last interval
            if last_idle_transition >= 0.0:
                time[1] += start - last_idle_transition
            break
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
if missed_events:
    missed_events_table = PrettyTable(['Missed events', 'Missed events %', 'Average missed events per CPU','Worst CPU', 'Worst CPU results', 'Best CPU','Best CPU results'])
    me_summary = dict()
    me_summary["total"] = sum(missed_events.values())
    me_summary["worst_cpu"] = max(missed_events, key=missed_events.get)
    me_summary["best_cpu"] = min(missed_events, key=missed_events.get)
    me_summary["average"] = me_summary["total"] / len(missed_events)
    missed_events_table.add_row( [me_summary["total"],
            '{:.2g}%'.format(me_summary["total"]/events_count*100.0),
            '{:.2g}'.format(me_summary["average"]),
            me_summary["worst_cpu"], missed_events[me_summary["worst_cpu"]],
            me_summary["best_cpu"], missed_events[me_summary["best_cpu"]] ])
    print(missed_events_table)
    print("Total sched_update_nr_running events:", events_count)

else:
    print("No missed events found\n")

#pprint.pprint(cpu_run_intervals[0])
