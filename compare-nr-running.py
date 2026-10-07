#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compare heatmaps and imbalances of two recordings of
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
import importlib.util
import lzma
import os
import sys
from collections import namedtuple

import numpy as np

# import matplotlib
# matplotlib.use('agg')  # Make it work also on machines without tkinter
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib import collections as mc


def load_plot_nr_running():
    # plot-nr-running.py is not importable by name because of the dashes
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "plot-nr-running.py"
    )
    spec = importlib.util.spec_from_file_location("plot_nr_running", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pnr = load_plot_nr_running()

# Times are relative to the first event of each trace
Report = namedtuple(
    "Report",
    "time_axis map_values differences sums imbalances end_time",
)


def draw_report(title, base, target, image_file=None, numa_cpus=None):
    cmap = ListedColormap(
        ["#000000", "#305090", "#40b080", "#f0e020", "#f04010"]
    )
    boundaries = [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5]
    norm = BoundaryNorm(boundaries, cmap.N, clip=True)

    fig, axs = plt.subplots(
        nrows=4,
        ncols=1,
        gridspec_kw=dict(height_ratios=[4, 4, 1, 2]),
        figsize=(20, 15),
        sharex=True,
    )  # , constrained_layout=True)
    fig.subplots_adjust(hspace=0.1)

    for ax, report, label in (
        (axs[0], base, "Base"),
        (axs[1], target, "Target"),
    ):
        time_edges = np.append(
            report.time_axis, max(report.end_time, report.time_axis[-1])
        )
        mesh = pnr.draw_heatmap(
            ax, time_edges, report.map_values, cmap, norm, numa_cpus
        )
        ax.set_ylabel("CPUs ({})".format(label))

        # Draw lines with differences and sums, holding the last value
        # until the end of trace
        axs[2].step(
            time_edges,
            np.append(report.differences, report.differences[-1]),
            where="post",
            color="green" if report is base else "blue",
            alpha=0.8,
        )
        axs[3].step(
            time_edges,
            np.append(report.sums, report.sums[-1]),
            where="post",
            color="green" if report is base else "blue",
            alpha=0.8,
            label=label,
        )

        # Draw imbalances
        for i in report.imbalances:
            axs[2].plot(i[0][0], i[0][1], "rx")
        lc = mc.LineCollection(
            report.imbalances,
            colors=np.tile((1, 0, 0, 1), (len(report.imbalances), 1)),
            linewidths=2,
        )
        axs[2].add_collection(lc)

    # Create colorbar
    cbar = fig.colorbar(
        mesh,
        cax=fig.add_axes([0.95, 0.05, 0.02, 0.9]),
        extend="max",
        ticks=range(5),
    )
    cbar.ax.set_yticklabels(["0", "1", "2", "3", "4+"])
    cbar.ax.set_ylabel("Number of tasks on CPU core")
    fig.subplots_adjust(bottom=0.05, right=0.9, top=0.95, left=0.05)

    axs[2].set_ylabel("Max difference")
    axs[3].set_ylabel("Sum of tasks")
    axs[3].set_xlabel("Time since first event (seconds)")

    axs[0].set_xlim(0, max(base.end_time, target.end_time))
    axs[2].set_ylim(bottom=0)
    axs[2].grid()
    axs[3].set_ylim(bottom=0)
    axs[3].grid()

    axs[3].legend(loc="lower right", ncol=2)

    axs[0].set_title(title)

    if image_file:
        fig.savefig(image_file)
    else:
        plt.show()

    plt.close(fig)


def process_report(input_file, sampling, time_sampling, threshold, duration):
    print("Processing '{}':".format(input_file.name))
    events = pnr.read_events(input_file)
    if events is None:
        return None

    times = events[0]
    if not times:
        print("No sched_update_nr_running found. Exiting.")
        return None

    (
        time_axis,
        map_values,
        differences,
        sums,
        imbalances,
    ) = pnr.replay_events(
        *events, sampling, time_sampling, threshold, duration
    )

    if len(time_axis) == 0:
        print("No data left after sampling. Exiting.")
        return None

    if not imbalances:
        print("No imbalance found")

    # Align both traces to start at zero
    start = times[0]
    return Report(
        time_axis - start,
        map_values,
        differences,
        sums,
        [[(s - start, y), (e - start, y)] for (s, y), (e, _) in imbalances],
        times[-1] - start,
    )


def read_report(input_file, args):
    if input_file.name.endswith(".xz"):
        input_file.close()
        with lzma.open(input_file.name, "rt") as decompressed:
            return process_report(
                decompressed,
                args.sampling,
                args.time_sampling,
                args.threshold,
                args.duration,
            )
    return process_report(
        input_file,
        args.sampling,
        args.time_sampling,
        args.threshold,
        args.duration,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Compare heatmaps and imbalances of two recordings"
        " of sched_update_nr_running events with trace-cmd."
    )
    parser.add_argument(
        "base_file",
        type=argparse.FileType("r"),
        help="Base trace report, '-' for stdin",
    )
    parser.add_argument(
        "target_file",
        type=argparse.FileType("r"),
        help="Target trace report, '-' for stdin",
    )
    parser.add_argument(
        "--sampling",
        default=1,
        type=int,
        help="Sampling of plotted data to reduce drawing time"
        " - takes each N-th event. Imbalances are always searched"
        " on all events.",
    )
    parser.add_argument(
        "--time-sampling",
        default=0,
        type=int,
        help="Reduce plotted data to N records per second"
        " to shorten drawing time. Is applied after input sampling.",
    )
    parser.add_argument(
        "--threshold",
        default=2,
        type=int,
        help="Minimal difference of process count considered as imbalance",
    )
    parser.add_argument(
        "--duration",
        default=0.05,
        type=float,
        help="Minimal duration of imbalance worth reporting",
    )
    parser.add_argument(
        "--image-file",
        type=str,
        default=None,
        help="Save plotted heatmap to file instead of showing",
    )
    parser.add_argument(
        "--lscpu-file",
        type=argparse.FileType("r"),
        default=None,
        help="File with output of lscpu from observed machine",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Title of the graph. Usefull when reading input from stdin.",
    )

    try:
        args = parser.parse_args()
    except SystemExit:
        return 1

    if args.base_file is sys.stdin and args.target_file is sys.stdin:
        print("Only one of the trace reports can be read from stdin.")
        return 1

    numa_cpus = {}
    if args.lscpu_file:
        numa_cpus = pnr.read_nodes(args.lscpu_file)

    title = args.name or "Comparison of '{}' and '{}'".format(
        args.base_file.name, args.target_file.name
    )

    base = read_report(args.base_file, args)
    target = read_report(args.target_file, args)
    if base is None or target is None:
        return 1

    draw_report(title, base, target, args.image_file, numa_cpus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
