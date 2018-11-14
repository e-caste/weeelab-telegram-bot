#!/usr/bin/env python
# coding:utf-8

"""
WEEELAB_BOT - Telegram bot.
Author: WEEE Open Team
	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.
	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.
	You should have received a copy of the GNU General Public License
	along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

# Modules
from variables import *  # internal library with the environment variables
import requests  # send HTTP requests to Telegram server
# noinspection PyUnresolvedReferences
import owncloud
import datetime
from datetime import timedelta
import json
import re  # "Parse" logs
import traceback  # Print stack traces in logs


class BotHandler:
	"""
	class with method used by the bot, for more details see https://core.telegram.org/bots/api
	"""

	def __init__(self, token):
		"""
		init function to set bot token and reference url
		"""
		self.token = token
		self.api_url = "https://api.telegram.org/bot{}/".format(token)
		self.offset = None

		# These are returned when a user sends an unknown command.
		self.unknown_command_messages_last = -1
		self.unknown_command_messages = [
			"Sorry, I didn't understand that",
			"I don't know that command, but do you know /history? It's pretty cool",
			"What? I don't understand :(",
			"Unknown command"
		]

	def get_updates(self, timeout=30):
		"""
		method to receive incoming updates using long polling
		[Telegram API -> getUpdates ]
		"""
		params = {'offset': self.offset, 'timeout': timeout}
		try:
			result = requests.get(self.api_url + 'getUpdates', params).json()['result']  # return an array of json
			if len(result) > 0:
				self.offset = result[-1]['update_id'] + 1
			return result
		except:
			return None

	def send_message(self, chat_id, text, parse_mode='HTML', disable_web_page_preview=True, reply_markup=None):
		"""
		method to send text messages [ Telegram API -> sendMessage ]
		On success, the sent Message is returned.
		"""
		params = {
			'chat_id': chat_id,
			'text': text,
			'parse_mode': parse_mode,
			'disable_web_page_preview': disable_web_page_preview,
			'reply_markup': reply_markup
		}
		return requests.post(self.api_url + 'sendMessage', params)

	def get_last_update(self):
		"""
		method to get last message if there is.
		in case of error return an error code used in the main function
		"""
		get_result = self.get_updates()  # recall the function to get updates
		if not get_result:
			return -1
		elif len(get_result) > 0:  # check if there are new messages
			return get_result[-1]  # return the last message in json format
		else:
			return -1

	def leave_chat(self, chat_id):
		"""
		method to send text messages [ Telegram API -> leaveChat ]
		On success, the leave Chat returns True.
		"""
		params = {
			'chat_id': chat_id,
		}
		return requests.post(self.api_url + 'leaveChat', params)

	@property
	def unknown_command_message(self):
		self.unknown_command_messages_last += 1
		self.unknown_command_messages_last %= len(self.unknown_command_messages)
		return self.unknown_command_messages[self.unknown_command_messages_last]


class TaralloSession:
	def __init__(self):
		self.cookie = None
		self.last_status = None

	def login(self, username, password):
		"""
		Try to log in, if necessary.

		:rtype: bool
		:return: Logged in or not?
		"""

		if self.cookie is not None:
			whoami = requests.get(TARALLO + '/v1/session', cookies=self.cookie)
			self.last_status = whoami.status_code

			if whoami.status_code == 200:
				return True

			# Attempting to log in would be pointless, there's some other error
			if whoami.status_code != 403:
				return False

		body = dict()
		body['username'] = username
		body['password'] = password
		headers = {"Content-Type": "application/json"}
		res = requests.post(TARALLO + '/v1/session', data=json.dumps(body), headers=headers)
		self.last_status = res.status_code

		if res.status_code == 204:
			self.cookie = res.cookies
			return True
		else:
			return False

	def get_history(self, item, limit):
		history = requests.get(TARALLO + '/v1/items/{}/history?length={}'.format(item, str(limit)), cookies=self.cookie)
		self.last_status = history.status_code

		if history.status_code == 200:
			return history.json()['data']
		elif history.status_code == 404:
			return None
		else:
			raise RuntimeError("Unexpected return code")


class WeeelabLogs:
	def __init__(self, oc: owncloud):
		self.log = []
		self.log_last_update = None
		self.users = None
		self.error = None
		self.oc = oc

		# Logs from past months (no lines from current month)
		self.old_log = []
		# Logs start from april 2017, these variables represent which log file has been fetched last, so it will start
		# from the first one that actually exists (april 2017)
		self.old_logs_month = 3
		self.old_logs_year = 2017

	def get_log(self):
		self.log = []
		log_file = self.oc.get_file_contents(LOG_PATH).decode('utf-8')
		log_lines = log_file.splitlines()

		for line in log_lines:
			self.log.append(WeeelabLine(line))

		# store the data of the last update of the log file,
		# the data is in UTC so we add 2 for eu/it local time
		# TODO: this is sometimes +1 because ora legale, use a timezone library and compute correct time
		self.log_last_update = self.oc.file_info(LOG_PATH).get_last_modified() + timedelta(hours=2)

		return self

	def get_old_logs(self):
		today = datetime.date.today()
		prev_month = today.month - 1
		if prev_month == 12:
			prev_year = today.year - 1
		else:
			prev_year = today.year

		if self.old_logs_year < prev_year or self.old_logs_month < prev_month:
			self.update_old_logs(prev_month, prev_year)

	def update_old_logs(self, max_month, max_year):
		"""
		Download old logs up to a date. Don't call directly, use get_old_logs.

		:param max_month:
		:param max_year:
		:return:
		"""
		year = self.old_logs_year
		month = self.old_logs_month

		while True:
			month += 1
			if month >= 13:
				month = 1
				year += 1
			if year >= max_year and month > max_month:
				break

			filename = LOG_BASE + "log" + str(year) + str(month).zfill(2) + ".txt"
			print(f"Downloading {filename}")
			try:
				log_file = self.oc.get_file_contents(filename).decode('utf-8')
				log_lines = log_file.splitlines()

				for line in log_lines:
					self.old_log.append(WeeelabLine(line))
			except owncloud.owncloud.HTTPResponseError:
				print(f"Failed downloading {filename}, will try again next time")
				# Roll back to the previous month, since that's the last we have
				month -= 1
				if month == 0:
					month = 12
					year -= 1
				break

		self.old_logs_month = month
		self.old_logs_year = year

	def get_users(self):
		try:
			self.users = json.loads(self.oc.get_file_contents(USER_PATH).decode('utf-8'))["users"]
		except json.decoder.JSONDecodeError as e:
			self.error = str(e)
			if self.users is None:
				raise RuntimeError("Error getting/parsing users file and no previous versione available")
			return self
		self.error = None

		return self

	def count_time_user(self, username):
		"""
		Count time spent in lab for this user

		:param username:
		:return: Minutes this month and in total
		"""
		minutes_thismonth = 0

		# noinspection PyUnusedLocal
		line: WeeelabLine
		for line in self.log:
			if line.username == username:
				minutes_thismonth += line.duration_minutes()

		minutes_total = minutes_thismonth

		# noinspection PyUnusedLocal
		line: WeeelabLine
		for line in self.old_log:
			if line.username == username:
				minutes_total += line.duration_minutes()

		return minutes_thismonth, minutes_total

	def count_time_month(self):
		"""
		Count time spent in lab for all users this month

		:return: Dict with username as key, minutes as value
		"""
		minutes = {}

		# noinspection PyUnusedLocal
		line: WeeelabLine
		for line in self.log:
			if line.username not in minutes:
				minutes[line.username] = 0
			minutes[line.username] += line.duration_minutes()

		return minutes

	def count_time_all(self):
		"""
		Count time spent in lab for all users, all times

		:return: Dict with username as key, minutes as value
		"""
		# Start from that
		minutes = self.count_time_month()

		# noinspection PyUnusedLocal
		line: WeeelabLine
		for line in self.old_log:
			if line.username not in minutes:
				minutes[line.username] = 0
			minutes[line.username] += line.duration_minutes()

		return minutes

	def get_entries_inlab(self):
		# PyCharm, you suggested that, why are you making me remove it?
		# noinspection PyUnusedLocal
		line: WeeelabLine
		inlab = []

		for line in self.log:
			if line.inlab:
				inlab.append(line.username)

		return inlab

	def get_entry_from_tid(self, user_id: str):
		"""
		Search user data from a Telegram ID

		:param user_id: Telegram user ID
		:return: The entry from users.json or None
		"""
		for user in self.users:
			if user["telegramID"] == str(user_id):
				return user
		return None

	def get_entry_from_username(self, username: str):
		"""
		Search user data from a username

		:param username: Normalized, unique, official username
		:return: The entry from users.json or None
		"""
		for user in self.users:
			if username == user["username"]:
				return user
		return None

	def store_new_user(self, tid, name: str, surname: str, username: str):
		new_users_file = self.oc.get_file_contents(USER_BOT_PATH)
		new_users = new_users_file.decode('utf-8')

		if str(tid) in new_users:
			return
		else:
			# Store a new user name and id in a file on owncloud server,
			# encoding in utf.8
			try:
				if surname != '':
					surname = f" {surname}"
				if username == '':
					username = " (no username)"
				else:
					username = f" (@{username})"
				new_users = new_users + "{}{}{}: {}\n".format(name, surname, username, tid)
				self.oc.put_file_contents(USER_BOT_PATH, new_users.encode('utf-8'))
			except (AttributeError, UnicodeEncodeError):
				print("ERROR writing user.txt")
				pass

	def try_get_name_and_surname(self, username: str):
		"""
		Get full name and surname from username, or return provided username if not found

		:param username: Normalized, unique, official username
		:return: Name and surname, or name only, or username only, or something usable
		"""
		entry = self.get_entry_from_username(username)
		if entry:
			return self.get_name_and_surname(entry)
		else:
			return username

	def try_get_id(self, username: str):

		entry = self.get_entry_from_username(username)
		if entry:
			return entry["telegramID"]
		else:
			return None

	@staticmethod
	def get_name_and_surname(user_entry: dict):
		"""
		Get user name and surname in correct format, given an entry.
		This doesn't crash and burn if some data is missing.

		:param user_entry: user entry (e.g. from search_user)
		:return: Name and surname, or name only, or username only, or something usable
		"""
		if "name" in user_entry and "surname" in user_entry:
			return "{} {}".format(user_entry["name"], user_entry["surname"])

		if "name" in user_entry:
			return user_entry["name"]

		return user_entry["username"]

	@staticmethod
	def mm_to_hh_mm(minutes):
		hh = minutes // 60
		hh = str(hh).zfill(2)

		mm = minutes % 60
		mm = str(mm).zfill(2)

		return hh, mm


class WeeelabLine:
	regex = re.compile('\[([^\]]+)\]\s*\[([^\]]+)\]\s*\[([^\]]+)\]\s*<([^>]+)>\s*[:{2}]*\s*(.*)')

	def __init__(self, line: str):
		res = self.regex.match(line)
		self.time_in = res.group(1)
		self.time_out = res.group(2)
		self.duration = res.group(3)
		self.username = res.group(4)
		self.text = res.group(5)

		if self.duration == "INLAB":
			self.time_out = None
			self.inlab = True
		else:
			self.inlab = False

	def day(self):
		return self.time_in.split(" ")[0]

	def duration_minutes(self):
		# TODO: calculate partials (time right now - time in)
		if self.inlab:
			return 0

		parts = self.duration.split(':')
		return int(parts[0]) * 60 + int(parts[1])


def escape_all(string):
	return string.replace('_', '\\_').replace('*', '\\*').replace('`', '\\``').replace('[', '\\[')


class CommandHandler:
	"""
	Aggregates all the possible commands within one class.
	"""

	def __init__(self, user, bot, tarallo, logs, last_update):
		self.user = user
		self.bot = bot
		self.tarallo = tarallo
		self.logs = logs
		self.last_chat_id = last_update['message']['chat']['id']
		self.last_user_id = last_update['message']['from']['id']
		self.last_update = last_update

	def _send_message(self, message):
		self.bot.send_message(self.last_chat_id, message)

	def start(self):
		"""
		Called with /start
		"""

		self._send_message('\
*WEEE Open Telegram bot*.\nThe goal of this bot is to obtain information \
about who is currently in the lab, who has done what, compute some stats and, \
in general, simplify the life of our members and to avoid waste of paper \
as well. \nAll data is read from a weeelab log file, which is fetched from \
an OwnCloud shared folder.\nFor a list of the commands allowed send /help.', )

	def inlab(self):
		"""
		Called with /inlab
		"""

		inlab = self.logs.get_log().get_entries_inlab()

		if len(inlab) == 0:
			msg = 'Nobody is in lab right now.'
		elif len(inlab) == 1:
			msg = 'There is one student in lab right now:\n'
		else:
			msg = 'There are {} students in lab right now:\n'.format(str(len(inlab)))

		for username in inlab:
			user_id = self.logs.try_get_id(username)
			if user_id is None:
				msg += '\n- {})'.format(self.logs.try_get_name_and_surname(username))
			else:
				msg += '\n- <a href="tg://user?id={}">{}</a>'.format(user_id, self.logs.try_get_name_and_surname(username))

		self._send_message(msg)

	def log(self, cmd_days_to_filter=None):
		"""
		Called with /log
		"""

		# TODO: this also downloads the file for each request. Maybe don't do it every time.
		self.logs.get_log()

		if cmd_days_to_filter is not None and cmd_days_to_filter.isdigit():
			# Command is "/log [number]"
			days_to_print = int(cmd_days_to_filter)
		elif cmd_days_to_filter == "all":
			# This won't work. Will never work. There's a length limit on messages.
			# Whatever, this variant had been missing for months and nobody even noticed...
			days_to_print = 31
		else:
			days_to_print = 1

		days = {}
		# reversed() doesn't create a copy
		for line in reversed(self.logs.log):
			this_day = line.day()
			if this_day not in days:
				if len(days) >= days_to_print:
					break
				days[this_day] = []

			print_name = self.logs.try_get_name_and_surname(line.username)

			if line.inlab:
				days[this_day].append(f'<i>{print_name}</i> is in lab\n')
			else:
				days[this_day].append(f'<i>{print_name}</i>: {line.text}\n')

		msg = ''
		for this_day in days:
			msg += '<b>{day}</b>\n{rows}\n'.format(day=this_day, rows=''.join(days[this_day]))

		msg = msg + 'Latest log update: <b>{}</b>'.format(self.logs.log_last_update)
		self._send_message(msg)

	def stat(self, cmd_target_user=None):
		if cmd_target_user is None:
			# User asking its own /stat
			target_username = self.user['username']
		elif self.user['level'] == 1:
			# User asking somebody else's stats
			# TODO: allow normal users to do /stat by specifying their own username. Pointless but more consistent.
			target_username = str(cmd_target_user)
			if self.logs.get_entry_from_username(target_username) is None:
				target_username = None
				self._send_message('No statistics for the given user. Have you typed it correctly?')
		else:
			# Asked for somebody else's stats but not an admin
			target_username = None
			self._send_message('Sorry! You are not allowed	to see stat of other users!\nOnly admins can!')

		# Do we know what to search?
		if target_username is not None:
			# Downloads them only if needed
			self.logs.get_old_logs()
			# TODO: usual optimizations are possible
			self.logs.get_log()

			month_mins, total_mins = self.logs.count_time_user(target_username)
			month_mins_hh, month_mins_mm = self.logs.mm_to_hh_mm(month_mins)
			total_mins_hh, total_mins_mm = self.logs.mm_to_hh_mm(total_mins)

			msg = f'Stat for {self.logs.try_get_name_and_surname(target_username)}:' \
				f'\n<b>{month_mins_hh} h {month_mins_mm} m</b> this month.' \
				f'\n<b>{total_mins_hh} h {total_mins_mm} m</b> in total.' \
				f'\n\nLast log update: {self.logs.log_last_update}'
			self._send_message(msg)

	def history(self, item, cmd_limit=None):
		if cmd_limit is None:
			limit = 6
		else:
			limit = int(cmd_limit)
			if limit < 1:
				limit = 1
			elif limit > 50:
				limit = 50
		try:
			if self.tarallo.login(BOT_USER, BOT_PSW):
				history = self.tarallo.get_history(item, limit)
				if history is None:
					self._send_message(f'Item {item} not found.')
				else:
					msg = f'<b>History of item {item}</b>\n\n'
					entries = 0
					for index in range(0, len(history)):
						change = history[index]['change']
						h_user = history[index]['user']
						h_location = history[index]['other']
						h_time = datetime.datetime.fromtimestamp(
							int(history[index]['time'])).strftime('%d-%m-%Y %H:%M:%S')
						if change == 'M':
							msg += f'➡️ Moved to <b>{h_location}</b>\n'
						elif change == 'U':
							msg += '🛠️ Updated features\n'
						elif change == 'C':
							msg += '📋 Created\n'
						elif change == 'R':
							msg += f'✏️ Renamed from <b>{h_location}</b>\n'
						elif change == 'D':
							msg += '❌ Deleted\n'
						else:
							msg += f'Unknown change {change}'
						entries += 1
						msg += f'{h_time} by <i>{self.logs.try_get_name_and_surname(h_user)}</i>\n\n'
						if entries >= 6:
							self._send_message(msg)
							msg = ''
							entries = 0
					if entries != 0:
						self._send_message(msg)
			else:
				self._send_message('Sorry, cannot authenticate with T.A.R.A.L.L.O.')
		except RuntimeError:
			fail_msg = f'Sorry, an error has occurred (HTTP status: {str(self.tarallo.last_status)}).'
			self._send_message(fail_msg)

	def top(self, cmd_filter=None):
		"""
		Called with /top <filter>.
		Currently, the only accepted filter is "all", and besides that,
		it returns the monthly filter
		"""
		if self.user['level'] == 1:
			# Downloads them only if needed
			self.logs.get_old_logs()
			# TODO: usual optimizations are possible
			self.logs.get_log()

			# TODO: add something like "/top 04 2018" that returns top list for April 2018
			if cmd_filter == "all":
				msg = 'Top User List!\n'
				rank = self.logs.count_time_all()
			else:
				msg = 'Top Monthly User List!\n'
				rank = self.logs.count_time_month()
			# sort the dict by value in descending order (and convert dict to list of tuples)
			rank = sorted(rank.items(), key=lambda x: x[1], reverse=True)

			n = 0
			for (rival, time) in rank:
				entry = self.logs.get_entry_from_username(rival)
				if entry is not None:
					n += 1
					time_hh, time_mm = self.logs.mm_to_hh_mm(time)
					if entry["level"] == 1 or entry["level"] == 2:
						msg += f'{n}) [{time_hh}:{time_mm}] <b>{self.logs.try_get_name_and_surname(rival)}</b>\n'
					else:
						msg += f'{n}) [{time_hh}:{time_mm}] {self.logs.try_get_name_and_surname(rival)}\n'

			msg += f'\nLast log update: {self.logs.log_last_update}'
			self._send_message(msg)
		else:
			self._send_message('Sorry! You are not allowed to use this function! \nOnly admins can')

	def not_allowed(self, user_json_error):
		"""
		Called when user is not allowed to use the bot (banned, no telegram ID in user.json, etc...)
		"""

		msg = f'Sorry, you are not allowed to use this bot.\n\
If you\'re a member of <a href="http://weeeopen.polito.it/">WEEE Open</a>, \
ask the administrators to authorize your account and /start the bot again.\n\n\
Your user ID is: <b>{self.last_user_id}</b>'

		if user_json_error is not None:
			msg += "\n\nWarning: error in users file, {user_json_error}.\nMaybe you\'re authorized but the file is broken?"

		self._send_message(msg)

	def store_id(self):
		first_name = self.last_update['message']['from']['first_name']

		if 'username' in self.last_update['message']['from']:
			username = self.last_update['message']['from']['username']
		else:
			username = ""

		if 'last_name' in self.last_update['message']['from']:
			last_name = self.last_update['message']['from']['last_name']
		else:
			last_name = ""

		self.logs.store_new_user(self.last_user_id, first_name, last_name, username)

	def unknown(self):
		"""
		Called when an unknown command is received
		"""
		self._send_message(self.bot.unknown_command_message + "\n\nType /help for list of commands")

	def help(self):
		help_message = "Available commands and options:\n\n\
/inlab - Show the people in lab\n\
/log - Show log of the day\n\
/log <i>n</i> - Show last <i>n</i> days worth of logs\n\
/stat - Show hours you've spent in lab\n\
/history <i>item</i> - Show history for an item, straight outta T.A.R.A.L.L.O.\n\
/history <i>item</i> <i>n</i> - Show <i>n</i> history entries\n"

		if self.user['level'] == 1:
			help_message += "\n<b>only for admin users</b>\n\
/stat <i>name.surname</i> - Show hours spent in lab by this user\n\
/top - Show a list of top users by hours spent this month\n\
/top all - Show a list of top users by hours spent\n"
		self._send_message(help_message)


def main():
	"""main function of the bot"""
	oc = owncloud.Client(OC_URL)
	oc.login(OC_USER, OC_PWD)

	bot = BotHandler(TOKEN_BOT)
	tarallo = TaralloSession()
	logs = WeeelabLogs(oc)

	while True:
		# call the function to check if there are new messages
		last_update = bot.get_last_update()

		if last_update != -1:
			try:
				command = last_update['message']['text'].split()

				last_user_id = last_update['message']['from']['id']
				message_type = last_update['message']['chat']['type']
				print(last_update['message'])  # Extremely advanced debug techniques

				# Don't respond to messages in group chats
				if message_type == "private":
					# TODO: get_users downloads users.json from the cloud. For performance this could be done only once in a while
					logs.get_users()
					user = logs.get_entry_from_tid(last_user_id)

					# Instantiate a command handler with the current user information
					handler = CommandHandler(user, bot, tarallo, logs, last_update)

					if user is None or user["level"] == 0:
						handler.not_allowed(logs.error)
						if user is None:
							handler.store_id()
					else:
						if command[0] == "/start" or command[0] == "/start@weeelab_bot":
							handler.start()

						if command[0] == "/inlab" or command[0] == "/inlab@weeelab_bot":
							handler.inlab()

						elif command[0] == "/history" or command[0] == "/history@weeelab_bot":
							if len(command) < 2:
								bot.send_message(handler.last_chat_id, 'Sorry insert the item to search')
							elif len(command) < 3:
								handler.history(command[1])
							else:
								handler.history(command[1], command[2])

						elif command[0] == "/log" or command[0] == "/log@weeelab_bot":

							if len(command) > 1:
								handler.log(command[1])
							else:
								handler.log()

						elif command[0] == "/stat" or command[0] == "/stat@weeelab_bot":

							if len(command) > 1:
								handler.stat(command[1])
							else:
								handler.stat()

						elif command[0] == "/top" or command[0] == "/top@weeelab_bot":
							if len(command) > 1:
								handler.top(command[1])
							else:
								handler.top()

						elif command[0] == "/help" or command[0] == "/help@weeelab_bot":
							handler.help()

						else:
							handler.unknown()

			except:  # catch the exception if raised
				if "channel_post" in last_update:
					chat_id = last_update['channel_post']['chat']['id']
					print(bot.leave_chat(chat_id).text)
				print("ERROR!")
				print(last_update)
				print(traceback.format_exc())


# call the main() until a keyboard interrupt is called
if __name__ == '__main__':
	try:
		main()
	except KeyboardInterrupt:
		exit()
