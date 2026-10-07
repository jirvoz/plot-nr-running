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
import lzma
import sys
import re
from array import array

import numpy as np
# import matplotlib
# matplotlib.use('agg')  # For machines without tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib import collections as mc
from matplotlib.ticker import MultipleLocator

# Per-CPU minor ticks are unreadable above this many CPUs and, more
# importantly, requesting one tick per CPU can exceed matplotlib's internal
# tick limit (Locator.MAXTICKS == 1000) on many-core systems, which aborts
# plotting. On such machines we drop the per-CPU grid and keep only the
# per-NUMA-node major ticks.
MINOR_TICK_CPU_LIMIT = 256

# Above this many CPUs, labelling every CPU row makes the labels overlap.
CPU_LABEL_LIMIT = 64

# Number of heat map cells (events x CPUs) replayed at once. Bounds the
# memory used while reconstructing per-CPU state from the events.
REPLAY_CHUNK_CELLS = 1 << 22

HEADER_RE = re.compile(r"^cpus=(\d+)$")
EVENT_RE = re.compile(r"^.*-(\d+).*\s(\d+[.]\d+): sched_update_nr_running: cpu=(\d+) change=([-]?\d+) nr_running=(\d+)")


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
    if len(listed) != sum(len(cpus) for cpus in numa_cpus.values()) or missing:
        print("WARNING: CPUs in lscpu file do not match the {} CPUs in the trace.".format(cpus_count))
    if missing:
        nodes.append((len(order), "Unknown"))
        order += missing

    return order, nodes


def draw_heatmap(ax, time_edges, states, cmap, norm, numa_cpus=None):
    """Draw per-CPU states (samples x CPUs) as a heat map, one row per CPU.

    time_edges has one more item than states has rows: sample i is drawn
    from time_edges[i] until the next sample.
    """
    order, nodes = cpu_layout(numa_cpus, states.shape[1])
    mesh = ax.pcolormesh(
        time_edges,
        np.arange(len(order) + 1),
        states[:, order].transpose(),
        cmap=cmap,
        norm=norm,
        shading='flat',
        rasterized=True,
    )

    ax.set_xlim(time_edges[0], time_edges[-1])
    ax.set_ylim(0, len(order))

    # Separate CPUs with lines by NUMA nodes
    if nodes:
        ax.set_yticks([first for first, _ in nodes])
        ax.set_yticklabels([label for _, label in nodes])
        ax.grid(True, which='major', axis='y', linestyle='--', color='w')
        if len(order) <= MINOR_TICK_CPU_LIMIT:
            ax.yaxis.set_minor_locator(MultipleLocator(1))
    elif len(order) <= CPU_LABEL_LIMIT:
        ax.set_yticks(np.arange(len(order)) + 0.5)
        ax.set_yticklabels(order)

    return mesh


def draw_report(title, time_axis, map_values, differences, imbalances, sums, image_file=None, numa_cpus=None,
                end_time=None):
    if end_time is None:
        end_time = time_axis[-1]
    # The last sample lasts until the end of trace. A trace with a single
    # event gets a nominal width to keep the plot visible.
    time_edges = np.append(time_axis, max(end_time, time_axis[-1]))
    if time_edges[-1] == time_edges[0]:
        time_edges[-1] += 1e-3

    cmap = ListedColormap(['#000000', '#305090', '#40b080', '#f0e020', '#f04010'])
    boundaries = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5]
    norm = BoundaryNorm(boundaries, cmap.N, clip=True)

    fig, axs = plt.subplots(nrows=3, ncols=1, gridspec_kw=dict(height_ratios=[4, 1, 2]),
                            sharex=True, figsize=(20, 10))  # , constrained_layout=True)
    fig.subplots_adjust(hspace=0.05)

    # Draw the main heat map
    mesh = draw_heatmap(axs[0], time_edges, np.asarray(map_values), cmap, norm, numa_cpus)

    # Create colorbar
    cbar = fig.colorbar(mesh, cax=fig.add_axes([0.95, 0.05, 0.02, 0.9]),
                        extend='max', ticks=range(5))
    cbar.ax.set_yticklabels(['0', '1', '2', '3', '4+'])
    cbar.ax.set_ylabel("Number of tasks on CPU core")
    fig.subplots_adjust(bottom=0.05, right=0.9, top=0.95, left=0.05)

    # Draw line with differences, holding the last value until the end of trace
    axs[1].step(time_edges, np.append(differences, differences[-1]), where='post', color='black', alpha=0.8)

    # Draw imbalances
    for i in imbalances:
        axs[1].plot(i[0][0], i[0][1], 'rx')
    lc = mc.LineCollection(imbalances,
                           colors=np.tile((1, 0, 0, 1), (len(imbalances), 1)),
                           linewidths=2)
    axs[1].add_collection(lc)

    # Draw line with sums
    axs[2].step(time_edges, np.append(sums, sums[-1]), where='post', color='black', alpha=0.8)

    axs[0].set_ylabel("CPUs")
    axs[1].set_ylabel("Max difference")
    axs[2].set_ylabel("Sum of tasks")
    axs[2].set_xlabel("Timestamp (seconds)")

    axs[1].set_ylim(bottom=0)
    axs[1].grid()
    axs[2].set_ylim(bottom=0)
    axs[2].grid()

    axs[0].set_title(title)

    if image_file:
        fig.savefig(image_file)
    else:
        plt.show()

    # Release the figure; pyplot keeps a reference to every figure it creates,
    # so a caller that renders many files in one process leaks one each time.
    plt.close(fig)


