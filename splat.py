#!/usr/bin/python
# Copyright (c) IBM 2017 All Rights Reserved.
# Project name: splat
# This project is licensed under the GPL License 2.0, see LICENSE.

import os
import sys
import argparse
import subprocess

if 'PERF_EXEC_PATH' in os.environ:
	sys.path.append(os.environ['PERF_EXEC_PATH'] + \
		'/scripts/python/Perf-Trace-Util/lib/Perf/Trace')

def debug_print(s):
	if params.debug:
		print s

parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
	description='''
Report per-task, per-process, and system-wide lock statistics

Process a perf format trace file containing some or all of the following event sets:
- sdt_libpthread:mutex_acquired
- sdt_libpthread:mutex_entry
- sdt_libpthread:mutex_release
- sched:sched_switch
- sched:sched_migrate_task
- sched:sched_process_fork, sched:sched_process_exec, sched:sched_process_exit

Report the following statistics
- per-process, perf-task, system-wide:
  - per-lock:
    - acquired count
    - elapsed, minimum, maximum, average wait time
    - elapsed, minimum, maximum, average hold time
''',
	epilog='''
Establish tracepoints:
$ perf probe --add sdt_libpthread:mutex_entry
$ perf probe --add sdt_libpthread:mutex_acquired
$ perf probe --add sdt_libpthread:mutex_release

Note: there may be multiple tracepoints established at each "perf probe" step above.  All tracepoints should be recorded in subsequent steps.

Record using perf (to perf.data file):
$ perf record -e '{sdt_libpthread:mutex_acquired,sdt_libpthread_mutex_entry,sdt_libpthread_mutex_release ...}' command

Note: record all tracepoints established above.

Generate report (from perf.data file):
$ ./splat.py

Or, record and report in a single step:
$ ./splat.py --record all command
''')
parser.add_argument('--debug', action='store_true', help='enable debugging output')
parser.add_argument('--window', type=int, help='maximum event sequence length for correcting out-of-order events', default=40)
parser.add_argument('--record',
	metavar='EVENTLIST',
	help="record events (instead of generating report). "
		"Specify event group(s) as a comma-separated list from "
		"{all,pthread,sched}.")
parser.add_argument('file_or_command',
	nargs=argparse.REMAINDER,
	help="the perf format data file to process (default: \"perf.data\"), or "
		"the command string to record (with \"--record\")",
	metavar='ARG',
	default='perf.data')
parser.add_argument('--api', type=int, help='use newer(2) perf API', default=2)
params = parser.parse_args()

if params.record:
	eventlist = ''
	comma = ''
	groups = params.record.split(',')
	#if 'all' in groups or 'sched' in groups:
	#	eventlist = eventlist + comma + "sched:sched_switch," \
	#	"sched:sched_process_fork,sched:sched_process_exec," \
	#	"sched:sched_process_exit"
	#	comma = ','
	#if 'all' in groups or 'pthread' in groups:
	#	eventlist = eventlist + comma + \
	#		'raw_syscalls:sys_enter,raw_syscalls:sys_exit'
	#	comma = ','
	if 'all' not in groups:
		print "Only 'all' is currently supported for recording groups."
		sys.exit(1)
	eventlist = 'sdt_libpthread:*' # hack, should be refined
	eventlist = '{' + eventlist + '}'
	command = ['perf', 'record', '--quiet', '--all-cpus', '-g',
		'--event', eventlist ] + params.file_or_command
	if params.debug:
		print command
	subprocess.call(command)
	params.file_or_command = []

try:
	from perf_trace_context import *
except:
	debug_print("Relaunching under \"perf\" command...")
	if len(params.file_or_command) == 0:
		params.file_or_command = [ "perf.data" ]
	sys.argv = ['perf', 'script', '-i' ] + params.file_or_command + [ '-s', sys.argv[0] ]
	sys.argv.append('--')
	sys.argv += ['--window', str(params.window)]
	sys.argv += ['--api', str(params.api)]
	if params.debug:
		sys.argv.append('--debug')
	debug_print(sys.argv)
	os.execvp("perf", sys.argv)
	sys.exit(1)

