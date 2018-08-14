#!/bin/sh

# entry, init, release
for sdt in init entry acquired release; do
	perf probe --add "sdt_libpthread:mutex_$sdt"
	for probe in $(perf list | grep 'sdt_libpthread:mutex_'$sdt'.*Tracepoint event' | awk '{print $1}'); do
		echo $probe
	done
done
