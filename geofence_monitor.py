import argparse
import json
import logging
import requests
import smtplib
import threading
import time
import urllib
import urllib2

from email.mime.text import MIMEText
from shapely.geometry import shape
from flask import Flask

parser = argparse.ArgumentParser(
    description='Monitors cars, triggering an email alert if any leave their prescribed geofences.')
parser.add_argument('--mailgun_api_key', dest='mailgun_api_key',
                    default='key-db805e58c7522624b6b6c7fbb96dcbb0',
                    help='The API key for the mailgun account used to send alert emails')
args = parser.parse_args()


ALERT_EMAILS = ['Cameron Behar <0x24a537r9@gmail.com>']
MONITOR_EMAIL = 'Geofence monitor <engineering+geofence_monitor@skurt.com>'

CAR_IDS = set(range(1, 12))
CAR_STATUS_ENDPOINT = 'http://skurt-interview-api.herokuapp.com/carStatus/%s'

app = Flask(__name__)


@app.route('/')
def status():
  return 'Not yet implemented'


@app.route('/ok')
def ok():
  return 'ok'


def poll():
  # Find the set of out-of-bounds cars.
  out_of_bounds_car_ids = set()
  for car_id in CAR_IDS:
    geojson = json.load(urllib2.urlopen(CAR_STATUS_ENDPOINT % car_id))

    car = next((feature for feature in geojson['features']
                if feature['geometry']['type'] == 'Point'), None)
    if not car:
      logging.warning('No car coordinates in %s', geojson)
      continue

    geofences = [feature for feature in geojson['features']
                 if feature['geometry']['type'] == 'Polygon']

    if not any(shape(geofence['geometry']).contains(shape(car['geometry']))
               for geofence in geofences):
      print 'Out of bounds: %s' % car['properties']['id']
      out_of_bounds_car_ids.add(car_id)

  # Alert if necessary.
  if out_of_bounds_car_ids:
    requests.post(
        'https://api.mailgun.net/v3/sandboxf3f15ea9e4c743199c24cb3b628208c0.mailgun.org/messages',
        auth=('api', args.mailgun_api_key),
        data={
            'from': MONITOR_EMAIL,
            'to': ', '.join(ALERT_EMAILS),
            'subject': '[Alert] Cars outside of geofences',
            'text': 'Cars [%s] are out of bounds!' %
                    ', '.join(str(car_id) for car_id in sorted(out_of_bounds_car_ids))
        })
  
  # Queue another poll event.
  threading.Timer(10, poll).start()


if __name__ == '__main__':
  poll()
  app.run()