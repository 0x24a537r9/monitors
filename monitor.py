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
import traceback

name, args, server, poll_fns, poll_timer, silence_timer, is_alive = (
    '', None, None, [], None, None, False)

server = flask.Flask(__name__)
server.config.from_envvar('FLASKR_SETTINGS', silent=True)
logger = logging.getLogger('monitor')


def parse_args(raw_name, raw_description, raw_arg_defs=[], raw_args=sys.argv[1:]):
  global name, args
  name = raw_name
  parser = argparse.ArgumentParser(description=raw_description)
  name_slug = name.lower().replace(' ', '_')
  raw_arg_defs += [{
    'name': 'monitor_url',
    'help': 'The URL by which this monitor can be reached, used for convenience status/management '
            'links in the alert emails',
  }, {
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
    'default': 5 * 60.0,
    'type': float,
    'help': 'The period (in seconds) with which to poll for status updates',
  }, {
    'name': '--min_poll_padding_period_s',
    'dest': 'min_poll_padding_period_s',
    'default': 10.0,
    'type': float,
    'help': 'The minimum period (in seconds) between when one polling operation finishes and the '
            'next one begins. Used for alerting in case the polling method is slow and in danger '
            'of overrunning the configured --poll_period_s.',
  }, {
    'name': '--mailgun_messages_url',
    'dest': 'mailgun_messages_url',
    'default': 'https://api.mailgun.net/v3/sandboxf3f15ea9e4c743199c24cb3b628208c0.mailgun.org/'
               'messages',
    'help': 'The URL for the Mailgun messages endpoint',
  }, {
    'name': '--mailgun_api_key',
    'dest': 'mailgun_api_key',
    'default': '',
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
    'dest': 'log_level',
    'default': logging.INFO,
    'type': lambda level: getattr(logging, level),
    'choices': (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL),
    'help': 'The logging level to use',
  }]
  for arg_def in raw_arg_defs:
    parser.add_argument(arg_def.pop('name'), **arg_def)
  args = parser.parse_args(raw_args)


def start(raw_poll_fns=None):
  global poll_fns, poll_timer, is_alive
  is_alive = True
  set_up_logging()
  if raw_poll_fns:
    poll_fns += raw_poll_fns if isinstance(raw_poll_fns, collections.Iterable) else [raw_poll_fns]
  # Delay so that the Flask server is up before polling begins.
  poll_timer = threading.Timer(1, poll)
  poll_timer.start()
  if not server.config.get('TESTING'):
    server.run(port=args.port)


def set_up_logging():
  logger.handlers = []  # Clean up past handlers when repeatedly starting up in unit tests.
  logger.setLevel(args.log_level)
  formatter = logging.Formatter('%(levelname)-8s %(asctime)s [%(name)s]: %(message)s')

  stdout = logging.StreamHandler(stream=sys.stdout)
  stdout.setLevel(args.log_level)
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


def poll():
  if not is_alive:
    return

  logger.info('Polling...')
  start_time = time.time()

  if not poll_fns:
    logger.critical('No polling poll_fns implemented.')
    raise NotImplementedError('No polling poll_fns implemented.')
  for poll_fn in poll_fns:
    try:
      poll_fn()
    except Exception as e:
      traceback_str = ''.join(traceback.format_exception(*sys.exc_info()))
      logger.exception('Unhandled exception in delegate poll function.')
      alert('%s encountered an exception' % name, 'monitor_exception', {'traceback': traceback_str})

  if is_alive:
    poll_delay_s = args.poll_period_s - (time.time() - start_time)
    if poll_delay_s < 0:
      logger.error('Overran polling period by %ss.', abs(poll_delay_s))
      alert('%s is overrunning' % name, 'monitor_overrunning',
            {'overrun_s': abs(poll_delay_s), 'poll_period_s': args.poll_period_s})
    elif poll_delay_s <= args.min_poll_padding_period_s:
      logger.warning('In danger of overrunning polling period. Only %ss left until next poll.',
                     poll_delay_s)
      alert('%s is in danger of overrunning' % name, 'monitor_in_danger_of_overrunning',
            {'poll_delay_s': poll_delay_s, 'poll_period_s': args.poll_period_s})

    global poll_timer
    poll_timer = threading.Timer(max(0, poll_delay_s), poll)
    poll_timer.start()


