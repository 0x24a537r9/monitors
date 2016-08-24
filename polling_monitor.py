import argparse
import collections
import flask
import logging
import re
import requests
import sys
import threading
import time


args, deps, callbacks, alive = None, None, [], False
app = flask.Flask(__name__)


Deps = collections.namedtuple('Deps', ['requests', 'time'])
DEFAULT_DEPS = Deps(requests=requests, time=time)


def start(name, description, arg_defs=[], raw_args=sys.argv[1:], raw_deps=DEFAULT_DEPS):
  global args, deps, alive
  args = parse_args(name, description, arg_defs, raw_args)
  deps = raw_deps
  alive = True
  logging.basicConfig(level=args.logging_level,
                      format='%(levelname)-8s %(asctime)s [%(name)s]: %(message)s')
  poll()
  app.run(port=args.port)


def parse_args(name, description, arg_defs, raw_args=sys.argv[1:]):
  parser = argparse.ArgumentParser(description=description)
  arg_defs += [{
    'name': '--alert_emails',
    'dest': 'alert_emails',
    'default': ['Cameron Behar <0x24a537r9@gmail.com>'],
    'type': lambda s: re.split(r'\s*,\s*', s),
    'help': 'The email addresses to alert if needed',
  }, {
    'name': '--monitor_email',
    'dest': 'monitor_email',
    'default': '%s <engineering+%s@skurt.com>' % (name, name.lower().replace(' ', '_')),
    'help': 'The email addresses from which to send alerts',
  }, {
    'name': '--poll_period_s',
    'dest': 'poll_period_s',
    'default': 5 * 60,
    'type': int,
    'help': 'The period (in seconds) with which to poll for status updates',
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
  logging.debug('Polling...')
  start_time = deps.time.time()

  if not callbacks:
    logging.critical('No polling callbacks implemented.')
    raise NotImplementedError('No polling callbacks implemented.')
  for callback in callbacks:
    callback()

  if alive:
    poll_delay = max(0, args.poll_period_s - (deps.time.time() - start_time))
    threading.Timer(poll_delay, poll).start()


def alert(subject, text):
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


@app.route('/killkillkill')
def kill():
  logging.info('Received killkillkill request. Shutting down...')
  func = flask.request.environ.get('werkzeug.server.shutdown')
  if func is None:
    raise RuntimeError('Not running with the Werkzeug Server')
  func()
  global alive
  alive = False
  return 'Shutting down...'