# perf added an additional parameter to event handlers, perf_sample_dict,
# in Linux 4.14 (commit a641860550f05a4b8889dca61aab73c84b2d5e16), which
# altered the event handler API in a binary-incompatible way.
# Using the new API on a system which does not support it results in an
# exception like:
#   TypeError: event__handler() takes exactly 11 arguments (10 given)
# Here, we catch all exceptions, and if it seems to match the above
# exception, we attempt to revert to the older perf event handler API.

def checkAPI(t, val, backtrace):
	if t == TypeError and str(val).find('takes exactly'):
		# remove any existing "--api" parameters
		new_argv = []
		arg = 0
		while arg < len(sys.argv):
			if sys.argv[arg].find("--api=") != -1:
				pass
			elif sys.argv[arg] == "--api":
				arg = arg+1
			else:
				new_argv.append(sys.argv[arg])
			arg = arg+1
		new_argv.insert(1,"--api=1")
		debug_print(new_argv)
		os.execvp(new_argv[0],new_argv)
		sys.exit(1)
	sys.__excepthook__(t, val, backtrace)

from Core import *
from Util import *

def ns2ms(nsecs):
	return nsecs * 0.000001

global start_timestamp, curr_timestamp
start_timestamp = 0
curr_timestamp = 0

events = []
n_events = 0

def process_event(event):
	global events,n_events,curr_timestamp
	i = n_events
	while i > 0 and events[i-1].timestamp > event.timestamp:
		i = i-1
	events.insert(i,event)
	if n_events < params.window:
		n_events = n_events+1
	else:
		event = events[0]
		# need to delete from events list now,
		# because event.process() could reenter here
		del events[0]
		if event.timestamp < curr_timestamp:
			sys.stderr.write("Error: OUT OF ORDER events detected.\n  Try increasing the size of the look-ahead window with --window=<n>\n")
		event.process()

class Lock:
	def __init__(self):
		self.timestamp = 0 # mutex initialization time
		self.acquired = 0
		self.last_event = 0 # recording last event time
		self.released = 0
		self.attempted = 0
		self.held = 0 # delta between acquired and release
		self.held_min = sys.maxint
		self.held_max = 0
		self.wait = 0 # delta between entry and acquired
		self.wait_min = sys.maxint
		self.wait_max = 0
		self.pending = 0

	def accumulate(self, lock):
		self.acquired += lock.acquired
		self.released += lock.released
		self.attempted += lock.attempted
		self.held += lock.held
		if lock.held_min < self.held_min:
			self.held_min = lock.held_min
		if lock.held_max > self.held_max:
			self.held_max = lock.held_max
		self.wait += lock.wait
		if lock.wait_min < self.wait_min:
			self.wait_min = lock.wait_min
		if lock.wait_max > self.wait_max:
			self.wait_max = lock.wait_max

	def output_header(self):
		print "%12s %12s %12s %12s %12s %12s %12s %12s %12s" % ("acquired", "waited", "minWait", "maxWait", "avgWait", "held", "minHeld", "maxHeld", "avgHeld")

	def output(self):
		# compute average wait and hold times
		if (self.acquired != 0):
			avgWait = float(self.wait)/float(self.acquired)/1000000.0
			avgHeld = float(self.held)/float(self.acquired)/1000000.0
		else:
			avgWait = 0.0
			avgHeld = 0.0

		wait_min = self.wait_min
		if wait_min == sys.maxint:
			wait_min = 0

		held_min = self.held_min
		if held_min == sys.maxint:
			held_min = 0

		print "%12u %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f %12.3f" \
		      % (self.acquired, \
			 float(self.wait)/1000000.0, float(wait_min)/1000000.0, float(self.wait_max)/float(1000000.0), avgWait, \
			 float(self.held)/1000000.0, float(held_min)/1000000.0, float(self.held_max)/float(1000000.0), avgHeld  )

