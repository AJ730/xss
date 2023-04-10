#!/usr/bin/env python3

from __future__ import print_function

import sqlite3
import time

import requests

from core.colors import end, red, white, bad, info

import os

from xss.reader.LogStorer import LogStorer

# Just a fancy ass banner
print('''%s
\tXSStrike %sv4.0.0
%s''' % (red, white, end))

try:
	import concurrent.futures
	from urllib.parse import urlparse

	try:
		import fuzzywuzzy
	except ImportError:
		import os

		print('%s fuzzywuzzy isn\'t installed, installing now.' % info)
		ret_code = os.system('pip3 install fuzzywuzzy')
		if (ret_code != 0):
			print('%s fuzzywuzzy installation failed.' % bad)
			quit()
		print('%s fuzzywuzzy has been installed, restart XSStrike.' % info)
		quit()
except ImportError:  # throws error in python2
	print('%s XSStrike isn\'t compatible with python2.\n Use python > 3.4 to run XSStrike.' % bad)
	quit()

# Let's import whatever we need from standard lib
import sys
import json
import argparse

# ... and configurations core lib
import core.config
import core.log

# Processing command line arguments, where dest var names will be mapped to local vars with the same name
parser = argparse.ArgumentParser()
parser.add_argument('-u', '--url', help='url', dest='target')
parser.add_argument('-ul', '--url_list', help='path to a file of URLs', dest='targets')
parser.add_argument('--data', help='post data', dest='paramData')
parser.add_argument('-e', '--encode', help='encode payloads', dest='encode')
parser.add_argument('--fuzzer', help='fuzzer',
                    dest='fuzz', action='store_true')
parser.add_argument('--update', help='update',
                    dest='update', action='store_true')
parser.add_argument('--timeout', help='timeout',
                    dest='timeout', type=int, default=core.config.timeout)
parser.add_argument('--proxy', help='use prox(y|ies)',
                    dest='proxy', action='store_true')
parser.add_argument('--crawl', help='crawl',
                    dest='recursive', action='store_true')
parser.add_argument('--json', help='treat post data as json',
                    dest='jsonData', action='store_true')
parser.add_argument('--path', help='inject payloads in the path',
                    dest='path', action='store_true')
parser.add_argument(
	'--seeds', help='load crawling seeds from a file', dest='args_seeds')
parser.add_argument(
	'-f', '--file', help='load payloads from a file', dest='args_file')
parser.add_argument('-l', '--level', help='level of crawling',
                    dest='level', type=int, default=2)
parser.add_argument('--headers', help='add headers',
                    dest='add_headers', nargs='?', const=True)
parser.add_argument('-t', '--threads', help='number of threads',
                    dest='threadCount', type=int, default=core.config.threadCount)
parser.add_argument('-d', '--delay', help='delay between requests',
                    dest='delay', type=int, default=core.config.delay)
parser.add_argument('--skip', help='don\'t ask to continue',
                    dest='skip', action='store_true')
parser.add_argument('--enable-dom-checking', help='skip dom checking',
                    dest='enableDom', action='store_true')
parser.add_argument('--blind', help='inject blind XSS payload while crawling (set the payload/s in core/config.py)',
                    dest='blindXSS', action='store_true')
parser.add_argument('--console-log-level', help='Console logging level',
                    dest='console_log_level', default=core.log.console_log_level,
                    choices=core.log.log_config.keys())
parser.add_argument('--file-log-level', help='File logging level', dest='file_log_level',
                    choices=core.log.log_config.keys(), default=None)
parser.add_argument('--log-file', help='Name of the file to log', dest='log_file',
                    default=core.log.log_file)
parser.add_argument('--js', '--javascript', help='render javascript', dest='js', action='store_true')
parser.add_argument('--save-payloads', dest="payloads_file", help='Save generated payloads to a file')
parser.add_argument('--clear-db', dest="clear_db", help="Clear generated db", action='store_true')
parser.add_argument('--parse-timeout', dest='parse_timeout', help='timeout when parsing', type=int, default=300)
parser.add_argument('--headless', dest='headless', help='run validation headless', default=True, action='store_true')
args = parser.parse_args()

# Pull all parameter values of dict from argparse namespace into local variables of name == key
# The following works, but the static checkers are too static ;-) locals().update(vars(args))
target = args.target
targets = args.targets
js = args.js
path = args.path
jsonData = args.jsonData
paramData = args.paramData
encode = args.encode
fuzz = args.fuzz
update = args.update
timeout = args.timeout
proxy = args.proxy
recursive = args.recursive
args_file = args.args_file
args_seeds = args.args_seeds
level = args.level
add_headers = args.add_headers
threadCount = args.threadCount
delay = args.delay
skip = args.skip
enableDom = args.enableDom
blindXSS = args.blindXSS
payloads_file = args.payloads_file
core.log.console_log_level = args.console_log_level
core.log.file_log_level = args.file_log_level
core.log.log_file = args.log_file
clear_db = args.clear_db
logger = core.log.setup_logger()
parse_timeout = args.parse_timeout
headless = args.headless

core.config.globalVariables = vars(args)