def read_events(input_file):
    """Parse the trace report.

    Returns (times, cpus, nr_running, initial) where initial is the number
    of tasks on each CPU before the first recorded event, or None when the
    input is not a usable trace report.
    """
    line_count = 0
    while True:
        line = input_file.readline()
        line_count += 1
        match = HEADER_RE.match(line)
        if match:
            cpus_count = int(match.group(1))
            break
        if "empty" in line:
            # Information of missing records for specific cpu
            continue
        print("ERROR: Couldn't get number of CPUs from the trace file.")
        print("       Unexpected trace file format. First line is expected to have form '{}'".format(HEADER_RE.pattern))
        print("       Input line: '{}'".format(line.rstrip('\n')))
        print("       Exiting")
        return None

    times = array('d')
    cpus = array('i')
    values = array('i')
    # CPUs without any event were idle for the whole trace
    initial = [0] * cpus_count
    seen = [False] * cpus_count
    signed_change = False

    for line in input_file:
        line_count += 1
        match = EVENT_RE.match(line)

        # Check the correct event
        if not match:
            if "sched_update_nr_running:" in line:
                print("WARNING: Line number {} contains 'sched_update_nr_running:' string, but does not match regex '{}'!".format(line_count, EVENT_RE.pattern))
                print(line, end='')
            continue

        # pid = int(match.group(1))
        point_time = float(match.group(2))
        cpu = int(match.group(3))
        change = int(match.group(4))
        nr_running = int(match.group(5))

        if cpu >= cpus_count:
            print("WARNING: Line number {} reports cpu={}, but the trace has only {} CPUs. Skipping.".format(line_count, cpu, cpus_count))
            continue

        if change < 0:
            signed_change = True

        if not seen[cpu]:
            # First time we got data for this CPU, so the value before the
            # trace started is nr_running - change. Older kernels record
            # the change unsigned, so a negative result means a decrement.
            seen[cpu] = True
            previous = nr_running - change
            if previous < 0:
                previous = nr_running + change
            initial[cpu] = previous

        times.append(point_time)
        cpus.append(cpu)
        values.append(nr_running)

    if times and not signed_change:
        print("NOTE: No negative 'change' values found, the kernel probably records them unsigned."
              " Values before the first event of each CPU may be inaccurate.")

    return times, cpus, values, initial


