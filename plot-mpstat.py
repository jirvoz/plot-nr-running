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
from matplotlib.ticker import MultipleLocator

# See plot-nr-running.py: one tick per CPU can exceed matplotlib's tick limit
MINOR_TICK_CPU_LIMIT = 256

# Above this many CPUs, labelling every CPU row makes the labels overlap.
CPU_LABEL_LIMIT = 64

HEADER_RE = re.compile(r"\)\s+(\S+)\s+_\S+_\s+\((\d+) CPU\)")
# Date formats used by sysstat in C, en_US and ISO (S_TIME_FORMAT=ISO) locales
DATE_FORMATS = ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d")


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


def time_edges(time_axis):
    # Each mpstat block starts with a header holding the start time of its
    # measurement interval, the values are averages over that interval
    interval = np.median(np.diff(time_axis)) if len(time_axis) > 1 else 1.0
    return np.append(time_axis, time_axis[-1] + interval)


def draw_cpu_heatmap(ax, time_axis, values, title, numa_cpus=None):
    order, nodes = cpu_layout(numa_cpus, values.shape[1])
    edges = time_edges(time_axis)
    mesh = ax.pcolormesh(edges, np.arange(len(order) + 1), values[:, order].transpose(),
                         vmin=0.0, vmax=100.0, cmap='Reds', shading='flat', rasterized=True)

    ax.set_xlim(edges[0], edges[-1])
    ax.set_ylim(0, len(order))

    ax.set_title(title)
    ax.set_xlabel("Time in seconds")

    # Separate CPUs with lines by NUMA nodes
    if nodes:
        ax.grid(True, which='major', axis='y', linestyle='--', color='k')
        ax.set_yticks([first for first, _ in nodes])
        ax.set_yticklabels([label for _, label in nodes])
        if len(order) <= MINOR_TICK_CPU_LIMIT:
            ax.yaxis.set_minor_locator(MultipleLocator(1))
        ax.set_ylabel("CPUs (grouped by NUMA nodes)")
    else:
        ax.set_ylabel("CPUs")
        if len(order) <= CPU_LABEL_LIMIT:
            ax.set_yticks(np.arange(len(order)) + 0.5)
            ax.set_yticklabels(order)

    return mesh


def draw_node_heatmap(ax, time_axis, values, title):
    edges = time_edges(time_axis)
    nodes_count = values.shape[1]
    mesh = ax.pcolormesh(edges, np.arange(nodes_count + 1), values.transpose(),
                         vmin=0.0, vmax=100.0, cmap='Reds', shading='flat', rasterized=True)

    ax.set_xlim(edges[0], edges[-1])
    ax.set_ylim(0, nodes_count)

    ax.set_title(title)
    ax.set_xlabel("Time in seconds")
    ax.set_ylabel("Nodes")
    ax.set_yticks(np.arange(nodes_count) + 0.5)
    ax.set_yticklabels(range(nodes_count))

    return mesh


def finish_figure(fig, mesh, image_file):
    fig.subplots_adjust(right=0.88)
    cbar = fig.colorbar(mesh, cax=fig.add_axes((0.91, 0.1, 0.02, 0.8)))
    cbar.ax.set_ylabel("CPU utilization (%)")

    if image_file:
        fig.savefig(image_file)
    else:
        plt.show()

    plt.close(fig)


def draw_reports(cpu_values, time_axis, file_names, image_file=None, numa_cpus=None):
    cols = int(np.ceil(np.sqrt(len(cpu_values))))
    rows = int(np.ceil(len(cpu_values) / cols))
    fig, axs = plt.subplots(nrows=rows, ncols=cols, figsize=(cols * 10, rows * 8), squeeze=False)

    for i, vmap in enumerate(cpu_values):
        mesh = draw_cpu_heatmap(axs.flat[i], time_axis[i], vmap,
                                "mpstat heatmap for file '" + file_names[i] + "'", numa_cpus)

    for ax in axs.flat[len(cpu_values):]:
        ax.set_visible(False)

    finish_figure(fig, mesh, image_file)


