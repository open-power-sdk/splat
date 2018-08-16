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

parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
	description='''
Report per-task, per-process, and system-wide lock statistics

Process a perf format trace file containing some or all of the following event sets:
- sdt_libpthread:mutex_acquired
- sdt_libpthread:mutex_entry
- sdt_libpthread:mutex_init
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
$ perf probe --add sdt_libpthread:mutex_init
$ perf probe --add sdt_libpthread:mutex_entry
$ perf probe --add sdt_libpthread:mutex_acquired
$ perf probe --add sdt_libpthread:mutex_release

Note: there may be multiple tracepoints established at each "perf probe" step above.  All tracepoints should be recorded in subsequent steps.

Record using perf (to perf.data file):
$ perf record -e '{sdt_libpthread:mutex_init:sdt_libpthread:mutex_acquired,sdt_libpthread_mutex_entry,sdt_libpthread_mutex_release ...}' command

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
	command = ['perf', 'record', '--quiet', '--all-cpus',
		'--event', eventlist ] + params.file_or_command
	if params.debug:
		print command
	subprocess.call(command)
	params.file_or_command = []

try:
	from perf_trace_context import *
except:
	print "Relaunching under \"perf\" command..."
	if len(params.file_or_command) == 0:
		params.file_or_command = [ "perf.data" ]
	sys.argv = ['perf', 'script', '-i' ] + params.file_or_command + [ '-s', sys.argv[0] ]
	sys.argv.append('--')
	sys.argv += ['--window', str(params.window)]
	if params.debug:
		sys.argv.append('--debug')
	if params.debug:
		print sys.argv
	os.execvp("perf", sys.argv)
	sys.exit(1)

from Core import *
from Core import *
from Util import *

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

class Task:
	def __init__(self, timestamp, tid):
		self.timestamp = timestamp
		self.tid = tid
		self.cpu = 'unknown'
		self.cpus = {}
		self.locks = {}

	def output_header(self):
		print "     -- [%8s] %-20s %3s" % ("task", "command", "cpu"),
		for cpu in self.cpus:
			self.cpus[cpu].output_header()
			break # need just one to emit the header
		print "%6s" % ("moves"),

	def output_migrations(self):
		print "%6u" % (self.migrations),

tasks = {}

def addLock(tid, lid):
	try:
		lock = tasks[tid].locks[lid]
	except:
		lock = Lock()
		tasks[tid].locks[lid] = lock
		print  "\tAdding new lock = 0x%x" %lid

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
			print  "Adding new task = %u" %self.tid

			if self.cpu not in task.cpus:
				print"\tAdding new CPU %d" %self.cpu
				task.cpus[self.cpu] = CPU()
		return task

class Event_mutex_init ( Event ):

	def __init__(self, timestamp, cpu, lid, tid):
		self.timestamp = timestamp
		self.cpu = cpu
		self.lid = lid
		self.tid = tid
		
	def process(self):
		global start_timestamp, curr_timestamp
		curr_timestamp = self.timestamp
		if (start_timestamp == 0):
			start_timestamp = curr_timestamp

		print "[%7u] Inside Event_mutex_init::process, lid = 0x%x" % (self.tid, self.lid)
		task = super(Event_mutex_init, self).process()
		addLock(self.tid, self.lid)
		task.locks[self.lid].timestamp = curr_timestamp


class Event_mutex_entry_3 ( Event ):

	def __init__(self, timestamp, cpu, lid, tid):
		self.timestamp = timestamp
		self.cpu = cpu
		self.lid = lid
		self.tid = tid

	def process(self):
		global start_timestamp, curr_timestamp
		curr_timestamp = self.timestamp
		if (start_timestamp == 0):
			start_timestamp = curr_timestamp

		print "[%7u] Inside Event_mutex_entry_3::process, lid = 0x%x" % (self.tid, self.lid)
		task = super(Event_mutex_entry_3, self).process()
		addLock(self.tid, self.lid)

		task.locks[self.lid].last_event = curr_timestamp


class Event_mutex_acquired_7 ( Event ):

	def __init__(self, timestamp, cpu, lid, tid):
		self.timestamp = timestamp
		self.cpu = cpu
		self.lid = lid
		self.tid = tid

	def process(self):
		global start_timestamp, curr_timestamp
		curr_timestamp = self.timestamp
		if (start_timestamp == 0):
			start_timestamp = curr_timestamp

		print "[%7u] Inside Event_mutex_acquired_7::process, lid = 0x%x" % (self.tid, self.lid)
		task = super(Event_mutex_acquired_7, self).process()
		addLock(self.tid, self.lid)

		# wait = delta b/w mutex entry & acquired
		waitTime = (curr_timestamp - task.locks[self.lid].last_event)
		task.locks[self.lid].wait += waitTime

		# update min & max wait time
		if (waitTime < task.locks[self.lid].wait_min):
			task.locks[self.lid].wait_min = waitTime

		if (waitTime > task.locks[self.lid].wait_max):
			task.locks[self.lid].wait_max = waitTime

		task.locks[self.lid].last_event = curr_timestamp
		task.locks[self.lid].acquired += 1


class Event_mutex_release_7 ( Event ):

	def __init__(self, timestamp, cpu, lid, tid):
		self.timestamp = timestamp
		self.cpu = cpu
		self.lid = lid
		self.tid = tid
		
	def process(self):
		global start_timestamp, curr_timestamp
		curr_timestamp = self.timestamp
		if (start_timestamp == 0):
			start_timestamp = curr_timestamp

		print "[%7u] Inside Event_mutex_release_7::process, lid = 0x%x" % (self.tid, self.lid)
		task = super(Event_mutex_release_7, self).process()
		addLock(self.tid, self.lid)

		task.locks[self.lid].released = curr_timestamp

		# held = delta b/w mutex acquired & released
		heldTime = (curr_timestamp - task.locks[self.lid].last_event)
		task.locks[self.lid].held += heldTime

		# update min & max held time
		if (heldTime < task.locks[self.lid].held_min):
			task.locks[self.lid].held_min = heldTime

		if (heldTime > task.locks[self.lid].held_max):
			task.locks[self.lid].held_max = heldTime


def sdt_libpthread__mutex_destroy_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		print "Destroying mutex, id = 0x%x" %arg1


def trace_begin():
	print "in trace_begin"

def trace_end():
	print "in trace_end"
	global events
	for event in events:
		event.process()

	mutexTotals()

def mutexTotals():
	locks = {}
	# print header
	# print "%20s" % (''),
	for tid in tasks:
		print ""
		print "Task [%9u]" % (tid)
		for lid in tasks[tid].locks:
			print "            lock",
			tasks[tid].locks[lid].output_header()
			break
		# print mutex list
		for lid in tasks[tid].locks:
			print "%16x" % (lid),
			tasks[tid].locks[lid].output()
			if lid not in locks:
				locks[lid] = Lock()
			locks[lid].accumulate(tasks[tid].locks[lid])

	print ""
	print "Task [%9s]" % ("ALL")
	print "            lock",
	for lid in locks:
		locks[lid].output_header()
		break
	for lid in locks:
		print "%16x" % (lid),
		locks[lid].output()

def sdt_libpthread__pthread_create(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__pthread_create_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1, arg2, arg3, arg4):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u, arg2=%u, arg3=%u, arg4=%u" % (__probe_ip, arg1, arg2, arg3, arg4)
		pass

def sdt_libpthread__pthread_join(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__pthread_join_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		pass

def sdt_libpthread__pthread_join_ret(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_acquired(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_acquired_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		pass

def sdt_libpthread__mutex_acquired_2(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_acquired_3(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_acquired_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__mutex_acquired_4(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % \ (__probe_ip)
		pass

def sdt_libpthread__mutex_acquired_5(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		pass

def sdt_libpthread__mutex_acquired_6(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_acquired_7(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_acquired_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__mutex_destroy(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_entry(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_entry_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_entry_3 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__mutex_entry_2(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_entry_3(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm, common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_entry_3 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__mutex_init(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % \ (__probe_ip)
		event = Event_mutex_init (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__mutex_init_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_init (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__mutex_release(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_release_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		pass

def sdt_libpthread__mutex_release_2(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % \ (__probe_ip)
		pass

def sdt_libpthread__mutex_release_3(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__mutex_release_4(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_release_5(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		pass

def sdt_libpthread__mutex_release_6(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__mutex_release_7(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u" % (__probe_ip, arg1)
		event = Event_mutex_release_7 (nsecs(common_secs,common_nsecs), common_cpu, arg1, common_pid)
		process_event(event)

def sdt_libpthread__pthread_start(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def sdt_libpthread__pthread_start_1(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip, arg1, arg2, arg3):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u, arg1=%u, arg2=%u, arg3=%u" % (__probe_ip, arg1, arg2, arg3)
		pass

def probe_libpthread__pthread_mutex_lock(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % \ (__probe_ip)
		pass

def probe_libpthread__pthread_mutex_unlock(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % \ (__probe_ip)
		pass

def probe_libpthread__pthread_mutex_init(event_name, context, common_cpu, common_secs, common_nsecs, common_pid, common_comm,
	common_callchain, __probe_ip):
		# print_header(event_name, common_cpu, common_secs, common_nsecs, common_pid, common_comm)
		# print "__probe_ip=%u" % (__probe_ip)
		pass

def trace_unhandled(event_name, context, event_fields_dict):
	#print "trace_unhandled %s" % (event_name)
	#	print ' '.join(['%s=%s'%(k,str(v))for k,v in sorted(event_fields_dict.items())])
	pass

def print_header(event_name, cpu, secs, nsecs, pid, comm):
	#print "%-20s %5u %05u.%09u %8u %-20s " % (event_name, cpu, secs, nsecs, pid, comm),
	pass
