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
from datetime import datetime, timedelta
import math
import sys

import numpy as np
# import matplotlib
# matplotlib.use('agg')  # In case of missing tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib import collections as mc
from matplotlib.ticker import MultipleLocator

def draw_report(time_axis, map_values, differences, imbalances, image_file=None, numa_cpus={}):
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

    cmap = ListedColormap(['#300040', '#305090', '#40b080', '#f0e020', '#f06020'])
    boundaries = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5]
    norm = BoundaryNorm(boundaries, cmap.N, clip=True)

    fig = plt.figure(figsize=(20, 10))
    ax = plt.gca()

    # Draw the main heat map
    x_grid, y_grid = np.meshgrid(time_axis, range(len(map_values)))
    mesh = ax.pcolormesh(x_grid, y_grid, map_values, vmin=0, vmax=4, cmap=cmap, norm=norm)

    # Draw line with differences
    ax.step(time_axis, differences, where='post', color='white', alpha=0.5)

    # Draw imbalances
    for i in imbalances:
        ax.plot(i[0][0], i[0][1], 'rx')
    lc = mc.LineCollection(imbalances,
                           colors=np.tile((1, 0, 0, 1), (len(imbalances), 1)),
                           linewidths=2)
    ax.add_collection(lc)

    plt.ylabel("CPUs")
    plt.xlabel("Timestamp")

    # Separate CPUs with lines by NUMA nodes
    if numa_cpus:
        ax.grid(True, which='major', axis='y', linestyle='--', color='k')
        plt.yticks(range(0, map_values.shape[0] - 1, len(numa_cpus[0])),
                   map(lambda x: "Node " + str(x), range(len(numa_cpus.keys()))))
        ax.yaxis.set_minor_locator(MultipleLocator(1))
    else:
        plt.yticks(range(map_values.shape[0] - 1))
    ax.set_ylim([0, map_values.shape[0] - 1])

    plt.subplots_adjust(left=0.05, right=0.90, top=0.95, bottom=0.1)

    cbar = fig.colorbar(mesh, cax=plt.axes((0.95, 0.1, 0.02, 0.85)), extend='max',
                        ticks=range(5))

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


def process_report(input_file, sampling, threshold, duration, image_file=None, numa_cpus={}):
    cpus_count = 0
    time_axis = []
    map_values = []
    differences = []
    imbalances = []
    counter = 0

    cpus_count = int(input_file.readline().split('=')[1])
    # TODO add the last row in plotting function
    last_row = np.zeros(cpus_count)
    map_values.append(last_row)

    last_imbalance_start = 0
    for line in input_file:
        data = line.split()
        #point_time = datetime.fromtimestamp(float(data[2].strip(':')))
        point_time = float(data[2].strip(':'))
        cpu = int(data[4].split('=')[1])
        value = int(data[5].split('=')[1])

        row = np.copy(last_row)
        row[cpu] = value
        row_min = min(row)
        row_max = max(row)
        diff = row_max - row_min

        # Check the start of imbalance
        if diff >= threshold and last_imbalance_start == 0:
            last_imbalance_start = point_time
        if diff < threshold and last_imbalance_start != 0:
            # Print and store long imbalances
            if (point_time - last_imbalance_start) >= duration:
                imbalances.append([(last_imbalance_start, threshold),
                                    (point_time, threshold)])
                print("Imbalance from timestamp " \
                      + str(last_imbalance_start) \
                      + " lasting " \
                      + str(point_time - last_imbalance_start) \
                      + " seconds")
            last_imbalance_start = 0

        # Store plotting data with optional sampling
        counter += 1
        if counter >= sampling:
            counter = 0
            map_values.append(row)
            differences.append(diff)
            time_axis.append(point_time)
        last_row = row

    if not imbalances:
        print("No imbalance found")

    draw_report(time_axis, map_values, differences, imbalances, image_file, numa_cpus)
    return time_axis, map_values, differences, imbalances


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="")
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

    try:
        args = parser.parse_args()
    except SystemExit:
        sys.exit(1)

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = read_nodes(args.lscpu_file)

    print("Processing", args.input_file.name)
    process_report(args.input_file, args.sampling, args.threshold, args.duration, args.image_file, numa_cpus)
