#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Create heatmap and find imbalances from recorded
sched_update_nr_running events with trace-cmd.
Copyright (C) 2019  Jiri Vozar

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

import argparse
import sys
import re

import numpy as np
#import matplotlib
#matplotlib.use('agg')  # For machines without tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib import collections as mc
from matplotlib.ticker import MultipleLocator

def draw_report(title, time_axis, map_values, differences, imbalances, sums, image_file=None, numa_cpus={}):
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

    cmap = ListedColormap(['#000000', '#305090', '#40b080', '#f0e020', '#f04010'])
    boundaries = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5]
    norm = BoundaryNorm(boundaries, cmap.N, clip=True)

    fig, axs = plt.subplots(nrows=3, ncols=1, gridspec_kw=dict(height_ratios=[4, 1, 2]),
                            sharex=True, figsize=(20, 10))  # , constrained_layout=True)
    fig.subplots_adjust(hspace=0.05)

    # Draw the main heat map
    x_grid, y_grid = np.meshgrid(time_axis, range(len(map_values)))
    mesh = axs[0].pcolormesh(x_grid, y_grid, map_values, vmin=0, vmax=4, cmap=cmap, norm=norm)

    axs[0].set_xlim(time_axis[0], time_axis[-1])
    axs[0].set_ylim([0, map_values.shape[0] - 1])

    # Create colorbar
    cbar = fig.colorbar(mesh, cax=plt.axes([0.95, 0.05, 0.02, 0.9]),
                        extend='max', ticks=range(5))
    cbar.ax.set_yticklabels(['0', '1', '2', '3', '4+'])
    cbar.ax.set_ylabel("Number of tasks on CPU core")
    plt.subplots_adjust(bottom=0.05, right=0.9, top=0.95, left=0.05)

    # Draw line with differences
    axs[1].step(time_axis, differences, where='post', color='black', alpha=0.8)

    # Draw imbalances
    for i in imbalances:
        axs[1].plot(i[0][0], i[0][1], 'rx')
    lc = mc.LineCollection(imbalances,
                           colors=np.tile((1, 0, 0, 1), (len(imbalances), 1)),
                           linewidths=2)
    axs[1].add_collection(lc)

    # Draw line with sums
    axs[2].step(time_axis, sums, where='post', color='black', alpha=0.8)

    axs[0].set_ylabel("CPUs")
    axs[1].set_ylabel("Max difference")
    axs[2].set_ylabel("Sum of tasks")
    axs[2].set_xlabel("Timestamp (seconds)")

    axs[1].set_ylim(ymin=0)
    axs[1].grid()
    axs[2].set_ylim(ymin=0)
    axs[2].grid()

    # Separate CPUs with lines by NUMA nodes
    plt.sca(axs[0])
    if numa_cpus:
        axs[0].grid(True, which='major', axis='y', linestyle='--', color='w')
        axs[0].yaxis.set_minor_locator(MultipleLocator(1))
        plt.yticks(range(0, map_values.shape[0] - 1, len(numa_cpus[0])),
                   map(lambda x: "Node " + str(x), range(len(numa_cpus.keys()))))
    else:
        axs[0].set_yticks(range(map_values.shape[0] - 1))

    plt.title(title)

    if image_file:
        plt.savefig(image_file)
    else:
        plt.show()


def read_nodes(lscpu_file):
    numa_cpus = {}
    NUMA_re = re.compile(r'NUMA.*CPU\(s\):')
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


