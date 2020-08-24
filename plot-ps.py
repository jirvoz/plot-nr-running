#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from datetime import datetime
import sys

import numpy as np
# import matplotlib
# matplotlib.use('agg')  # In case of missing tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap
from matplotlib.ticker import MultipleLocator


def draw_report(map_values, time_axis, task_count, input_file,
                image_file=None, numa_cpus={}):
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

    # Create discrete colormap
    cmap = plt.cm.jet
    cmaplist = [cmap(i) for i in range(cmap.N)]
    cmaplist[0] = (.1, .1, .1, 1.0)
    cmaplist[-1] = (1.0, 1.0, 1.0, 1.0)
    cmap = LinearSegmentedColormap.from_list(
        'Custom cmap', cmaplist, cmap.N)
    bounds = np.linspace(0, task_count + 2, task_count + 3)
    norm = BoundaryNorm(bounds, cmap.N)

    # Draw the main heat map
    x_grid, y_grid = np.meshgrid(time_axis, range(len(map_values)))
    mesh = ax.pcolormesh(x_grid, y_grid, map_values, vmin=0.0,
                         vmax=task_count + 1, cmap=cmap, norm=norm)

    ax.set_xlim(time_axis[0], time_axis[-1])
    ax.set_ylim([0, map_values.shape[0] - 1])

    plt.title("Process migration heatmap for file '" + str(input_file.name)
              + "'")
    plt.ylabel("CPUs (grouped by NUMA nodes)")
    plt.xlabel("Time in seconds")

    # Separate CPUs with lines by NUMA nodes
    if numa_cpus:
        ax.grid(True, which='major', axis='y', linestyle='--', color='k')
        plt.yticks(range(0, map_values.shape[0] - 1, len(numa_cpus[0])),
                   map(lambda x: "Node " + str(x),
                       range(len(numa_cpus.keys()))))
        ax.yaxis.set_minor_locator(MultipleLocator(1))
    else:
        plt.yticks(range(map_values.shape[0]))

    plt.subplots_adjust(left=0.05, right=0.90, top=0.95, bottom=0.1)

    cbar = fig.colorbar(mesh, ticks=range(task_count + 3),
                        cax=plt.axes((0.92, 0.1, 0.02, 0.85)),
                        cmap='Reds')
    cbar.ax.set_ylabel("ID of task running on CPU core")
    cbar.ax.set_yticklabels(["No task"]
                            + list(map(str, range(1, task_count + 1)))
                            + ["More tasks", ""])

    if image_file:
        plt.savefig(image_file)
    else:
        plt.show()


def read_nodes(lscpu_file):
    numa_cpus = {}
    for line in lscpu_file:
        # Find NUMA nodes associated with CPUs:
        if line[:13] == 'NUMA node(s):':
            continue
        elif line[:9] == 'NUMA node':
            words = line.split()
            cpus = words[-1].split(',')
            for cpu in cpus:
                if '-' in cpu:
                    w = cpu.split('-')
                    for i in range(int(w[0]), int(w[1]) + 1):
                        numa_cpus.setdefault(int(words[1][4:]), []).append(i)
                else:
                    numa_cpus.setdefault(int(words[1][4:]),
                                         []).append(int(cpu))

    return numa_cpus


def process_report(input_file, time_offset=0.0, image_file=None, numa_cpus={}):
    cpus_count = max(np.concatenate(list(numa_cpus.values()))) + 1
    time_axis = []
    map_values = []

    time_axis = []
    row = np.zeros(cpus_count)
    threads = {}
    first_record = True
    curr_time = 0

    for line in input_file:
        data = line.split()

        if len(data) == 1:  # Time record
            curr_time = datetime.strptime(data[0], '%Y-%b-%d_%Hh%Mm%Ss')

            if first_record:
                if not time_offset:
                    time_offset = curr_time.timestamp()
                else:
                    first_record = False
                    map_values.append(row)
            else:
                map_values.append(row)

            time_axis.append(curr_time.timestamp() - time_offset)
            row = np.zeros(cpus_count)

            continue

        if data[0] == "PID":  # Skip table header
            continue

        lwp = int(data[1])
        psr = int(data[2])

        if first_record:
            threads[lwp] = len(threads) + 1

        if row[psr] == 0:
            row[psr] = threads[lwp]
        else:
            row[psr] = 1000  # Multiple tasks on single core

    map_values.append(row)

    draw_report(map_values, time_axis, len(threads), input_file,
                image_file, numa_cpus)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create process migration"
                                     " heatmap using PSR column from ps"
                                     " with optional alignment to system"
                                     " uptime and reordering by NUMA nodes.")
    parser.add_argument("input_file", nargs="?", type=argparse.FileType('r'),
                        default=sys.stdin)
    parser.add_argument("--lscpu-file", type=argparse.FileType('r'),
                        default=None,
                        help="File with output of lscpu from observed machine"
                        "(REQUIRED)")
    parser.add_argument("--image-file", type=str, default=None,
                        help="Save plotted heatmap to file instead of showing")
    parser.add_argument("--time-offset", type=float, default=0,
                        help="Timestamp of system's boot"
                        " to align time axis to uptime")

    try:
        args = parser.parse_args()
    except SystemExit:
        sys.exit(1)

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = read_nodes(args.lscpu_file)
    else:
        print("Argument --lscpu-file is required.")
        sys.exit(1)

    process_report(args.input_file, args.time_offset,
                   args.image_file, numa_cpus)