class CPU:
	def __init__(self):
		self.sys = 0
		self.user = 0
		self.idle = 0
		self.irq = 0
		self.hv = 0
		self.busy_unknown = 0
		self.runtime = 0
		self.sleep = 0
		self.wait = 0
		self.blocked = 0
		self.iowait = 0
		self.unaccounted = 0

	def accumulate(self, cpu):
		self.user += cpu.user
		self.sys += cpu.sys
		self.irq += cpu.irq
		self.hv += cpu.hv
		self.idle += cpu.idle
		self.busy_unknown += cpu.busy_unknown
		self.runtime += cpu.runtime
		self.sleep += cpu.sleep
		self.wait += cpu.wait
		self.blocked += cpu.blocked
		self.iowait += cpu.iowait
		self.unaccounted += cpu.unaccounted

	def output_header(self):
		print "%12s %12s %12s %12s %12s %12s | %12s %12s %12s %12s %12s %12s | %5s%%" % \
			("user", "sys", "irq", "hv", "busy", "idle", "runtime", "sleep", "wait", "blocked", "iowait", "unaccounted", "util"),

	def output(self):
		print "%12.6f %12.6f %12.6f %12.6f %12.6f %12.6f | %12.6f %12.6f %12.6f %12.6f %12.6f %12.6f" % \
			(ns2ms(self.user), ns2ms(self.sys), ns2ms(self.irq), ns2ms(self.hv), ns2ms(self.busy_unknown), ns2ms(self.idle), \
			ns2ms(self.runtime), ns2ms(self.sleep), ns2ms(self.wait), ns2ms(self.blocked), ns2ms(self.blocked), ns2ms(self.unaccounted)),
		running = self.user + self.sys + self.irq + self.hv + self.busy_unknown
		print "| %5.1f%%" % ((float(running * 100) / float(running + self.idle)) if running > 0 else 0),

locks = {}

class LockStats (object):
	def __init__(self):
		self.attempted = 0
		self.acquired = 0
		self.released = 0
		self.wait = 0 # delta between entry and acquired
		self.wait_min = sys.maxint
		self.wait_max = 0
		self.held = 0 # delta between acquired and release
		self.held_min = sys.maxint
		self.held_max = 0

	def output_header(self):
		print "%12s %12s %12s %12s %12s %12s %12s %12s %12s %12s %12s" % ("attempted", "acquired", "released", "wait", "wait avg", "wait min", "wait max", "held", "held avg", "held min", "held max")

	def output(self):
		print "%12u %12u %12u %12.6f %12.6f %12.6f %12.6f %12.6f %12.6f %12.6f %12.6f" % \
			(self.attempted, self.acquired, self.released, \
			ns2ms(self.wait), \
			ns2ms(float(self.wait)/float(self.acquired)) if self.acquired > 0 else 0, \
			ns2ms(self.wait_min) if self.acquired > 0 else 0, \
			ns2ms(self.wait_max),
			ns2ms(self.held), \
			ns2ms(float(self.held)/float(self.released)) if self.released > 0 else 0, \
			ns2ms(self.held_min) if self.released > 0 else 0, \
			ns2ms(self.held_max))

	def accumulate(self, lockstat):
		self.attempted += lockstat.attempted
		self.acquired += lockstat.acquired
		self.released += lockstat.released
		self.wait += lockstat.wait
		if self.wait_min > lockstat.wait_min:
			self.wait_min = lockstat.wait_min
		if self.wait_max < lockstat.wait_max:
			self.wait_max = lockstat.wait_max
		self.held += lockstat.held
		if self.held_min > lockstat.held_min:
			self.held_min = lockstat.held_min
		if self.held_max < lockstat.held_max:
			self.held_max = lockstat.held_max

