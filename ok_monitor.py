import flask
import itertools
import logging
import monitor
import re
import requests
import requests.exceptions
import shapely.geometry
import sys
import time


server, logger = monitor.server, logging.getLogger('monitor.ok_monitor')


def start(raw_args=sys.argv[1:]):
  monitor.callbacks.append(poll)
  monitor.start(
      'Ok monitor',
      "Monitors another monitor's /ok endpoint, triggering an email alert if for any reason it "
      "can't be reached.",
      raw_arg_defs=[{
        'name': '--monitor_ok_endpoint',
        'dest': 'monitor_ok_endpoint',
        'default': '',
        'help': 'The /ok URL for the monitor server to be monitored',
      }],
      raw_args=raw_args)


def poll():
  url = '%s/ok' % monitor.args.monitor_ok_endpoint
  try:
    response = requests.get(url, timeout=10)
  except requests.exceptions.Timeout:
    logger.error('Request for "%s" timed out after 10s.', url)
    monitor.alert('%s is not ok' % monitor.args.monitor_ok_endpoint,
                  'Request for "%s" timed out after 10s.' % url)
    return
  except Exception:
    logger.error('Failed to connect to "%s".', url)
    monitor.alert('%s is unreachable' % monitor.args.monitor_ok_endpoint,
                  '"%s" could not be reached.' % url)
    return

  if response.status_code != 200 or response.text != 'ok':
    logger.error('Received %s HTTP code with response: %s',
                 response.status_code, response.text)
    monitor.alert('%s is not ok' % monitor.args.monitor_ok_endpoint,
                  'Received %s HTTP code with response: %s' % (response.status_code, response.text))
    return


if __name__ == '__main__':
  start()