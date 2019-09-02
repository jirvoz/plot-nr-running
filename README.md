# plot-nr-running
Create heatmap and find imbalances from recorded *sched\_update\_nr\_running* events with *trace-cmd*.

This script reads output of `trace-cmd report` command with `sched\_update\_nr\_running` events. From this data it plots heat map showing number of active tasks on each core of processor with line graph showing imbalance between the numbers.

## Example
```bash
$ ./plot-nr-running.py example/example.trace --lscpu-file example/example-lscpu.txt
```
![Example report](example/example.png)