class Task:
	def __init__(self, timestamp, tid):
		self.timestamp = timestamp
		self.tid = tid
		self.cpu = 'unknown'
		self.cpus = {}
		self.functions = {}

	def output_header(self):
		print "     -- [%8s] %-20s %3s" % ("task", "command", "cpu"),
		for cpu in self.cpus:
			self.cpus[cpu].output_header()
			break # need just one to emit the header
		print "%6s" % ("moves"),

	def output_migrations(self):
		print "%6u" % (self.migrations),

tasks = {}

class Function (object):

	def __init__(self):
		self.lockstats = {}

def addLock(tid, func, lid):
	try:
		lock = locks[lid]
	except:
		lock = Lock()
		locks[lid] = lock
	try:
		lockstats = tasks[tid].functions[func].lockstats[lid]
	except:
		try:
			f = tasks[tid].functions[func]
		except:
			f = Function()
			tasks[tid].functions[func] = f
		lockstats = LockStats()
		tasks[tid].functions[func].lockstats[lid] = lockstats

	return lock

class Event (object):

	def __init__(self):
		self.timestamp = 0
		self.cpu = 0
		self.lid = 0
		self.tid = 0

	def process(self):
		global start_timestamp

		try:
			task = tasks[self.tid]
		except:
			task = Task(start_timestamp, self.tid)
			tasks[self.tid] = task
			debug_print("Adding new task = %u" % self.tid)

			if self.cpu not in task.cpus:
				debug_print("\tAdding new CPU %d" % self.cpu)
				task.cpus[self.cpu] = CPU()
		return task

#class Event_mutex_init ( Event ):
#
#	def __init__(self, timestamp, cpu, lid, tid):
#		self.timestamp = timestamp
#		self.cpu = cpu
#		self.lid = lid
#		self.tid = tid
#		
#	def process(self):
#		global start_timestamp, curr_timestamp
#		curr_timestamp = self.timestamp
#		if (start_timestamp == 0):
#			start_timestamp = curr_timestamp
#
#		debug_print("[%7u] Inside Event_mutex_init::process, lid = 0x%x" % (self.tid, self.lid))
#		task = super(Event_mutex_init, self).process()
#		addLock(self.tid, self.lid)
#		task.locks[self.lid].timestamp = curr_timestamp


class Event_mutex_entry_3 ( Event ):

	def __init__(self, timestamp, cpu, lid, tid, func):
		self.timestamp = timestamp
		self.cpu = cpu
		self.lid = lid
		self.tid = tid
		self.function = func

	def process(self):
		global start_timestamp, curr_timestamp
		curr_timestamp = self.timestamp
		if (start_timestamp == 0):
			start_timestamp = curr_timestamp

		debug_print("[%7u] Inside Event_mutex_entry_3::process, lid = 0x%x" % (self.tid, self.lid))
		task = super(Event_mutex_entry_3, self).process()
		lock = addLock(self.tid, self.function, self.lid)

		lockstats = task.functions[self.function].lockstats[self.lid]

		lockstats.attempted += 1

		lock.last_event = curr_timestamp


class Event_mutex_acquired_7 ( Event ):

	def __init__(self, timestamp, cpu, lid, tid, func):
		self.timestamp = timestamp
		self.cpu = cpu
		self.lid = lid
		self.tid = tid
		self.function = func

	def process(self):
		global start_timestamp, curr_timestamp
		curr_timestamp = self.timestamp
		if (start_timestamp == 0):
			start_timestamp = curr_timestamp

		debug_print("[%7u] Inside Event_mutex_acquired_7::process, lid = 0x%x" % (self.tid, self.lid))
		task = super(Event_mutex_acquired_7, self).process()
		lock = addLock(self.tid, self.function, self.lid)

		lockstats = task.functions[self.function].lockstats[self.lid]

		# wait = delta b/w mutex entry & acquired
		waitTime = (curr_timestamp - lock.last_event)
		lockstats.wait += waitTime

		# update min & max wait time
		if (waitTime < lockstats.wait_min):
			lockstats.wait_min = waitTime

		if (waitTime > lockstats.wait_max):
			lockstats.wait_max = waitTime

		lockstats.acquired += 1

		lock.last_event = curr_timestamp