# Import everything else required from core lib
from core.config import blindPayload
from core.encoders import base64
from core.photon import photon
from core.prompt import prompt
from core.updater import updater
from core.utils import extractHeaders, reader, converter

from modes.bruteforcer import bruteforcer
from modes.crawl import crawl
from modes.scan import scan
from modes.singleFuzz import singleFuzz

if type(args.add_headers) == bool:
	headers = extractHeaders(prompt())
elif type(args.add_headers) == str:
	headers = extractHeaders(args.add_headers)
else:
	from core.config import headers

core.config.globalVariables['headers'] = headers
core.config.globalVariables['checkedScripts'] = set()
core.config.globalVariables['checkedForms'] = {}
core.config.globalVariables['definitions'] = json.loads('\n'.join(reader(sys.path[0] + '/db/definitions.json')))
ls = LogStorer()
if clear_db:
	os.remove('./vuln.db')

f = open("logfile.text", "a")
if path:
	paramData = converter(target, target)
elif jsonData:
	headers['Content-type'] = 'application/json'
	paramData = converter(paramData)

target_list = []
if targets:
	target_list = list(filter(None, reader(targets)))
elif target:
	target_list.append(target)

if args_file:
	if args_file == 'default':
		payloadList = core.config.payloads
	else:
		payloadList = list(filter(None, reader(args_file)))

seedList = []
if args_seeds:
	seedList = list(filter(None, reader(args_seeds)))

encoding = base64 if encode and encode == 'base64' else False

if not proxy:
	core.config.proxies = {}

if update:  # if the user has supplied --update argument
	updater()
	quit()  # quitting because files have been changed

if not target_list and not args_seeds:  # if the user hasn't supplied a url
	logger.no_format('\n' + parser.format_help().lower())
	quit()

if fuzz:
	singleFuzz(target, paramData, encoding, headers, delay, timeout)
elif not recursive and not args_seeds:

	results = []
	for i, target in enumerate(target_list):
		logger.red_line()
		logger.info(f'Target: {target}  ({i + 1}/{len(target_list)})')
		if args_file:
			bruteforcer(target, paramData, payloadList, encoding, headers, delay, timeout)
		else:
			result = scan(target, paramData, encoding, headers, delay, timeout, enableDom, skip, payloads_file,
			              headless=headless)
			results.append(result) if result else 'The target is not vulnerable!'

	if results:
		logger.yellow_summary_line()
		logger.run('SUMMARY')
		logger.info(f'Total        {len(target_list)} target{"s"[:len(target_list) ^ 1]}')
		logger.info(f'Vulnerable   {len(results)} target{"s"[:len(results) ^ 1]}')
		for i, result in enumerate(results):
			logger.good(f'Pwned        {result[0]} ({result[1]})')

else:

	executiontime = time.time()
	if target:
		seedList.append(target)

	count = 2020
	for target in seedList:
		logger.run('Crawling the target:'+target)
		scheme = urlparse(target).scheme
		logger.debug('Target scheme: {}'.format(scheme))
		host = urlparse(target).netloc
		main_url = scheme + '://' + host
		crawlingResult = photon(target, headers, level,
		                        threadCount, delay, timeout, enableDom, parse_timeout)

		count += crawlingResult[2]
		forms = crawlingResult[0]
		domURLs = list(crawlingResult[1])
		difference = abs(len(domURLs) - len(forms))
		if len(domURLs) > len(forms):
			for i in range(difference):
				forms.append(0)
		elif len(forms) > len(domURLs):
			for i in range(difference):
				domURLs.append(0)
		threadpool = concurrent.futures.ThreadPoolExecutor(max_workers=threadCount)

		futures = (threadpool.submit(crawl, scheme, host, main_url, form,
		                             blindXSS, blindPayload, headers, delay, timeout, encoding, headless) for
		           form, domURL in zip(forms, domURLs))

		for i, future in enumerate(concurrent.futures.as_completed(futures)):
			if future.result() == 'TimedOut':
				logger.error('All threads Stopped for current site!')
				threadpool.shutdown(wait=False)
				for f in futures:
					if not f.done():
						f.cancel()
				break

			if i + 1 == len(forms) or (i + 1) % threadCount == 0:
				logger.info('Progress: %i/%i\r' % (i + 1, len(forms)))
		logger.no_format('')


		if not ls.getColumn(target):
			try:
				status = requests.get(target, timeout=5)
				print("Not Crawled", flush=True)
				ls.addVector('Not Crawled', target, 'none', 'none', 'none', False)
			except:
				ls.addVector('Banned', target, 'none', 'none', 'none', False)
				print("Banned", flush=True)




		logger.info("printing log file")
		f = open("logfile.text", "a")
		f.write(f"Target: {target}, time: {13522.887819766998  +time.time() - executiontime} crawl-subpages: {count}\n")
		f.flush()

		logger.red_line()


	executiontime = time.time() - executiontime

	logger.info("printing log file")
	f = open("logfile.text", "a")
	f.write(f"time: {time.time() + 13522.887819766998- executiontime} crawl-subpages: {count}\n")
	f.flush()
	f.close()