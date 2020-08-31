#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from datetime import datetime, timedelta
import os
import sys
import re

import numpy as np
# import matplotlib
# matplotlib.use('agg')  # In case of missing tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib import collections as mc
from matplotlib.ticker import MultipleLocator

def draw_reports(cpu_values, time_axis, file_names, image_file=None, numa_cpus={}):
    cols = int(np.ceil(np.sqrt(len(cpu_values))))
    rows = int(np.ceil(len(cpu_values) / cols))
    fig, axs = plt.subplots(nrows=rows, ncols=cols, figsize=(cols * 10, rows * 5))

    for i, vmap in enumerate(cpu_values):
        ax = axs.flat[i]
        plt.sca(ax)

        # Transpose heat map data to right axes
        vmap = np.array(vmap)[:-1, :].transpose()

        # Group CPU lines by NUMA nodes
        if numa_cpus:
            new_order = []
            for k, v in numa_cpus.items():
                new_order += v
            vmap = vmap[new_order]

        # Add blank row to correctly plot all rows with data
        vmap = np.vstack((vmap, np.zeros(vmap.shape[1])))

        # Draw the main heat map
        x_grid, y_grid = np.meshgrid(time_axis[i], range(len(vmap)))
        mesh = ax.pcolormesh(x_grid, y_grid, vmap, vmin=0.0, vmax=100.0, cmap='Reds')

        ax.set_xlim(time_axis[i][0], time_axis[i][-1])
        ax.set_ylim([0, vmap.shape[0] - 1])

        ax.set_title("mpstat heatmap for file '" + file_names[i] + "'")
        ax.set_xlabel("Time in seconds")

        # Separate CPUs with lines by NUMA nodes
        if numa_cpus:
            ax.grid(True, which='major', axis='y', linestyle='--', color='k')
            plt.yticks(range(0, vmap.shape[0] - 1, len(numa_cpus[0])),
                    map(lambda x: "Node " + str(x), range(len(numa_cpus.keys()))))
            ax.yaxis.set_minor_locator(MultipleLocator(1))
            ax.set_ylabel("CPUs (grouped by NUMA nodes)")
        else:
            ax.set_ylabel("CPUs")
            plt.yticks(range(vmap.shape[0]))

    #plt.subplots_adjust(left=0.05, right=0.90, top=0.95, bottom=0.1)

    cbar = fig.colorbar(mesh, cax=plt.axes((0.95, 0.1, 0.02, 0.85)), cmap='Reds')

    if image_file:
        plt.savefig(image_file)
    else:
        plt.show()

    plt.close()


