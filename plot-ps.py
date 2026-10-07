#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from datetime import datetime
import sys
import re

import numpy as np
# import matplotlib
# matplotlib.use('agg')  # In case of missing tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.ticker import MultipleLocator

# See plot-nr-running.py: one tick per CPU can exceed matplotlib's tick limit
MINOR_TICK_CPU_LIMIT = 256

# Keep the colorbar readable with many threads
TASK_LABEL_LIMIT = 30


def cpu_layout(numa_cpus, cpus_count):
    """Return the heat map row order of CPUs and (first_row, label) of each NUMA node.

    CPUs missing from the lscpu file are kept in a trailing group, so a
    mismatched lscpu file neither crashes the plot nor hides data.
    """
    if not numa_cpus:
        return list(range(cpus_count)), []

    order = []
    nodes = []
    for node, cpus in numa_cpus.items():
        cpus = [cpu for cpu in cpus if cpu < cpus_count]
        if cpus:
            nodes.append((len(order), "Node " + str(node)))
            order += cpus

    listed = set(order)
    missing = [cpu for cpu in range(cpus_count) if cpu not in listed]
    if missing:
        nodes.append((len(order), "Unknown"))
        order += missing

    return order, nodes


def draw_report(map_values, time_axis, task_count, input_file,
                image_file=None, numa_cpus=None):
    # Each snapshot is drawn until the next one, the last one for the
    # usual interval between snapshots
    interval = np.median(np.diff(time_axis)) if len(time_axis) > 1 else 1.0
    time_edges = np.append(time_axis, time_axis[-1] + interval)

    order, nodes = cpu_layout(numa_cpus, map_values.shape[1])

    fig = plt.figure(figsize=(20, 10))
    ax = plt.gca()

    # Create discrete colormap: no task, one color per task, more tasks
    jet = plt.get_cmap('jet')
    colors = ([(.1, .1, .1, 1.0)]
              + [jet(x) for x in np.linspace(0, 1, task_count)]
              + [(1.0, 1.0, 1.0, 1.0)])
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(np.arange(task_count + 3) - 0.5, cmap.N)

    # Draw the main heat map
    mesh = ax.pcolormesh(time_edges, np.arange(len(order) + 1),
                         map_values[:, order].transpose(), cmap=cmap,
                         norm=norm, shading='flat', rasterized=True)

    ax.set_xlim(time_edges[0], time_edges[-1])
    ax.set_ylim(0, len(order))

    plt.title("Process migration heatmap for file '" + str(input_file.name)
              + "'")
    plt.ylabel("CPUs (grouped by NUMA nodes)")
    plt.xlabel("Time in seconds")

    # Separate CPUs with lines by NUMA nodes
    if nodes:
        ax.grid(True, which='major', axis='y', linestyle='--', color='k')
        ax.set_yticks([first for first, _ in nodes])
        ax.set_yticklabels([label for _, label in nodes])
        if len(order) <= MINOR_TICK_CPU_LIMIT:
            ax.yaxis.set_minor_locator(MultipleLocator(1))

    plt.subplots_adjust(left=0.05, right=0.90, top=0.95, bottom=0.1)

    step = -(-task_count // TASK_LABEL_LIMIT)
    tasks = list(range(step, task_count + 1, step))
    cbar = fig.colorbar(mesh, ticks=[0] + tasks + [task_count + 1],
                        cax=fig.add_axes((0.92, 0.1, 0.02, 0.85)))
    cbar.ax.set_ylabel("ID of task running on CPU core")
    cbar.ax.set_yticklabels(["No task"] + list(map(str, tasks))
                            + ["More tasks"])

    if image_file:
        fig.savefig(image_file)
    else:
        plt.show()

    plt.close(fig)


def read_nodes(lscpu_file):
    """Return {node: [cpu, ...]} parsed from lscpu output, in lscpu order."""
    numa_cpus = {}
    numa_re = re.compile(r'NUMA node(\d+) CPU\(s\):\s*(\S*)')
    for line in lscpu_file:
        match = numa_re.search(line)
        if not match:
            continue
        cpus = []
        # Memory-only nodes (CXL, HBM, ...) have an empty CPU list
        for cpu_range in filter(None, match.group(2).split(',')):
            first, _, last = cpu_range.partition('-')
            cpus.extend(range(int(first), int(last or first) + 1))
        if cpus:
            numa_cpus[int(match.group(1))] = cpus

    return numa_cpus


def process_report(input_file, time_offset=0.0, image_file=None,
                   numa_cpus=None):
    if numa_cpus is None:
        numa_cpus = {}
    cpus_count = max(max(cpus) for cpus in numa_cpus.values()) + 1
    time_axis = []
    map_values = []
    # Threads are numbered in order of their first appearance
    threads = {}
    row = None

    for line in input_file:
        data = line.split()
        if not data:
            continue

        if len(data) == 1:  # Time record
            if row is not None:
                map_values.append(row)
            curr_time = datetime.strptime(data[0], '%Y-%b-%d_%Hh%Mm%Ss')
            if not time_offset:
                time_offset = curr_time.timestamp()
            time_axis.append(curr_time.timestamp() - time_offset)
            row = np.zeros(cpus_count, dtype=int)
            continue

        if data[0] == "PID" or row is None:  # Skip table header
            continue

        lwp = int(data[1])
        psr = int(data[2])
        if psr >= cpus_count:
            print("WARNING: Thread {} runs on CPU {}, which is not in lscpu"
                  " file. Skipping.".format(lwp, psr))
            continue

        task = threads.setdefault(lwp, len(threads) + 1)
        if row[psr] == 0:
            row[psr] = task
        else:
            row[psr] = -1  # Multiple tasks on single core

    if row is None:
        print("No ps records found in '{}'.".format(input_file.name))
        return None
    map_values.append(row)

    map_values = np.array(map_values)
    map_values[map_values == -1] = len(threads) + 1

    draw_report(map_values, time_axis, len(threads), input_file,
                image_file, numa_cpus)
    return time_axis, map_values


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
                        " (REQUIRED)")
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

    if not numa_cpus:
        print("No NUMA nodes with CPUs found in lscpu file.")
        sys.exit(1)

    if process_report(args.input_file, args.time_offset,
                      args.image_file, numa_cpus) is None:
        sys.exit(1)
