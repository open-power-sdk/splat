#!/bin/sh
mount -o remount,mode=755 /sys/kernel/debug
sysctl kernel.perf_event_paranoid=-1