def draw_dual_reports(cpu_values, numa_values, time_axis, file_names, image_file=None, numa_cpus={}):
    cols = int(np.ceil(np.sqrt(len(cpu_values))))
    rows = int(np.ceil(len(cpu_values) / cols)) * 2
    fig, axs = plt.subplots(nrows=rows, ncols=cols, figsize=(cols * 10, rows * 5))

    for i in range(rows // 2):
        for j in range(cols):
            if j + i * cols >= len(cpu_values):
                break
            # CPU graph
            ax = axs.flat[j + i * cols * 2]
            plt.sca(ax)

            # Transpose heat map data to right axes
            cpu_values[j + i * cols] = np.array(cpu_values[j + i * cols])[:-1, :].transpose()

            # Group CPU lines by NUMA nodes
            if numa_cpus:
                new_order = []
                for k, v in numa_cpus.items():
                    new_order += v
                cpu_values[j + i * cols] = cpu_values[j + i * cols][new_order]

            # Add blank row to correctly plot all rows with data
            cpu_values[j + i * cols] = np.vstack((cpu_values[j + i * cols], np.zeros(cpu_values[j + i * cols].shape[1])))

            # Draw the main heat map
            x_grid, y_grid = np.meshgrid(time_axis[j + i * cols], range(len(cpu_values[j + i * cols])))
            mesh = ax.pcolormesh(x_grid, y_grid, cpu_values[j + i * cols], vmin=0.0, vmax=100.0, cmap='Reds')

            ax.set_xlim(time_axis[j + i * cols][0], time_axis[j + i * cols][-1])
            ax.set_ylim([0, cpu_values[j + i * cols].shape[0] - 1])

            ax.set_title("CPU mpstat heatmap for file '" + file_names[j + i * cols] + "'")
            ax.set_xlabel("Time in seconds")

            # Separate CPUs with lines by NUMA nodes
            if numa_cpus:
                ax.grid(True, which='major', axis='y', linestyle='--', color='k')
                plt.yticks(range(0, cpu_values[j + i * cols].shape[0] - 1, len(numa_cpus[0])),
                        map(lambda x: "Node " + str(x), range(len(numa_cpus.keys()))))
                ax.yaxis.set_minor_locator(MultipleLocator(1))
                ax.set_ylabel("CPUs (grouped by NUMA nodes)")
            else:
                ax.set_ylabel("CPUs")
                plt.yticks(range(cpu_values[j + i * cols].shape[0]))

            # NUMA graph
            ax = axs.flat[j + i * cols * 2 + cols]
            plt.sca(ax)

            # Transpose heat map data to right axes
            numa_values[j + i * cols] = np.array(numa_values[j + i * cols])[:-1, :].transpose()

            # Add blank row to correctly plot all rows with data
            numa_values[j + i * cols] = np.vstack((numa_values[j + i * cols], np.zeros(numa_values[j + i * cols].shape[1])))

            # Draw the main heat map
            x_grid, y_grid = np.meshgrid(time_axis[j + i * cols], range(len(numa_values[j + i * cols])))
            mesh = ax.pcolormesh(x_grid, y_grid, numa_values[j + i * cols], vmin=0.0, vmax=100.0, cmap='Reds')

            ax.set_xlim(time_axis[j + i * cols][0], time_axis[j + i * cols][-1])
            ax.set_ylim([0, numa_values[j + i * cols].shape[0] - 1])

            ax.set_title("NUMA mpstat heatmap for file '" + file_names[j + i * cols] + "'")
            ax.set_xlabel("Time in seconds")

            ax.set_ylabel("Nodes")
            plt.yticks(range(numa_values[j + i * cols].shape[0]))

    #plt.subplots_adjust(left=0.05, right=0.90, top=0.95, bottom=0.1)

    cbar = fig.colorbar(mesh, cax=plt.axes((0.95, 0.1, 0.02, 0.85)), cmap='Reds')

    if image_file:
        plt.savefig(image_file)
    else:
        plt.show()

    plt.close()


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


def process_report(input_file, time_offset=0.0):
    cpus_count = 0
    time_axis = []
    cpu_values = []
    differences = []
    imbalances = []

    # Get CPUs count and start date
    reg_exp=re.compile(r".*\)\s+(\d+/\d+/\d+)\s+_.*\((\d+) CPU\).*")

    line = input_file.readline()  # read first data line
    match = reg_exp.findall(line)
    if not match:
        print("Wrong mpstat header")
        exit(1)

    start_date = datetime.strptime(match[0][0], "%m/%d/%y").date()
    cpus_count = int(match[0][1])

    input_file.readline()  # skip first empty line
    data = input_file.readline().split()  # read first data line

    if time_offset:
        curr_time = datetime.combine(start_date,
            datetime.strptime(data[0], "%H:%M:%S").time())
    else:
        curr_time = datetime.combine(start_date,
            datetime.strptime(data[0], "%H:%M:%S").time())
        time_offset = curr_time.timestamp()

    time_axis = []
    row = np.zeros(cpus_count)

    for line in input_file:
        data = line.split()
        if not data:
            cpu_values.append(row)
            time_axis.append(curr_time.timestamp() - time_offset)
            row = np.zeros(cpus_count)
            continue
        if data[0] == "Average:":
            break  # end of file
        if data[1] == "CPU":  # Time when measure started
            last_time = curr_time
            curr_time = datetime.combine(start_date,
                datetime.strptime(data[0], "%H:%M:%S").time())
            if curr_time.hour < last_time.hour:
                start_date += timedelta(days=1)
                curr_time += timedelta(days=1)
            continue
        if data[1] == "all":
            continue
        row[int(data[1])] = float(data[2]) + float(data[4])  # usr + sys values

    return cpu_values, time_axis


def process_dual_report(input_file, time_offset=0.0, measuretype="CPU"):
    cpus_count = 0
    time_axis = []
    cpu_values = []
    differences = []
    imbalances = []

    # Get CPUs count and start date
    reg_exp=re.compile(r".*\)\s+(\d+/\d+/\d+)\s+_.*\((\d+) CPU\).*")

    line = input_file.readline()  # read first data line
    match = reg_exp.findall(line)
    if not match:
        print("Wrong mpstat header")
        exit(1)

    start_date = datetime.strptime(match[0][0], "%m/%d/%y").date()

    input_file.readline()  # skip first empty line
    data = input_file.readline().split()  # read first data line

    if time_offset:
        curr_time = datetime.combine(start_date,
            datetime.strptime(data[0], "%H:%M:%S").time())
    else:
        curr_time = datetime.combine(start_date,
            datetime.strptime(data[0], "%H:%M:%S").time())
        time_offset = curr_time.timestamp()

    time_axis = []
    row = []

    for line in input_file:
        data = line.split()
        if not data:
            if row:
                cpu_values.append(row)
                time_axis.append(curr_time.timestamp() - time_offset)
                row = []
            continue
        if data[0] == "Average:":
            break  # end of file
        if data[1] == measuretype:  # Time when measure started
            last_time = curr_time
            curr_time = datetime.combine(start_date,
                datetime.strptime(data[0], "%H:%M:%S").time())
            if curr_time.hour < last_time.hour:
                start_date += timedelta(days=1)
                curr_time += timedelta(days=1)
            continue
        if data[1] == "all":
            continue
        row.append(float(data[2]) + float(data[4]))  # usr + sys values

    return cpu_values, time_axis


def create_multiple(input_files, lscpu_file):
    numa_cpus = {}
    if lscpu_file:
        numa_cpus = read_nodes(lscpu_file)

    cpu_values = {}
    time_axis = {}
    file_names = {}

    for f in input_files:
        key = f.name.rpartition("loop")[0].rstrip(".")
        mv, ta = process_report(f, 0)
        cpu_values.setdefault(key, []).append(mv)
        time_axis.setdefault(key, []).append(ta)
        file_names.setdefault(key, []).append(os.path.basename(f.name))

    for key in cpu_values.keys():
        print("Drawing " + key)
        draw_reports(cpu_values[key], time_axis[key], file_names[key],
                     key + ".png", numa_cpus)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create heatmaps from multiple mpstat data"
        " with optional alignment to system uptime and reordering by NUMA nodes.")
    parser.add_argument("input_file", nargs="+", type=argparse.FileType('r'), default=sys.stdin)
    parser.add_argument("--image-file", type=str, default=None,
                        help="Save plotted heatmap to file instead of showing")
    parser.add_argument("--lscpu-file", type=argparse.FileType('r'), default=None,
                        help="File with output of lscpu from observed machine")
    parser.add_argument("--time-offset", type=float, default=0,
                        help="Timestamp of system's boot to align time axis to uptime")
    parser.add_argument('--dual', dest='dual', action='store_true', default=False,
                        help="Plot CPU graph with consequent NUMA graph. "
                        "Requires even number of files - first all CPU files, then all NUMA files.")
    parser.add_argument('--multiple', dest='multiple', action='store_true', default=False,
                        help="Create multiple outputs grouping files by names before 'loop'")
    parser.add_argument("--title", type=str, default=None, help="Future title")

    try:
        args = parser.parse_args()
    except SystemExit:
        sys.exit(1)

    if args.multiple:
        create_multiple(args.input_file, args.lscpu_file)
        sys.exit()

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = read_nodes(args.lscpu_file)

    cpu_values = []
    numa_values = []
    time_axis = []
    file_names = []

    if not args.dual:
        for f in args.input_file:
            mv, ta = process_report(f, args.time_offset)
            cpu_values.append(mv)
            time_axis.append(ta)
            file_names.append(os.path.basename(f.name))

        draw_reports(cpu_values, time_axis, file_names, args.image_file, numa_cpus)
    else:
        if len(args.input_file) % 2 != 0:
            print("Number of files for dual graphs must be even.")
            sys.exit(1)

        for i in range(len(args.input_file) // 2):
            cpu_v, ta = process_dual_report(args.input_file[i], args.time_offset, "CPU")
            numa_v, ta2 = process_dual_report(args.input_file[i + len(args.input_file) // 2], args.time_offset, "NODE")
            if len(ta) != len(ta2):
                print("Files", args.input_file[i], "and", args.input_file[i + len(args.input_file) // 2],
                      "have different number of records.")
                continue
            cpu_values.append(cpu_v)
            numa_values.append(numa_v)
            time_axis.append(ta)
            file_names.append(os.path.basename(args.input_file[i].name))

        draw_dual_reports(cpu_values, numa_values, time_axis, file_names, args.image_file, numa_cpus)
