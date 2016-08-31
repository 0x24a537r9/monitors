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


server, logger = monitor.server, logging.getLogger('monitor.geofence_monitor')


def start(raw_args=sys.argv[1:]):
  monitor.parse_args(
      'Geofence monitor',
      'Monitors cars, triggering an email alert if any leave their prescribed geofences.',
      raw_arg_defs=[{
        'name': 'car_ids',
        'type': parse_ids,
        'nargs': '+',
        'help': 'The car IDs to monitor. IDs can be specified as single IDs or ID ranges such as "2-8"',
      }, {
        'name': '--car_status_url',
        'dest': 'car_status_url',
        'default': 'http://skurt-interview-api.herokuapp.com/carStatus/%s',
        'help': 'The URL pattern for the car status endpoint, with "%%s" to indicate the id insertion '
                'point',
      }, {
        'name': '--max_query_qps',
        'dest': 'query_delay_s',
        'default': 1,
        'type': lambda arg: 1 / float(arg),
        'help': 'The maximum QPS with which to query the server for individual car statuses',
      }, {
        'name': '--google_maps_api_key',
        'dest': 'google_maps_api_key',
        'default': 'AIzaSyDwHlJG6aS98VZPPOyv7hm1BHPnvwURink',
        'help': 'The API key for Google Static Maps, used to embed car location maps in geofence '
                'alert emails',
      }],
      raw_args=raw_args)
  # Flatten the car_ids args into a single sorted list of unique IDs.
  monitor.args.car_ids = sorted(set(itertools.chain.from_iterable(monitor.args.car_ids)))
  
  monitor.start(poll)


def parse_ids(arg):
  match = re.match(r'^(\d+)-(\d+)$', arg)
  try:
    return range(int(match.group(1)), int(match.group(2)) + 1) if match else [int(arg)]
  except:
    raise ValueError('Invalid ID arg: "%s"' % arg)


def poll():
  # Find the set of out-of-bounds cars.
  out_of_bounds_car_coords = []
  car_errors = []

  for car_id in monitor.args.car_ids:
    start_time = time.time()

    # Fetch the car's status.
    logger.debug('Fetching status for car %s.' % car_id)
    try:
      response = requests.get(monitor.args.car_status_url % car_id, timeout=10)
    except requests.exceptions.Timeout:
      logger.error('Request for car %s timed out after 10s.', car_id)
      car_errors.append((car_id, 'FETCH_TIMED_OUT'))
      continue

    if response.status_code != 200:
      logger.error('Received %s HTTP code for car %s with response: "%s"',
                   response.status_code, car_id, response.text)
      car_errors.append((car_id, 'INVALID_FETCH_RESPONSE'))
      continue
    geojson = response.json()

    # Extract the first Point feature in the GeoJSON response as the car's coordinates.
    car = next((feature for feature in geojson['features']
                if feature['geometry']['type'] == 'Point'), None)
    if not car:
      logger.error('No car coordinates for car %s in status response: "%s"', car_id, response.text)
      car_errors.append((car_id, 'NO_CAR_COORDS'))
      continue

    # Extract all Polygon features as the car's geofences.
    geofences = [feature for feature in geojson['features']
                 if feature['geometry']['type'] == 'Polygon']

    # Test whether the car is outside its geofence, marking if necessary.
    shape = shapely.geometry.shape
    if not any(shape(geofence['geometry']).contains(shape(car['geometry']))
               for geofence in geofences):
      logger.info('Car %s was found outside of its geofences.', car['properties']['id'])
      out_of_bounds_car_coords.append((car_id, car['geometry']['coordinates']))

    # Throttle, if necessary.
    throttle_delay = monitor.args.query_delay_s - (time.time() - start_time)
    if throttle_delay > 0:
      logger.debug('Throttling for %s seconds.' % throttle_delay)
      time.sleep(throttle_delay)

  # Alert by email if necessary.
  if out_of_bounds_car_coords:
    monitor.alert('Cars outside of geofences', 'geofence_monitor_geofence',
                  {
                    'car_coords': out_of_bounds_car_coords,
                    'google_maps_api_key': monitor.args.google_maps_api_key,
                  })

  if car_errors:
    monitor.alert('Geofence monitor errors', 'geofence_monitor_errors',
                  {'car_errors': car_errors})


if __name__ == '__main__':
  start()