def replay_events(times, cpus, values, initial, sampling, time_sampling, threshold, duration):
    """Reconstruct the number of tasks on every CPU after each event.

    Imbalances are searched on every event. Only the sampled states are
    kept for plotting. Returns (time_axis, states, differences, sums,
    imbalances), where states[i] is the state from time_axis[i] until the
    next sample.
    """
    times = np.frombuffer(times, dtype=np.float64)
    cpus = np.frombuffer(cpus, dtype=np.intc)
    values = np.frombuffer(values, dtype=np.intc)
    cpus_count = len(initial)
    columns = np.arange(cpus_count)
    state = np.array(initial, dtype=np.int32)

    sampling = max(sampling, 1)
    sample_period = 1.0 / time_sampling if time_sampling > 0 else 0
    chunk = max(1024, REPLAY_CHUNK_CELLS // cpus_count)

    time_axis = []
    states = []
    differences = []
    sums = []
    imbalances = []
    imbalance_start = None
    last_sample_time = None

    def end_imbalance(start, end):
        # Print and store long imbalances
        if end - start >= duration:
            imbalances.append([(start, threshold), (end, threshold)])
            print(f"Imbalance from timestamp {start} lasting {end - start} seconds")

    for first in range(0, len(times), chunk):
        chunk_times = times[first:first + chunk]
        rows = np.arange(1, len(chunk_times) + 1)

        # Row 0 holds the state before this chunk, row i the value changed by
        # event i. Forward-fill each CPU column with its last changed value.
        grid = np.empty((len(rows) + 1, cpus_count), dtype=np.int32)
        grid[0] = state
        grid[rows, cpus[first:first + chunk]] = values[first:first + chunk]
        source = np.zeros(grid.shape, dtype=np.intp)
        source[rows, cpus[first:first + chunk]] = rows
        np.maximum.accumulate(source, axis=0, out=source)
        filled = grid[source, columns][1:]
        state = filled[-1]

        diff = filled.max(axis=1) - filled.min(axis=1)

        # Find starts and ends of imbalances
        imbalanced = diff >= threshold
        before = np.concatenate(([imbalance_start is not None], imbalanced[:-1]))
        for i in np.flatnonzero(imbalanced != before):
            if imbalanced[i]:
                imbalance_start = float(chunk_times[i])
            else:
                end_imbalance(imbalance_start, float(chunk_times[i]))
                imbalance_start = None

        # Store plotting data with optional sampling
        selected = np.flatnonzero((first + rows) % sampling == 0)
        if sample_period:
            kept = []
            for i in selected:
                if last_sample_time is None or chunk_times[i] - last_sample_time >= sample_period:
                    kept.append(i)
                    last_sample_time = chunk_times[i]
            selected = np.array(kept, dtype=np.intp)

        time_axis.append(chunk_times[selected])
        states.append(filled[selected])
        differences.append(diff[selected])
        sums.append(filled[selected].sum(axis=1))

    # Check for unreported imbalance lasting to the very end of input
    if imbalance_start is not None:
        end_imbalance(imbalance_start, float(times[-1]))

    return (np.concatenate(time_axis), np.concatenate(states), np.concatenate(differences),
            np.concatenate(sums), imbalances)


def process_report(title, input_file, sampling, time_sampling, threshold, duration, image_file=None, numa_cpus=None):
    events = read_events(input_file)
    if events is None:
        # Return rather than sys.exit(): process_report is reusable, and a
        # SystemExit here would tear down any caller that imports it.
        return None

    times = events[0]
    if not times:
        print("No sched_update_nr_running found. Exiting.")
        return None

    time_axis, map_values, differences, sums, imbalances = replay_events(
        *events, sampling, time_sampling, threshold, duration)

    if len(time_axis) == 0:
        print("No data left after sampling. Exiting.")
        return None

    if not imbalances:
        print("No imbalance found")

    draw_report(title, time_axis, map_values, differences, imbalances, sums, image_file, numa_cpus,
                end_time=times[-1])
    return time_axis, map_values, differences, imbalances


def main():
    parser = argparse.ArgumentParser(
        description="Create heatmap and find imbalances from recorded"
        " sched_update_nr_running events with trace-cmd.")
    parser.add_argument("input_file", nargs="?", type=argparse.FileType('r'), default=sys.stdin)
    parser.add_argument("--sampling", default=1, type=int,
                        help="Sampling of plotted data to reduce drawing time"
                        " - takes each N-th event. Is applied before time"
                        " sampling. Imbalances are always searched on all events.")
    parser.add_argument("--time-sampling", default=0, type=int,
                        help="Reduce plotted data to N records per second"
                        " to shorten drawing time. Is applied after input sampling.")
    parser.add_argument("--threshold", default=2, type=int,
                        help="Minimal difference of process count considered as imbalance")
    parser.add_argument("--duration", default=0.05, type=float,
                        help="Minimal duration of imbalance worth reporting")
    parser.add_argument("--image-file", type=str, default=None,
                        help="Save plotted heatmap to this file. Defaults to INPUT_FILE.png,"
                        " the heatmap is shown in a window when reading from stdin.")
    parser.add_argument("--lscpu-file", type=argparse.FileType('r'), default=None,
                        help="File with output of lscpu from observed machine")
    parser.add_argument("--name", type=str, default=None,
                        help="Filename to be displayed in graph."
                        " Usefull when reading input from stdin.")
    parser.add_argument("--title", type=str, default=None,
                        help="Title of the graph. Overrides --name.")

    try:
        args = parser.parse_args()
    except SystemExit:
        return 1

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = read_nodes(args.lscpu_file)

    title = args.title or "Plot of '{}'".format(args.name or args.input_file.name)

    if not args.image_file and args.input_file is not sys.stdin:
        args.image_file = args.input_file.name + ".png"

    if args.input_file.name.endswith(".xz"):
        args.input_file.close()
        with lzma.open(args.input_file.name, 'rt') as decompressed:
            result = process_report(title, decompressed, args.sampling,
                                    args.time_sampling, args.threshold,
                                    args.duration, args.image_file, numa_cpus)
    else:
        result = process_report(title, args.input_file, args.sampling,
                                args.time_sampling, args.threshold,
                                args.duration, args.image_file, numa_cpus)

    return 0 if result is not None else 1


if __name__ == '__main__':
    sys.exit(main())