class Event_mutex_release_7 ( Event ):

	def __init__(self, timestamp, cpu, lid, tid, func):
		self.timestamp = timestamp
		self.cpu = cpu
		self.lid = lid
		self.tid = tid
		self.function = func
		
	def process(self):
		global start_timestamp, curr_timestamp
		curr_timestamp = self.timestamp
		if (start_timestamp == 0):
			start_timestamp = curr_timestamp

		debug_print("[%7u] Inside Event_mutex_release_7::process, lid = 0x%x" % (self.tid, self.lid))
		task = super(Event_mutex_release_7, self).process()
		lock = addLock(self.tid, self.function, self.lid)

		lockstats = task.functions[self.function].lockstats[self.lid]

		# held = delta b/w mutex acquired & released
		heldTime = (curr_timestamp - lock.last_event)
		lockstats.held += heldTime

		# update min & max held time
		if (heldTime < lockstats.held_min):
			lockstats.held_min = heldTime

		if (heldTime > lockstats.held_max):
			lockstats.held_max = heldTime

		lockstats.released += 1


#def sdt_libpthread__mutex_destroy_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
#	common_callchain, __probe_ip, arg1, perf_sample_dict):
#		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
#		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
#		debug_print("Destroying mutex, id = 0x%x" % arg1)

#def sdt_libpthread__mutex_destroy_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
#	sdt_libpthread__mutex_destroy_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def trace_begin():
	debug_print("in trace_begin")

def trace_end():
	debug_print("in trace_end")
	global events
	for event in events:
		event.process()
	mutexTotals()

def mutexTotals():
	lockstats = {}
	# print header
	# print "%20s" % (''),
	for tid in tasks:
		print ""
		print "Task [%9u]" % (tid)
		for func in tasks[tid].functions:
			print "  Function \"%s\"" % (func)
			for lid in tasks[tid].functions[func].lockstats:
				print "            lock",
				tasks[tid].functions[func].lockstats[lid].output_header()
				break
			# print mutex list
			for lid in sorted(tasks[tid].functions[func].lockstats, key = lambda x: (tasks[tid].functions[func].lockstats[x].acquired), reverse=True):
				print "%16x" % (lid),
				tasks[tid].functions[func].lockstats[lid].output()
				if lid not in lockstats:
					lockstats[lid] = LockStats()
				lockstats[lid].accumulate(tasks[tid].functions[func].lockstats[lid])

	print ""
	print "Task [%9s]" % ("ALL")
	print "            lock",
	for lid in locks:
		locks[lid].output_header()
		break
	for lid in locks:
		locks[lid].attempted = lockstats[lid].attempted
		locks[lid].wait = lockstats[lid].wait
		locks[lid].wait_min = lockstats[lid].wait_min
		locks[lid].wait_max = lockstats[lid].wait_max
		locks[lid].acquired = lockstats[lid].acquired
		locks[lid].held = lockstats[lid].held
		locks[lid].held_min = lockstats[lid].held_min
		locks[lid].held_max = lockstats[lid].held_max
		locks[lid].released = lockstats[lid].released
	for lid in sorted(locks, key = lambda x: (locks[x].acquired), reverse=True):
		print "%16x" % (lid),
		locks[lid].output()

def get_caller(callchain):
	try:
		caller = callchain[1]['sym']['name']
		try:
			offset = callchain[1]['ip'] - callchain[1]['sym']['start']
			caller = caller + "+0x%x" % offset
		except:
			pass
	except:
		try:
			caller = callchain[1]['dso']
			try:
				offset = callchain[1]['ip']
				caller = caller + "+0x%x" % offset
			except:
				pass
		except:
			caller = 'unknown'
	return caller

