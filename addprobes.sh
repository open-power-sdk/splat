#!/bin/sh

if [ "$1" = "--delete" ]; then
	pattern="$(sep=''; echo -n "'"; for sdt in init entry acquired release; do echo -n $sep'sdt_libpthread:mutex_'$sdt'.*Tracepoint event'; sep='|'; done; echo "'")"
	sdts="$(perf list | eval egrep "$pattern" | awk '{print $1}')"
	if [ -z "$sdts" ]; then
		echo "No probes found."
		exit 1
	fi
	perfarg="probe"
	for sdt in $sdts; do
		perfarg="$perfarg --del $sdt"
	done
	set -x
	exec perf $perfarg
fi

perfarg="probe"
for sdt_mutex in init entry acquired release; do
	perfarg="$perfarg --add sdt_libpthread:mutex_$sdt_mutex"
done
echo "$perfarg"
perf $perfarg
