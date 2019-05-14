#!/bin/sh

LIB=/lib64/libpthread.so.0

AT_LIBS=/opt/at*.*/lib64/libpthread.so.0

perfarg="probe"

if [ "$1" = "--delete" ]; then
	pattern="$(sep=''; echo -n "'"; for probe in trylock trylock_ret; do echo -n $sep'probe_libpthread:pthread_mutex_'$probe'.*Tracepoint event'; sep='|'; done; echo "'")"
	probes="$(perf list | eval egrep "$pattern" | awk '{print $1}')"

	pattern="$(sep=''; echo -n "'"; for sdt in init entry acquired release; do echo -n $sep'sdt_libpthread:mutex_'$sdt'.*Tracepoint event'; sep='|'; done; echo "'")"
	sdts="$(perf list | eval egrep "$pattern" | awk '{print $1}')"

	if [ -z "$probes$sdts" ]; then
		echo "No probes found."
		exit 1
	fi

	for probe in $probes $sdts; do
		perfarg="$perfarg --del $probe"
	done
	exec perf $perfarg
fi

for lib in $AT_LIBS; do
	perf buildid-cache --add $lib
done

for lib in "$LIB" $AT_LIBS; do
	perf "$perfarg" -x "$lib" --force --add='pthread_mutex_trylock mutex' --add=pthread_mutex_trylock_ret='pthread_mutex_trylock%return $retval'
	if [ $? -ne 0 -a "$lib" = "$LIB" ]; then
		echo "Failed to probe events with symbols in $lib.  You may need to install glibc-debuginfo package."
		exit 1
	fi
done

perfarg="$perfarg --force"
for sdt_mutex in init entry acquired release; do
	perfarg="$perfarg --add sdt_libpthread:mutex_$sdt_mutex"
done

echo perf "$perfarg"
perf $perfarg
