import argparse
import flask
import json
import logging
import re
import requests
import smtplib
import sys
import threading
import time
import urllib
import urllib2

from email.mime.text import MIMEText
from shapely.geometry import shape


app = flask.Flask(__name__)


def parse_ids(arg):
  match = re.match(r'^(\d+)-(\d+)$', arg)
  try:
    return range(int(match.group(1)), int(match.group(2)) + 1) if match else [int(arg)]
  except e:
    raise ValueError('Invalid ID arg: "%s"' % arg)


def parse_args(args=sys.argv[1:]):
  parser = argparse.ArgumentParser(description='Monitors cars, triggering an email alert if any '
                                               'leave their prescribed geofences.')
  arg_defs = [{
    'name': 'car_ids',
    'type': parse_ids,
    'nargs': '+',
    'help': 'The car IDs to monitor. IDs can be specified as single IDs or ID ranges such as "2-8"',
  }, {
    'name': '--car_status_endpoint',
    'dest': 'car_status_endpoint',
    'default': 'http://skurt-interview-api.herokuapp.com/carStatus/%s',
    'help': 'The URL pattern for the car status endpoint, with "%%s" to indicate the id insertion '
            'point',
  }, {
    'name': '--alert_emails',
    'dest': 'alert_emails',
    'default': ['Cameron Behar <0x24a537r9@gmail.com>'],
    'type': lambda s: re.split(r'\s*,\s*', s),
    'help': 'The email addresses to alert in case of a car out of its geofence',
  }, {
    'name': '--monitor_email',
    'dest': 'monitor_email',
    'default': 'Geofence monitor <engineering+geofence_monitor@skurt.com>',
    'help': 'The email addresses from which to send alerts',
  }, {
    'name': '--poll_period_s',
    'dest': 'poll_period_s',
    'default': 5 * 60,
    'type': int,
    'help': 'The period (in seconds) with which to poll the server for car statuses',
  }, {
    'name': '--max_poll_qps',
    'dest': 'poll_query_delay_s',
    'default': 1,
    'type': lambda arg: 1 / float(arg),
    'help': 'The maximum QPS with which to poll the server for car statuses',
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
    'name': '--log',
    'dest': 'logging_level',
    'default': logging.INFO,
    'type': lambda level: getattr(logging, level),
    'choices': (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL),
    'help': 'The logging level to use',
  }]
  for arg_def in arg_defs:
    parser.add_argument(arg_def.pop('name'), **arg_def)
  args = parser.parse_args(args)

  # Flatten the car_ids args into a set.
  args.car_ids = sorted(reduce(lambda acc, ids: acc | set(ids), args.car_ids, set()))
  return args


def poll():
  # Find the set of out-of-bounds cars.
  out_of_bounds_car_ids = set()
  for car_id in args.car_ids:
    start_time = time.time()

    # Fetch the car's status.
    logging.debug('Fetching status for car %s.' % car_id)
    geojson = json.load(urllib2.urlopen(args.car_status_endpoint % car_id))

    # Extract the first Point feature in the GeoJSON response as the car's coordinates.
    car = next((feature for feature in geojson['features']
                if feature['geometry']['type'] == 'Point'), None)
    if not car:
      logging.warning('No car coordinates for car %s in status response: %s', car_id, geojson)
      continue

    # Extract all Polygon features as the car's geofences.
    geofences = [feature for feature in geojson['features']
                 if feature['geometry']['type'] == 'Polygon']

    # Mark the car as out-of-bounds, if necessary.
    if not any(shape(geofence['geometry']).contains(shape(car['geometry']))
               for geofence in geofences):
      logging.info('Car found outside of geofence: %s', car['properties']['id'])
      out_of_bounds_car_ids.add(car_id)

    # Throttle, if necessary.
    throttle_delay = args.poll_query_delay_s - (time.time() - start_time)
    if throttle_delay > 0:
      logging.debug('Throttling for %s seconds.' % throttle_delay)
      time.sleep(throttle_delay)

  # Alert by email if necessary.
  if out_of_bounds_car_ids:
    requests.post(
        args.mailgun_messages_endpoint,
        auth=('api', args.mailgun_api_key),
        data={
          'from': args.monitor_email,
          'to': ', '.join(args.alert_emails),
          'subject': '[ALERT] Cars outside of geofences',
          'text': 'Cars [%s] are outside of their geofences!' %
                  ', '.join(str(car_id) for car_id in sorted(out_of_bounds_car_ids))
        })
  
  # Queue another poll event.
  threading.Timer(args.poll_period_s, poll).start()


@app.route('/')
def status():
  return 'Not yet implemented'


@app.route('/ok')
def ok():
  return 'ok'


if __name__ == '__main__':
  args = parse_args()
  logging.basicConfig(level=args.logging_level,
                      format='%(levelname)-8s %(asctime)s [%(name)s]: %(message)s')

  poll()
  app.run()