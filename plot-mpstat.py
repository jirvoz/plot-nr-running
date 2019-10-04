#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from datetime import datetime, timedelta
import math
import sys
import re

import numpy as np
# import matplotlib
# matplotlib.use('agg')  # In case of missing tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib import collections as mc
from matplotlib.ticker import MultipleLocator

def draw_report(map_values, time_axis, input_file, image_file=None, numa_cpus={}):
    # Transpose heat map data to right axes
    map_values = np.array(map_values)[:-1, :].transpose()

    # Group CPU lines by NUMA nodes
    if numa_cpus:
        new_order = []
        for k, v in numa_cpus.items():
            new_order += v
        map_values = map_values[new_order]

    # Add blank row to correctly plot all rows with data
    map_values = np.vstack((map_values, np.zeros(map_values.shape[1])))

    fig = plt.figure(figsize=(20, 10))
    ax = plt.gca()

    #im = ax.imshow(map_values, cmap='Reds')
    #plt.xticks(range(len(time_axis)), map(str, time_axis))
    # Draw the main heat map
    x_grid, y_grid = np.meshgrid(time_axis, range(len(map_values)))
    mesh = ax.pcolormesh(x_grid, y_grid, map_values, vmin=0.0, vmax=100.0, cmap='Reds')

    ax.set_xlim(time_axis[0], time_axis[-1])
    ax.set_ylim([0, map_values.shape[0] - 1])

    plt.title("mpstat heatmap for file '" + str(input_file.name) + "'")
    plt.ylabel("CPUs (grouped by NUMA nodes)")
    plt.xlabel("Uptime in seconds")

    # Separate CPUs with lines by NUMA nodes
    if numa_cpus:
        ax.grid(True, which='major', axis='y', linestyle='--', color='k')
        plt.yticks(range(0, map_values.shape[0] - 1, len(numa_cpus[0])),
                   map(lambda x: "Node " + str(x), range(len(numa_cpus.keys()))))
        ax.yaxis.set_minor_locator(MultipleLocator(1))
    else:
        plt.yticks(range(map_values.shape[0]))

    plt.subplots_adjust(left=0.05, right=0.90, top=0.95, bottom=0.1)

    cbar = fig.colorbar(mesh, cax=plt.axes((0.95, 0.1, 0.02, 0.85)), cmap='Reds')

    if image_file:
        plt.savefig(image_file)
    else:
        plt.show()


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


def process_report(input_file, image_file=None, numa_cpus={}):
    cpus_count = 0
    time_axis = []
    map_values = []
    differences = []
    imbalances = []
    counter = 0

    # Check if two first lines contain date and uptime timestamps in this format:
#Date since epoch in seconds:1570106259.365
#Uptime in seconds:105323.01
    # Related BASH code    
    # DATE_MILI=$(date +%s%3N); UPTIME=$(cat /proc/uptime)
    # DATE_SECONDS=$(bc -l <<< "scale=3;$DATE_MILI/10^3")
    # UPTIME_ONLY=$(echo ${UPTIME} | awk '{print $1}')
    # { echo "#Date since epoch in seconds:${DATE_SECONDS}"; echo "#Uptime in seconds:${UPTIME_ONLY}"; } > ${BASENAME_LOGFILE}.mpstat

    start_date=None
    uptime=None

    line = input_file.readline()
    m = re.search(r"#Date since epoch in seconds:([0-9]+.[0-9]+)", line)
    if m:
        start_date = datetime.fromtimestamp(float(m.group(1)))
        line = input_file.readline()
    else:
        print("Missing date")

    m = re.search(r"#Uptime in seconds:([0-9]+.[0-9]+)", line)
    if m:
        uptime = float(m.group(1))
        line = input_file.readline()
    else:
        print("Missing uptime")

    act_date = start_date.date()
    start_time = start_date.timestamp() - uptime

    # Get CPUs count
    reg_exp=re.compile(r".*\(([0-9]+) CPU\).*")
    match = reg_exp.findall(line)
    if match:
        cpus_count = int(match[0])
    else:
        print("Expected mpstat header on third line")
        exit(1)

    input_file.readline()  # skip first empty line

    curr_time = uptime
    time_axis = []
    row = np.zeros(cpus_count)

    for line in input_file:
        data = line.split()
        if not data:
            map_values.append(row)
            time_axis.append(curr_time - start_time)
            row = np.zeros(cpus_count)
            continue
        if data[0] == "Average:":
            break  # end of file
        if data[1] == "CPU":  # Time when measure started
            curr_time = datetime.combine(act_date,
                                         datetime.strptime(data[0], "%H:%M:%S").time()).timestamp()
            continue
        if data[1] == "all":
            continue
        row[int(data[1])] = float(data[2]) + float(data[4])  # usr + sys values

    draw_report(map_values, time_axis, input_file, image_file, numa_cpus)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="")
    parser.add_argument("input_file", nargs="?", type=argparse.FileType('r'), default=sys.stdin)
    parser.add_argument("--image-file", type=str, default=None,
                        help="Save plotted heatmap to file instead of showing")
    parser.add_argument("--lscpu-file", type=argparse.FileType('r'), default=None,
                        help="File with output of lscpu from observed machine")

    try:
        args = parser.parse_args()
    except SystemExit:
        sys.exit(1)

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = read_nodes(args.lscpu_file)

    process_report(args.input_file, args.image_file, numa_cpus)
