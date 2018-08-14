# Licensed under the terms of the GNU GPL License version 2

import os
import sys
import argparse

sys.path.append(os.environ['PERF_EXEC_PATH'] + \
	'/scripts/python/Perf-Trace-Util/lib/Perf/Trace')

from perf_trace_context import *
from Core import *
from Util import *

global start_timestamp, curr_timestamp
start_timestamp = 0
curr_timestamp = 0

def process_event(event):
		event.process()

class Lock:
	def __init__(self):
		self.timestamp = 0 # mutex initialization time
		self.acquired = 0
		self.last_event = 0 # recording last event time
		self.released = 0
		self.attempted = 0
		self.held = 0 # delta between acquired and release
		# self.held_min = sys.maxint		// Check
		self.held_min = 0
		self.held_max = 0
		self.wait = 0 # delta between entry and acquired
		# self.wait_min = sys.maxint		// Check
		self.wait_min = 0
		self.wait_max = 0
		self.pending = 0

	def output_header(self):
		print "%12s %12s %12s %12s %12s %12s %12s %12s %12s" % ("acquired", "waited", "minWait", "maxWait", "avgWait", "held", "minHeld", "maxHeld", "avgHeld")

	def output(self):		# // Check this routine
		# compute average wait and hold times
		if (self.acquired != 0):
			avgWait = (self.wait/self.acquired)/1000
			avgHeld = (self.held/self.acquired)/1000
		else:
			avgWait = 0
			avgHeld = 0

		# print "%9u %9.2f %9.2f %9.2f %9.2f %9.2f %9.2f %9.2f %9.2f" \		# Check: Having trouble with %f formatting
		print "%12s %12s %12s %12s %12s %12s %12s %12s %12s"  \
		      % (self.acquired, \
			 self.wait/1000, self.wait_min/1000, self.wait_max/1000, avgWait, \
			 self.held/1000, self.held_min/1000, self.held_max/1000, avgHeld  )

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

		# Check: Logic for min/max wait times

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

		# Check: Logic for min/max held times

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
	mutexTotals()

def mutexTotals():
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