def draw_dual_reports(cpu_values, numa_values, time_axis, file_names, image_file=None, numa_cpus=None):
    cols = int(np.ceil(np.sqrt(len(cpu_values))))
    rows = int(np.ceil(len(cpu_values) / cols)) * 2
    fig, axs = plt.subplots(nrows=rows, ncols=cols, figsize=(cols * 10, rows * 8), squeeze=False)

    for k in range(len(cpu_values)):
        # CPU graph with consequent NUMA graph below it
        i, j = divmod(k, cols)
        draw_cpu_heatmap(axs[2 * i, j], time_axis[k], cpu_values[k],
                         "CPU mpstat heatmap for file '" + file_names[k] + "'", numa_cpus)
        mesh = draw_node_heatmap(axs[2 * i + 1, j], time_axis[k], numa_values[k],
                                 "NUMA mpstat heatmap for file '" + file_names[k] + "'")

    for k in range(len(cpu_values), rows // 2 * cols):
        i, j = divmod(k, cols)
        axs[2 * i, j].set_visible(False)
        axs[2 * i + 1, j].set_visible(False)

    finish_figure(fig, mesh, image_file)


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


def read_header(input_file):
    """Return (start date, CPUs count) from the mpstat header, or None."""
    for line in input_file:
        # Skip comments and empty lines before the header
        if line.startswith('#') or not line.strip():
            continue
        match = HEADER_RE.search(line)
        if not match:
            break
        for date_format in DATE_FORMATS:
            try:
                return datetime.strptime(match.group(1), date_format).date(), int(match.group(2))
            except ValueError:
                pass
        break

    print("Wrong mpstat header in file '{}'".format(input_file.name))
    return None


def parse_time(data):
    """Return time of mpstat line and its remaining fields, for both 24 and 12-hour clock."""
    if len(data) > 1 and data[1] in ("AM", "PM"):
        return datetime.strptime(data[0] + " " + data[1], "%I:%M:%S %p").time(), data[2:]
    return datetime.strptime(data[0], "%H:%M:%S").time(), data[1:]


def read_blocks(input_file, start_date, measuretype):
    """Yield (time, rows) for each measurement in mpstat output.

    Each row holds the fields after the time column, starting with the CPU
    or node number.
    """
    curr_time = None
    rows = []
    for line in input_file:
        data = line.split()
        if not data:
            if rows:
                yield curr_time, rows
                rows = []
            continue
        if data[0] == "Average:":
            break  # end of file
        line_time, fields = parse_time(data)
        if fields[0] == measuretype:  # Time when measure started
            timestamp = datetime.combine(start_date, line_time)
            if curr_time is not None and timestamp < curr_time:
                # Measurement continues past midnight
                start_date += timedelta(days=1)
                timestamp += timedelta(days=1)
            curr_time = timestamp
            continue
        if fields[0] == "all":
            continue
        rows.append(fields)

    if rows:
        yield curr_time, rows


def process_report(input_file, time_offset=0.0):
    header = read_header(input_file)
    if header is None:
        return None
    start_date, cpus_count = header

    time_axis = []
    cpu_values = []
    for curr_time, rows in read_blocks(input_file, start_date, "CPU"):
        if not time_offset:
            time_offset = curr_time.timestamp()
        row = np.zeros(cpus_count)
        for fields in rows:
            row[int(fields[0])] = float(fields[1]) + float(fields[3])  # usr + sys values
        cpu_values.append(row)
        time_axis.append(curr_time.timestamp() - time_offset)

    if not cpu_values:
        print("No mpstat data in file '{}'".format(input_file.name))
        return None

    return np.array(cpu_values), np.array(time_axis)


def process_dual_report(input_file, time_offset=0.0, measuretype="CPU"):
    header = read_header(input_file)
    if header is None:
        return None
    start_date = header[0]

    time_axis = []
    values = []
    for curr_time, rows in read_blocks(input_file, start_date, measuretype):
        if not time_offset:
            time_offset = curr_time.timestamp()
        values.append([float(fields[1]) + float(fields[3]) for fields in rows])  # usr + sys values
        time_axis.append(curr_time.timestamp() - time_offset)

    if not values:
        print("No mpstat data in file '{}'".format(input_file.name))
        return None

    return np.array(values), np.array(time_axis)


def create_multiple(input_files, lscpu_file):
    numa_cpus = {}
    if lscpu_file:
        numa_cpus = read_nodes(lscpu_file)

    cpu_values = {}
    time_axis = {}
    file_names = {}

    failed = False
    for f in input_files:
        key = f.name.rpartition("loop")[0].rstrip(".")
        report = process_report(f, 0)
        if report is None:
            failed = True
            continue
        mv, ta = report
        cpu_values.setdefault(key, []).append(mv)
        time_axis.setdefault(key, []).append(ta)
        file_names.setdefault(key, []).append(os.path.basename(f.name))

    for key in cpu_values.keys():
        print("Drawing " + key)
        draw_reports(cpu_values[key], time_axis[key], file_names[key],
                     key + ".png", numa_cpus)

    return not failed


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
        sys.exit(0 if create_multiple(args.input_file, args.lscpu_file) else 1)

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = read_nodes(args.lscpu_file)

    cpu_values = []
    numa_values = []
    time_axis = []
    file_names = []
    failed = False

    if not args.dual:
        for f in args.input_file:
            report = process_report(f, args.time_offset)
            if report is None:
                failed = True
                continue
            mv, ta = report
            cpu_values.append(mv)
            time_axis.append(ta)
            file_names.append(os.path.basename(f.name))

        if cpu_values:
            draw_reports(cpu_values, time_axis, file_names, args.image_file, numa_cpus)
    else:
        if len(args.input_file) % 2 != 0:
            print("Number of files for dual graphs must be even.")
            sys.exit(1)

        for i in range(len(args.input_file) // 2):
            cpu_report = process_dual_report(args.input_file[i], args.time_offset, "CPU")
            numa_report = process_dual_report(args.input_file[i + len(args.input_file) // 2], args.time_offset, "NODE")
            if cpu_report is None or numa_report is None:
                failed = True
                continue
            cpu_v, ta = cpu_report
            numa_v, ta2 = numa_report
            if len(ta) != len(ta2):
                failed = True
                print("Files", args.input_file[i], "and", args.input_file[i + len(args.input_file) // 2],
                      "have different number of records.")
                continue
            cpu_values.append(cpu_v)
            numa_values.append(numa_v)
            time_axis.append(ta)
            file_names.append(os.path.basename(args.input_file[i].name))

        if cpu_values:
            draw_dual_reports(cpu_values, numa_values, time_axis, file_names, args.image_file, numa_cpus)

    sys.exit(1 if failed or not cpu_values else 0)
