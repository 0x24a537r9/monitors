import flask
import logging
import monitor
import re
import requests
import shapely.geometry
import sys
import time


server = monitor.server
logger = logging.getLogger('monitor.geofence_monitor')

INVALID_FETCH_RESPONSE = 'INVALID_FETCH_RESPONSE'
NO_CAR_COORDS = 'NO_CAR_COORDS'


def start(raw_args=sys.argv[1:]):
  monitor.callbacks.append(poll)
  monitor.start(
      'Geofence monitor',
      'Monitors cars, triggering an email alert if any leave their prescribed geofences.',
      raw_arg_defs=[{
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
      raw_args=raw_args)


def parse_ids(arg):
  match = re.match(r'^(\d+)-(\d+)$', arg)
  try:
    return range(int(match.group(1)), int(match.group(2)) + 1) if match else [int(arg)]
  except:
    raise ValueError('Invalid ID arg: "%s"' % arg)


def poll():
  # Find the set of out-of-bounds cars.
  car_ids_out_of_bounds = []
  car_id_errors = []

  # Flatten the car_ids args into a single sorted list of unique IDs.
  car_ids = sorted(reduce(lambda acc, ids: acc | set(ids), monitor.args.car_ids, set()))
  for car_id in car_ids:
    start_time = time.time()

    # Fetch the car's status.
    logger.debug('Fetching status for car %s.' % car_id)
    response = requests.get(monitor.args.car_status_endpoint % car_id)
    if response.status_code != 200:
      logger.error('Received %s HTTP code for car %s with response: %s',
                   response.status_code, car_id, response.text)
      car_id_errors.append((car_id, INVALID_FETCH_RESPONSE))
      continue
    geojson = response.json()

    # Extract the first Point feature in the GeoJSON response as the car's coordinates.
    car = next((feature for feature in geojson['features']
                if feature['geometry']['type'] == 'Point'), None)
    if not car:
      logger.error('No car coordinates for car %s in status response: %s', car_id, response.text)
      car_id_errors.append((car_id, NO_CAR_COORDS))
      continue

    # Extract all Polygon features as the car's geofences.
    geofences = [feature for feature in geojson['features']
                 if feature['geometry']['type'] == 'Polygon']

    # Test whether the car is outside its geofence, marking if necessary.
    shape = shapely.geometry.shape
    if not any(shape(geofence['geometry']).contains(shape(car['geometry']))
               for geofence in geofences):
      logger.info('Car %s was found outside of its geofences.', car['properties']['id'])
      car_ids_out_of_bounds.append(car_id)

    # Throttle, if necessary.
    throttle_delay = monitor.args.query_delay_s - (time.time() - start_time)
    if throttle_delay > 0:
      logger.debug('Throttling for %s seconds.' % throttle_delay)
      time.sleep(throttle_delay)

  # Alert by email if necessary.
  if car_ids_out_of_bounds:
    monitor.alert('Cars outside of geofences',
                  'Cars [%s] are outside of their geofences!' %
                  ', '.join(str(car_id) for car_id in car_ids_out_of_bounds))

  if car_id_errors:
    monitor.alert('Geofence monitor errors',
                  'Geofence monitor is experiencing the following car-specific errors:\n\n%s' %
                  car_id_errors)


if __name__ == '__main__':
  start()