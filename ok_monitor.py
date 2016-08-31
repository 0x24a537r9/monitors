import flask
import logging
import monitor
import requests
import requests.exceptions
import sys


server, logger = monitor.server, logging.getLogger('monitor.ok_monitor')


def start(raw_args=sys.argv[1:]):
  monitor.parse_args(
      'Ok monitor',
      "Monitors another monitor's /ok endpoint, triggering an email alert if for any reason it "
      "can't be reached.",
      raw_arg_defs=[{
        'name': 'server_url',
        'help': 'The URL of the server to be monitored',
      }, {
        'name': '--ok_timeout_s',
        'dest': 'ok_timeout_s',
        'default': 10,
        'type': float,
        'help': 'The maximum period (in seconds) before timing out an /ok request',
      }],
      raw_args=raw_args)
  monitor.start(poll)


def poll():
  url = '%s/ok' % monitor.args.server_url
  try:
    response = requests.get(url, timeout=monitor.args.ok_timeout_s)
  except requests.exceptions.Timeout:
    logger.error('Request for "%s" timed out after %ss.', url, monitor.args.ok_timeout_s)
    monitor.alert('%s is timing out' % monitor.args.server_url, 'ok_monitor_timing_out',
                  {'url': url, 'ok_timeout_s': monitor.args.ok_timeout_s})
    return
  except Exception:
    logger.error('Failed to connect to "%s".', url)
    monitor.alert('%s is unreachable' % monitor.args.server_url, 'ok_monitor_unreachable',
                  {'url': url})
    return

  if response.status_code != 200 or response.text != 'ok':
    logger.error('Received %s HTTP code with response: "%s"', response.status_code, response.text)
    monitor.alert('%s is not ok' % monitor.args.server_url, 'ok_monitor_not_ok',
                  {'status_code': response.status_code, 'url': url, 'text': response.text})
    return


if __name__ == '__main__':
  start()