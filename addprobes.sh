#!/bin/sh

perfarg="probe"

if [ "$1" = "--delete" ]; then
	perf probe -x /lib64/libpthread.so.0 --del=pthread_mutex_trylock --del=pthread_mutex_trylock_ret

	pattern="$(sep=''; echo -n "'"; for sdt in init entry acquired release; do echo -n $sep'sdt_libpthread:mutex_'$sdt'.*Tracepoint event'; sep='|'; done; echo "'")"
	sdts="$(perf list | eval egrep "$pattern" | awk '{print $1}')"
	if [ -z "$sdts" ]; then
		echo "No probes found."
		exit 1
	fi
	for sdt in $sdts; do
		perfarg="$perfarg --del $sdt"
	done
	set -x
	exec perf $perfarg
fi

perf "$perfarg" -x /lib64/libpthread.so.0 --add='pthread_mutex_trylock mutex' --add=pthread_mutex_trylock_ret='pthread_mutex_trylock%return $retval'
if [ $? -ne 0 ]; then
	echo "Failed to probe events with symbols in libpthread.so.  You may need to install glibc-debuginfo package."
	exit 1
fi

for sdt_mutex in init entry acquired release; do
	perfarg="$perfarg --add sdt_libpthread:mutex_$sdt_mutex"
done

echo "$perfarg"
perf $perfarg
