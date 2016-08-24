import argparse
import collections
import flask
import json
import logging
import polling_monitor as pm
import re
import requests
import shapely.geometry
import sys
import threading
import time
import urllib
import urllib2


Deps = collections.namedtuple('Deps', ('geometry', 'urllib2') + pm.Deps._fields)
DEFAULT_DEPS = Deps(geometry=shapely.geometry, urllib2=urllib2, **pm.DEFAULT_DEPS._asdict())


def start(raw_args=sys.argv[1:], raw_deps=DEFAULT_DEPS):
  pm.callbacks.append(poll)
  pm.start(
      'Geofence monitor',
      'Monitors cars, triggering an email alert if any leave their prescribed geofences.',
      arg_defs=[{
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
        'name': '--max_query_qps',
        'dest': 'query_delay_s',
        'default': 1,
        'type': lambda arg: 1 / float(arg),
        'help': 'The maximum QPS with which to query the server for individual car statuses',
      }],
      raw_args=raw_args,
      raw_deps=DEFAULT_DEPS)


def parse_ids(arg):
  match = re.match(r'^(\d+)-(\d+)$', arg)
  try:
    return range(int(match.group(1)), int(match.group(2)) + 1) if match else [int(arg)]
  except e:
    raise ValueError('Invalid ID arg: "%s"' % arg)


def poll():
  # Find the set of out-of-bounds cars.
  out_of_bounds_car_ids = set()
  # Flatten the car_ids args into a single sorted list of unique IDs.
  car_ids = sorted(reduce(lambda acc, ids: acc | set(ids), pm.args.car_ids, set()))
  for car_id in car_ids:
    start_time = pm.deps.time.time()

    # Fetch the car's status.
    logging.debug('Fetching status for car %s.' % car_id)
    geojson = json.load(urllib2.urlopen(pm.args.car_status_endpoint % car_id))

    # Extract the first Point feature in the GeoJSON response as the car's coordinates.
    car = next((feature for feature in geojson['features']
                if feature['geometry']['type'] == 'Point'), None)
    if not car:
      logging.warning('No car coordinates for car %s in status response: %s', car_id, geojson)
      continue

    # Extract all Polygon features as the car's geofences.
    geofences = [feature for feature in geojson['features']
                 if feature['geometry']['type'] == 'Polygon']

    # Test whether the car is outside its geofence, marking if necessary.
    shape = pm.deps.geometry.shape
    if not any(shape(geofence['geometry']).contains(shape(car['geometry']))
               for geofence in geofences):
      logging.info('Car found outside of geofence: %s', car['properties']['id'])
      out_of_bounds_car_ids.add(car_id)

    # Throttle, if necessary.
    throttle_delay = pm.args.query_delay_s - (pm.deps.time.time() - start_time)
    if throttle_delay > 0:
      logging.debug('Throttling for %s seconds.' % throttle_delay)
      pm.deps.time.sleep(throttle_delay)

  # Alert by email if necessary.
  if out_of_bounds_car_ids:
    pm.alert('Cars outside of geofences',
             'Cars [%s] are outside of their geofences!' %
             ', '.join(str(car_id) for car_id in sorted(out_of_bounds_car_ids)))


if __name__ == '__main__':
  start()