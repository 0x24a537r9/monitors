import argparse
import collections
import datetime
import flask
import logging
import logging.handlers
import re
import requests
import sys
import threading
import time


name, args, deps, callbacks, alive = '', None, None, [], False
app = flask.Flask(__name__)
logger = logging.getLogger('polling_monitor')

Deps = collections.namedtuple('Deps', ['requests', 'time'])
DEFAULT_DEPS = Deps(requests=requests, time=time)


def start(raw_name, raw_description, raw_arg_defs=[], raw_args=sys.argv[1:], raw_deps=DEFAULT_DEPS):
  global name, args, deps, alive
  name = raw_name
  args = parse_args(raw_description, raw_arg_defs, raw_args)
  deps = raw_deps
  alive = True
  set_up_logging()
  threading.Timer(1, poll).start()
  app.run(port=args.port)


def set_up_logging():
  logger.setLevel(args.logging_level)
  formatter = logging.Formatter('%(levelname)-8s %(asctime)s [%(name)s]: %(message)s')

  stdout = logging.StreamHandler(stream=sys.stdout)
  stdout.setLevel(args.logging_level)
  stdout.setFormatter(formatter)
  logger.addHandler(stdout)

  info = logging.handlers.TimedRotatingFileHandler(
      '%s.INFO.log' % args.log_file_prefix, when='d', interval=1, backupCount=7)
  info.setLevel(logging.INFO)
  info.setFormatter(formatter)
  logger.addHandler(info)

  warning = logging.handlers.TimedRotatingFileHandler(
      '%s.WARNING.log' % args.log_file_prefix, when='d', interval=1, backupCount=7)
  warning.setLevel(logging.WARNING)
  warning.setFormatter(formatter)
  logger.addHandler(warning)

  error = logging.handlers.TimedRotatingFileHandler(
      '%s.ERROR.log' % args.log_file_prefix, when='d', interval=1, backupCount=7)
  error.setLevel(logging.ERROR)
  error.setFormatter(formatter)
  logger.addHandler(error)


def parse_args(description, arg_defs, raw_args=sys.argv[1:]):
  parser = argparse.ArgumentParser(description=description)
  name_slug = name.lower().replace(' ', '_')
  arg_defs += [{
    'name': '--alert_emails',
    'dest': 'alert_emails',
    'default': ['Cameron Behar <0x24a537r9@gmail.com>'],
    'type': lambda s: re.split(r'\s*,\s*', s),
    'help': 'The email addresses to alert if needed',
  }, {
    'name': '--monitor_email',
    'dest': 'monitor_email',
    'default': '%s <engineering+%s@skurt.com>' % (name, name_slug),
    'help': 'The email addresses from which to send alerts',
  }, {
    'name': '--poll_period_s',
    'dest': 'poll_period_s',
    'default': 5 * 60,
    'type': int,
    'help': 'The period (in seconds) with which to poll for status updates',
  }, {
    'name': '--min_poll_padding_period_s',
    'dest': 'min_poll_padding_period_s',
    'default': 10,
    'type': int,
    'help': 'The minimum period (in seconds) between when one polling operation finishes and the '
            'next one begins. Used for alerting in case the polling method is slow and in danger '
            'of overrunning the configured --poll_period_s.',
  }, {
    'name': '--mailgun_messages_endpoint',
    'dest': 'mailgun_messages_endpoint',
    'default': 'https://api.mailgun.net/v3/sandboxf3f15ea9e4c743199c24cb3b628208c0.mailgun.org/'
               'messages',
    'help': 'The URL for the Mailgun messages endpoint',
  }, {
    'name': '--mailgun_api_key',
    'dest': 'mailgun_api_key',
    'default': 'key-db805e58c7522624b6b6c7fbb96dcbb0',
    'help': 'The API key for the mailgun account used to send alert emails',
  }, {
    'name': '--port',
    'dest': 'port',
    'default': 5000,
    'type': int,
    'help': 'The port to use for the monitoring HTTP server',
  }, {
    'name': '--log_file_prefix',
    'dest': 'log_file_prefix',
    'default': name_slug,
    'help': 'The prefix for the file used for logging',
  }, {
    'name': '--log',
    'dest': 'logging_level',
    'default': logging.INFO,
    'type': lambda level: getattr(logging, level),
    'choices': (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL),
    'help': 'The logging level to use',
  }]
  for arg_def in arg_defs:
    parser.add_argument(arg_def.pop('name'), **arg_def)
  return parser.parse_args(raw_args)


def poll():
  if not alive:
    return

  logger.info('Polling...')
  start_time = deps.time.time()

  if not callbacks:
    logger.critical('No polling callbacks implemented.')
    raise NotImplementedError('No polling callbacks implemented.')
  for callback in callbacks:
    callback()

  if alive:
    poll_delay = args.poll_period_s - (deps.time.time() - start_time)
    if poll_delay < 0:
      logger.error('Overran polling period by %ss.', abs(poll_delay))
      alert('%s is overrunning' % name,
            '%s is unable to poll as frequently as expected because the polling method is taking '
            '%ss longer than the polling period (%ss). Either optimize the polling method to run '
            'more quickly or configure the monitor with a longer polling period.' %
            (name, abs(poll_delay), args.poll_period_s))
    elif poll_delay <= args.min_poll_padding_period_s:
      logger.warning('In danger of overrunning polling period. Only %ss left until next poll.',
                     poll_delay)
      alert('%s is in danger of overrunning' % name,
            '%s is in danger of being unable to poll as frequently as expected because the polling '
            'method is taking only %ss less than the polling period (%ss). Either optimize the '
            'polling method to run more quickly or configure the monitor with a longer polling '
            'period.' % (name, poll_delay, args.poll_period_s))
    threading.Timer(max(0, poll_delay), poll).start()


def alert(subject, text):
  logger.info('Sending alert: "%s"', subject)
  deps.requests.post(
      args.mailgun_messages_endpoint,
      auth=('api', args.mailgun_api_key),
      data={
        'from': args.monitor_email,
        'to': ', '.join(args.alert_emails),
        'subject': '[ALERT] %s' % subject,
        'text': text,
      })


def reset():
  args, deps, callbacks, alive = None, None, [], False


@app.route('/')
def status():
  return 'Not yet implemented'


@app.route('/ok')
def ok():
  return 'ok'


@app.route('/silence')
def silence():
  duration_string = flask.request.args.get('duration', '1h')
  duration_components = re.match(
      r'^((?P<days>\d+?)d)?((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?$',
      duration_string)
  if not duration_components:
    logger.error('Received invalid silence duration: "%s"', duration_string)
    return 'Invalid silence duration: "%s"' % duration_string

  global alive
  alive = False
  timedelta_args = dict((when, int(interval or '0'))
                        for when, interval in duration_components.groupdict().iteritems())
  threading.Timer(datetime.timedelta(**timedelta_args).total_seconds(), unsilence).start()

  logger.info('Silenced for %s.', duration_string)
  return 'Silenced for %s.' % duration_string


@app.route('/unsilence')
def unsilence():
  logger.info('Unsilenced.')
  global alive
  alive = True
  poll()
  return 'Unsilenced'


@app.route('/killkillkill')
def kill():
  logger.info('Received killkillkill request. Shutting down...')
  func = flask.request.environ.get('werkzeug.server.shutdown')
  if func is None:
    raise RuntimeError('Not running with the Werkzeug Server')
  func()
  global alive
  alive = False
  exit(-1)
