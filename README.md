# Project Description
This project calculates statistics for low-level synchronization primitives:
1. System-wide, per process, per task: lock acquisition attempts (`trylock`), acquisitions, failures, releases
1. System-wide, per process, per task: average, minimum, maximum wait time for acquisitions, hold time

Usage is a three-step process (described in more detail below):
1. Define and enable tracepoints.
1. Collect trace data.
1. Process collected data.

or, a single step:

1. Define and enable tracepoints.
1. Record and report.

## Contributing to the project
We welcome contributions to the splat project in many forms. There's always plenty to do! Full details of how to contribute to this project are documented in the [CONTRIBUTING.md](CONTRIBUTING.md) file.

## Maintainers
The project's [maintainers](MAINTAINERS.txt) are responsible for reviewing and merging all pull requests and they guide the over-all technical direction of the project.

## Communication <a name="communication"></a>
We use [SDK Tools for Power Slack](https://toolsforpower.slack.com/) for communication.

## Installing
Currently, the only project file used in processing is `splat.py`.  One could download that directly from the [splat GitHub repository](https://github.com/open-power-sdk/splat), or clone the git repository and use it from there:
```
    $ git clone https://github.com/open-power-sdk/splat.git
    $ ls splat/splat.py
    splat/splat.py
```

## Documentation

### Set up

1. If you wish to run perf as a non-root user, you'll need superuser authority to set some things up:

   1. Make sure you have read/write access to `/sys/kernel/debug/tracing`:
      ```
      /usr/bin/sudo /usr/bin/mount -o remount,mode=755 /sys/kernel/debug
      ```

   1. Enable any user to be able to collect system-wide events:
      ```
      echo -1 | /usr/bin/sudo /usr/bin/tee /proc/sys/kernel/perf_event_paranoid
      ```
1. Install `glibc-debuginfo` package.


### Define and enable tracepoints

1. With superuser privileges, `./addprobes.sh`


### Collect and process trace data in one step

1. ./splat.py --record all *command --args*


### Process trace data

1. Simple!
```
    perf script -s ./splat.py
```

Or, even simpler, `splat.py` can be used directly (it will execute `perf` itself):
```
    ./splat.py
```

Like `perf`, `splat.py` will operate on `perf.data` by default.  To operate on a different file:
```
    ./splat.py my-trace-file.data
```

### Help

The full command help can be displayed:
```
    ./splat.py --help
```

### A note on `perf` versions

As of this writing, there are two versions of the Python APIs for `perf`:
1. An older API, which is currently found in all major Linux distributions
2. A newer API, which is found in newer kernels

The most significant difference between the two APIs, with respect to `splat`, is that the older API does not provide sufficient information to determine the process IDs for tasks.

`splat` attempts to use the newer API first.  If that fails, `splat` will revert to using the older API automatically.

`splat` is able to use either API by using the `--api` command option.  `--api=1` selects the older API, and is the default API selection (so `--api=1` is not required).  `--api=2` selects the newer API.

When using the older API, all tasks will be grouped under an `unknown` process ID.  One may use the older API on any kernel.

When using the new API on newer kernels, tasks will be grouped under their respective process IDs.

When attempting to use the new API on older kernels, `splat` will fail with an error like the following:
```
    TypeError: powerpc__hcall_entry_new() takes exactly 10 arguments (9 given)
```

### A note on `perf` trace data

`splat.py` keeps track of task states as it parses the `perf` data file.  This naturally depends on the events in the file being ordered in time.  Unfortunately, `perf` does not guarantee that the events in a trace file are in time order.  `splat.py` attempts to process the events in any trace file in time order by looking ahead and reordering if needed.  To keep the process of looking ahead from taking too much memory, it is limited in the number of events.  By default, this limit is 20 events.  This limit can be changed by using the `--window` option with `splat.py`.

Regardless of success for `splat.py` looking ahead, the `perf` command will still report that it detected out-of-order events:
```
Warning:
2 out of order events recorded.
```
These warnings can be ignored.

If, however, the look-ahead window for `splat.py` is too small, `splat.py` will report an error:
```
Error: OUT OF ORDER events detected.
  Try increasing the size of the look-ahead window with --window=<n>
```
As suggested, increasing the look-ahead window size sufficiently will address this issue.

## Still Have Questions?
For general purpose questions, please use [StackOverflow](http://stackoverflow.com/questions/tagged/toolsforpower).

## License <a name="license"></a>
The [splat](https://github.com/open-power-sdk/splat) project uses the [GPL License Version 2.0](LICENSE) software license.

## Related information
The [splat](https://github.com/open-power-sdk/splat) project is inspired by the [AIX splat tool](https://www.ibm.com/support/knowledgecenter/en/ssw_aix_72/com.ibm.aix.cmds5/splat.htm)