def sdt_libpthread__pthread_create_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__pthread_create_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	sdt_libpthread__pthread_create_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__pthread_create_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, arg2, arg3, arg4, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u, arg2=%u, arg3=%u, arg4=%u" % (__probe_ip, arg1, arg2, arg3, arg4)
		pass

def sdt_libpthread__pthread_create_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, arg2, arg3, arg4):
	sdt_libpthread__pthread_create_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, arg2, arg3, arg4, dummy_dict)

def sdt_libpthread__pthread_join_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__pthread_join_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	sdt_libpthread__pthread_join_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__pthread_join_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		pass

def sdt_libpthread__pthread_join_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__pthread_join_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__pthread_join_ret_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__pthread_join_ret_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	sdt_libpthread__pthread_join_ret_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__mutex_acquired_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_acquired_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_acquired_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_acquired_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_acquired_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_acquired_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_acquired_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_acquired_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_acquired_2_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_acquired_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_acquired_2_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_acquired_2_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_acquired_3_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_acquired_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_acquired_3_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_acquired_3_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_acquired_4_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
	print "sdt_libpthread::mutex_acquired_4 not handled"

def sdt_libpthread__mutex_acquired_4_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	sdt_libpthread__mutex_acquired_4_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__mutex_acquired_5_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	print "sdt_libpthread::mutex_acquired_4 not handled"

def sdt_libpthread__mutex_acquired_5_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_acquired_5_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_acquired_6_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
	print "sdt_libpthread::mutex_acquired_4 not handled"

def sdt_libpthread__mutex_acquired_6_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	sdt_libpthread__mutex_acquired_6_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__mutex_acquired_7_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_acquired_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_acquired_7_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_acquired_7_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

#def sdt_libpthread__mutex_destroy_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
#		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
#		# print "__probe_ip=%u" % (__probe_ip)
#		pass

#def sdt_libpthread__mutex_destroy_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
#	sdt_libpthread__mutex_destroy_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__mutex_entry_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_entry_3 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_entry_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_entry_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_entry_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_entry_3 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_entry_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_entry_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_entry_2_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_entry_3 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_entry_2_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	sdt_libpthread__mutex_entry_2_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__mutex_entry_3_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_entry_3 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
		process_event(event)

def sdt_libpthread__mutex_entry_3_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_entry_3_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

#def sdt_libpthread__mutex_init_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
#		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
#		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
#		event = Event_mutex_init (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
#		process_event(event)

#def sdt_libpthread__mutex_init_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
#	sdt_libpthread__mutex_init_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

#def sdt_libpthread__mutex_init_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
#		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
#		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
#		event = Event_mutex_init (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
#		process_event(event)

#def sdt_libpthread__mutex_init_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
#	sdt_libpthread__mutex_init_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_release_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_release_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_2_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_release_2_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_2_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_3_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
		process_event(event)

def sdt_libpthread__mutex_release_3_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_3_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_4_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_release_4_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_4_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_5_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_release_5_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_5_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_6_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
	event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
	process_event(event)

def sdt_libpthread__mutex_release_6_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_6_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__mutex_release_7_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid, get_caller(common_callchain))
		process_event(event)

def sdt_libpthread__mutex_release_7_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
	sdt_libpthread__mutex_release_7_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, dummy_dict)

def sdt_libpthread__pthread_start_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__pthread_start_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	sdt_libpthread__pthread_start_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def sdt_libpthread__pthread_start_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, arg2, arg3, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u, arg2=%u, arg3=%u" % (__probe_ip, arg1, arg2, arg3)
		pass

def sdt_libpthread__pthread_start_1_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, arg2, arg3):
	sdt_libpthread__pthread_start_1_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1, arg2, arg3, dummy_dict)

def probe_libpthread__pthread_mutex_lock_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % \ (__probe_ip)
		pass