def process_report(title, input_file, sampling, threshold, duration, image_file=None, numa_cpus={}):
    cpus_count = 0
    time_axis = []
    map_values = []
    differences = []
    imbalances = []
    sums = []
    counter = 0

    cpus_count = int(input_file.readline().split('=')[1])

    # For each line in trace report, row is NumPy array reprenting number of processes on each CPU
    # -1 means no data yet
    last_row = np.full(cpus_count, -1)
    map_values.append(last_row)

    point_time = 0

    reg_exp = re.compile(r"^.*-(\d+).*\s(\d+[.]\d+): sched_update_nr_running: cpu=(\d+) change=([-]?\d+) nr_running=(\d+)")

    for line in input_file:
        match = reg_exp.findall(line)

        # Check the correct event
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

        if last_row[cpu] == -1:
        # First time we got data for this CPU. Compute previous value as nr_running - change
        # and update all data already stored
            for val in map_values:
                val[cpu] = nr_running - change

        row = np.copy(last_row)
        row[cpu] = nr_running

        # Store plotting data with optional sampling
        counter += 1
        if counter >= sampling:
            counter = 0
            map_values.append(row)
            time_axis.append(point_time)
        last_row = row

    last_imbalance_start = 0

    if len(time_axis) == 0:
        print("No sched_update_nr_running found. Exiting.")
        sys.exit(0)

    # Second run to compute imbalances - process all rows from map_values
    for i, time in enumerate(time_axis):
        row_min = min(map_values[i])
        row_max = max(map_values[i])
        diff = row_max - row_min

        # Check the start of imbalance
        if diff >= threshold and last_imbalance_start == 0:
            last_imbalance_start = time
        if diff < threshold and last_imbalance_start != 0:
            # Print and store long imbalances
            if (time - last_imbalance_start) >= duration:
                imbalances.append([(last_imbalance_start, threshold),
                                   (time, threshold)])
                print(f"Imbalance from timestamp {last_imbalance_start}"
                      f" lasting {time - last_imbalance_start} seconds")
            last_imbalance_start = 0

        differences.append(diff)
        sums.append(sum(map_values[i]))

    # Check for unreported imbalance lasting to the very end of input
    if last_imbalance_start != 0 \
       and (time_axis[-1] - last_imbalance_start) >= duration:
        imbalances.append([(last_imbalance_start, threshold),
                           (time_axis[-1], threshold)])
        print(f"Imbalance from timestamp {last_imbalance_start}"
              f" lasting {time_axis[-1] - last_imbalance_start} seconds")

    if not imbalances:
        print("No imbalance found")

    draw_report(title, time_axis, map_values, differences, imbalances, sums, image_file, numa_cpus)
    return time_axis, map_values, differences, imbalances


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create heatmap and find"
        " imbalances from recorded sched_update_nr_running events with trace-cmd.")
    parser.add_argument("input_file", nargs="?", type=argparse.FileType('r'), default=sys.stdin)
    parser.add_argument("--sampling", default=1, type=int,
                        help="Sampling of plotted data to reduce drawing point_time")
    parser.add_argument("--threshold", default=2, type=int,
                        help="Minimal difference of process count considered as imbalance")
    parser.add_argument("--duration", default=0.05, type=float,
                        help="Minimal duration of imbalance worth reporting")
    parser.add_argument("--image-file", type=str, default=None,
                        help="Save plotted heatmap to file instead of showing")
    parser.add_argument("--lscpu-file", type=argparse.FileType('r'), default=None,
                        help="File with output of lscpu from observed machine")
    parser.add_argument("--name", type=str, default=None,
                        help="Filename to be displayed in graph. Usefull when reading input from stdin.")

    try:
        args = parser.parse_args()
    except SystemExit:
        sys.exit(1)

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = read_nodes(args.lscpu_file)

    if args.name:
        title = "Plot of '" + args.name
    else:
        title = "Plot of '" + args.input_file.name

    if args.input_file.name.endswith(".xz"):
        args.input_file.close()
        import lzma
        with lzma.open(args.input_file.name, 'rt') as decompressed:
            process_report(title, decompressed, args.sampling, args.threshold,
                           args.duration, args.image_file, numa_cpus)
    else:
        process_report(title, args.input_file, args.sampling, args.threshold,
                       args.duration, args.image_file, numa_cpus)
