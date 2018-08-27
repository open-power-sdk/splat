#!/bin/sh
eventlist='{'
for i in $(perf list | grep 'sdt_libpthread:.*\[Tracepoint event]' | awk '{print $1}'); do
	eventlist="$eventlist$comma$i"
	comma=,
done
eventlist="$eventlist}"

exec perf record -e "$eventlist" $*