def probe_libpthread__pthread_mutex_lock_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	probe_libpthread__pthread_mutex_lock_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def probe_libpthread__pthread_mutex_unlock_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % \ (__probe_ip)
		pass

def probe_libpthread__pthread_mutex_unlock_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
	probe_libpthread__pthread_mutex_unlock_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

#def probe_libpthread__pthread_mutex_init_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, perf_sample_dict):
#		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
#		# print "__probe_ip=%u" % (__probe_ip)
#		pass

#def probe_libpthread__pthread_mutex_init_old(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip):
#	probe_libpthread__pthread_mutex_init_new(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, dummy_dict)

def trace_unhandled(event_name, context, event_fields_dict):
	#print "trace_unhandled %s" % (event_name)
	#	print ' '.join(['%s=%s'%(k,str(v))for k,v in sorted(event_fields_dict.items())])
	pass

def print_header(event_name, cpu, secs, nsecs, pid, comm):
	#print "%-20s %5u %05u.%09u %8u %-20s " % (event_name, cpu, secs, nsecs, pid, comm),
	pass

if params.api == 1:
	dummy_dict = {}
	dummy_dict['sample'] = {}
	dummy_dict['sample']['pid'] = 'unknown'
#	sdt_libpthread__mutex_destroy_1 = sdt_libpthread__mutex_destroy_1_old
	sdt_libpthread__pthread_create = sdt_libpthread__pthread_create_old
	sdt_libpthread__pthread_create_1 = sdt_libpthread__pthread_create_1_old
	sdt_libpthread__pthread_join = sdt_libpthread__pthread_join_old
	sdt_libpthread__pthread_join_1 = sdt_libpthread__pthread_join_1_old
	sdt_libpthread__pthread_join_ret = sdt_libpthread__pthread_join_ret_old
	sdt_libpthread__mutex_acquired = sdt_libpthread__mutex_acquired_old
	sdt_libpthread__mutex_acquired_1 = sdt_libpthread__mutex_acquired_1_old
	sdt_libpthread__mutex_acquired_2 = sdt_libpthread__mutex_acquired_2_old
	sdt_libpthread__mutex_acquired_3 = sdt_libpthread__mutex_acquired_3_old
	sdt_libpthread__mutex_acquired_4 = sdt_libpthread__mutex_acquired_4_old
	sdt_libpthread__mutex_acquired_5 = sdt_libpthread__mutex_acquired_5_old
	sdt_libpthread__mutex_acquired_6 = sdt_libpthread__mutex_acquired_6_old
	sdt_libpthread__mutex_acquired_7 = sdt_libpthread__mutex_acquired_7_old
#	sdt_libpthread__mutex_destroy = sdt_libpthread__mutex_destroy_old
	sdt_libpthread__mutex_entry = sdt_libpthread__mutex_entry_old
	sdt_libpthread__mutex_entry_1 = sdt_libpthread__mutex_entry_1_old
	sdt_libpthread__mutex_entry_2 = sdt_libpthread__mutex_entry_2_old
	sdt_libpthread__mutex_entry_3 = sdt_libpthread__mutex_entry_3_old
#	sdt_libpthread__mutex_init = sdt_libpthread__mutex_init_old
#	sdt_libpthread__mutex_init_1 = sdt_libpthread__mutex_init_1_old
	sdt_libpthread__mutex_release = sdt_libpthread__mutex_release_old
	sdt_libpthread__mutex_release_1 = sdt_libpthread__mutex_release_1_old
	sdt_libpthread__mutex_release_2 = sdt_libpthread__mutex_release_2_old
	sdt_libpthread__mutex_release_3 = sdt_libpthread__mutex_release_3_old
	sdt_libpthread__mutex_release_4 = sdt_libpthread__mutex_release_4_old
	sdt_libpthread__mutex_release_5 = sdt_libpthread__mutex_release_5_old
	sdt_libpthread__mutex_release_6 = sdt_libpthread__mutex_release_6_old
	sdt_libpthread__mutex_release_7 = sdt_libpthread__mutex_release_7_old
	sdt_libpthread__pthread_start = sdt_libpthread__pthread_start_old
	sdt_libpthread__pthread_start_1 = sdt_libpthread__pthread_start_1_old
	probe_libpthread__pthread_mutex_lock = probe_libpthread__pthread_mutex_lock_old
	probe_libpthread__pthread_mutex_unlock = probe_libpthread__pthread_mutex_unlock_old