def alert(subject, template, template_args={}):
  logger.info('Sending alert: "%s"', subject)
  try:
    if template[-5:] != '.html':
      template += '_alert.html'
    template_args.update({
      'monitor_name': name,
      'monitor_url': args.monitor_url,
    })
    with server.app_context():
      requests.post(
          args.mailgun_messages_url,
          auth=('api', args.mailgun_api_key),
          data={
            'from': args.monitor_email,
            'to': ', '.join(args.alert_emails),
            'subject': '[ALERT] %s' % subject,
            'html': flask.render_template(template, **template_args),
          },
          timeout=10)
  except:
    traceback_str = ''.join(traceback.format_exception(*sys.exc_info()))
    logger.exception('Failed to send alert "%s" with template "%s" and args: %s' %
                     (subject, template, template_args))


def silence(duration_s):
  global is_alive, silence_timer
  if silence_timer:
    silence_timer.cancel()

  is_alive = False
  silence_timer = threading.Timer(duration_s, unsilence)
  silence_timer.start()
  logger.info('Silenced for %ss.', duration_s)


def unsilence():
  global is_alive
  if is_alive:
    logger.info('Already unsilenced.')
    return False
  elif silence_timer:
    silence_timer.cancel()

  logger.info('Unsilenced.')
  is_alive = True
  poll()
  return True


def render_page(template, title, template_args={}):
  try:
    if template[-5:] != '.html':
      template += '_page.html'
    template_args.update({
      'monitor_name': name,
      'monitor_url': args.monitor_url,
      'title': title,
    })
    return flask.render_template(template, **template_args)
  except:
    traceback_str = ''.join(traceback.format_exception(*sys.exc_info()))
    logger.exception('Failed to render template "%s" with args: %s' % (template, template_args))
    return flask.render_template(
        'error_page.html',
        monitor_name=name,
        title='Error',
        message='Failed to render template "%s" with args: %s' % (template, template_args),
        traceback=traceback_str)


def reset():
  global name, args, poll_fns, poll_timer, silence_timer, is_alive
  if poll_timer:
    poll_timer.cancel()
  if silence_timer:
    silence_timer.cancel()
  name, args, poll_fns, poll_timer, silence_timer, is_alive = (
      '', None, [], None, None, False)


@server.route('/ok')
def handle_ok():
  return 'ok'


@server.route('/silence')
@server.route('/silence/<duration>')
def handle_silence(duration='1h'):
  duration_components = re.match(
      r'^((?P<days>\d+?)d)?((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?$',
      duration)
  if not duration_components:
    logger.error('Received invalid silence duration: "%s"', duration)
    return render_page('error', 'Error', {'message': 'Invalid silence duration: "%s"' % duration})

  timedelta_args = dict((when, int(interval or '0'))
                        for when, interval in duration_components.groupdict().iteritems())
  silence(datetime.timedelta(**timedelta_args).total_seconds())
  return render_page('silence', 'Silence', {'duration': duration})


@server.route('/unsilence')
def handle_unsilence():
  return render_page('unsilence', 'Unsilence', {'silenced': unsilence()})


@server.route('/args')
def handle_args():
  sorted_args = sorted(vars(args).iteritems(), key=lambda item: item[0])
  logger.info('\n'.join('%s=%s' % arg_value for arg_value in sorted_args))
  return render_page('args', 'Args', {'args': sorted_args})


@server.route('/logs')
@server.route('/logs/<level>')
def handle_logs(level='INFO'):
  level = level.upper()
  if not level in ('INFO', 'WARNING', 'ERROR'):
    logger.error('Received invalid log level: "%s"', level)
    return render_page('error', 'Error', {'message': 'Invalid log level: "%s". Choose between '
                                                     '"INFO", "WARNING", or "ERROR".' % level})

  for handler in logger.handlers:
    handler.flush()
  with open('%s.%s.log' % (args.log_file_prefix, level), 'r') as f:
    logs_data = f.read()
  return render_page('logs', '%s logs' % level, {'logs_data': logs_data})


@server.route('/kill')
def handle_kill():
  logger.info('Received kill request. Shutting down...')
  func = flask.request.environ.get('werkzeug.server.shutdown')
  if func is None:
    flask.abort(404)
  func()
  reset()
  logging.shutdown()
  exit(-1)