#	probe_libpthread__pthread_mutex_init = probe_libpthread__pthread_mutex_init_old
else:
	sys.excepthook = checkAPI
#	sdt_libpthread__mutex_destroy_1 = sdt_libpthread__mutex_destroy_1_new
	sdt_libpthread__pthread_create = sdt_libpthread__pthread_create_new
	sdt_libpthread__pthread_create_1 = sdt_libpthread__pthread_create_1_new
	sdt_libpthread__pthread_join = sdt_libpthread__pthread_join_new
	sdt_libpthread__pthread_join_1 = sdt_libpthread__pthread_join_1_new
	sdt_libpthread__pthread_join_ret = sdt_libpthread__pthread_join_ret_new
	sdt_libpthread__mutex_acquired = sdt_libpthread__mutex_acquired_new
	sdt_libpthread__mutex_acquired_1 = sdt_libpthread__mutex_acquired_1_new
	sdt_libpthread__mutex_acquired_2 = sdt_libpthread__mutex_acquired_2_new
	sdt_libpthread__mutex_acquired_3 = sdt_libpthread__mutex_acquired_3_new
	sdt_libpthread__mutex_acquired_4 = sdt_libpthread__mutex_acquired_4_new
	sdt_libpthread__mutex_acquired_5 = sdt_libpthread__mutex_acquired_5_new
	sdt_libpthread__mutex_acquired_6 = sdt_libpthread__mutex_acquired_6_new
	sdt_libpthread__mutex_acquired_7 = sdt_libpthread__mutex_acquired_7_new
#	sdt_libpthread__mutex_destroy = sdt_libpthread__mutex_destroy_new
	sdt_libpthread__mutex_entry = sdt_libpthread__mutex_entry_new
	sdt_libpthread__mutex_entry_1 = sdt_libpthread__mutex_entry_1_new
	sdt_libpthread__mutex_entry_2 = sdt_libpthread__mutex_entry_2_new
	sdt_libpthread__mutex_entry_3 = sdt_libpthread__mutex_entry_3_new
#	sdt_libpthread__mutex_init = sdt_libpthread__mutex_init_new
#	sdt_libpthread__mutex_init_1 = sdt_libpthread__mutex_init_1_new
	sdt_libpthread__mutex_release = sdt_libpthread__mutex_release_new
	sdt_libpthread__mutex_release_1 = sdt_libpthread__mutex_release_1_new
	sdt_libpthread__mutex_release_2 = sdt_libpthread__mutex_release_2_new
	sdt_libpthread__mutex_release_3 = sdt_libpthread__mutex_release_3_new
	sdt_libpthread__mutex_release_4 = sdt_libpthread__mutex_release_4_new
	sdt_libpthread__mutex_release_5 = sdt_libpthread__mutex_release_5_new
	sdt_libpthread__mutex_release_6 = sdt_libpthread__mutex_release_6_new
	sdt_libpthread__mutex_release_7 = sdt_libpthread__mutex_release_7_new
	sdt_libpthread__pthread_start = sdt_libpthread__pthread_start_new
	sdt_libpthread__pthread_start_1 = sdt_libpthread__pthread_start_1_new
	probe_libpthread__pthread_mutex_lock = probe_libpthread__pthread_mutex_lock_new
	probe_libpthread__pthread_mutex_unlock = probe_libpthread__pthread_mutex_unlock_new
#	probe_libpthread__pthread_mutex_init = probe_libpthread__pthread_mutex_init_new
