import geofence_monitor
import io
import mock
import mocks
import monitor
import re
import requests
import time
import unittest


CAR_NEGATIVE_1_404_RESPONSE = requests.Response()
CAR_NEGATIVE_1_404_RESPONSE.status_code = 404

CAR_0_NO_COORDINATES_RESPONSE = requests.Response()
CAR_0_NO_COORDINATES_RESPONSE.status_code = 200
CAR_0_NO_COORDINATES_RESPONSE.raw = io.BytesIO(b'''
    {
      "type": "FeatureCollection",
      "features": [{
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[
            [-118.5, 34.0],
            [-118.5, 34.1],
            [-118.3, 34.1],
            [-118.3, 34.0],
            [-118.5, 34.0]
          ]]
        },
        "properties": {"name": "Los Angeles"}
      }]
    }''')

CAR_1_INSIDE_GEOFENCE_RESPONSE = requests.Response()
CAR_1_INSIDE_GEOFENCE_RESPONSE.status_code = 200
CAR_1_INSIDE_GEOFENCE_RESPONSE.raw = io.BytesIO(b'''
    {
      "type": "FeatureCollection",
      "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-118.4, 34.05]},
        "properties": {"id": 1, "description": "In Los Angeles geofence"}
      }, {
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[
            [-118.5, 34.0],
            [-118.5, 34.1],
            [-118.3, 34.1],
            [-118.3, 34.0],
            [-118.5, 34.0]
          ]]
        },
        "properties": {"name": "Los Angeles"}
      }]
    }''')

CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE = requests.Response()
CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE.status_code = 200
CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE.raw = io.BytesIO(b'''
    {
      "type": "FeatureCollection",
      "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-118.45, 34.075]},
        "properties": {"id": 2, "description": "In Los Angeles geofence"}
      }, {
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[
            [-122.5, 37.7],
            [-122.5, 37.8],
            [-122.4, 37.8],
            [-122.4, 37.7],
            [-122.5, 37.7]
          ]]
        },
        "properties": {"name": "San Francisco"}
      }, {
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[
            [-118.5, 34.0],
            [-118.5, 34.1],
            [-118.3, 34.1],
            [-118.3, 34.0],
            [-118.5, 34.0]
          ]]
        },
        "properties": {"name": "Los Angeles"}
      }]
    }''')

CAR_3_OUTSIDE_ITS_GEOFENCES_RESPONSE = requests.Response()
CAR_3_OUTSIDE_ITS_GEOFENCES_RESPONSE.status_code = 200
CAR_3_OUTSIDE_ITS_GEOFENCES_RESPONSE.raw = io.BytesIO(b'''
    {
      "type": "FeatureCollection",
      "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-73.98, 40.76]},
        "properties": {"id": 2, "description": "In New York City, outside geofences"}
      }, {
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[
            [-122.5, 37.7],
            [-122.5, 37.8],
            [-122.4, 37.8],
            [-122.4, 37.7],
            [-122.5, 37.7]
          ]]
        },
        "properties": {"name": "San Francisco"}
      }, {
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[
            [-118.5, 34.0],
            [-118.5, 34.1],
            [-118.3, 34.1],
            [-118.3, 34.0],
            [-118.5, 34.0]
          ]]
        },
        "properties": {"name": "Los Angeles"}
      }]
    }''')



class GeofenceMonitorTest(unittest.TestCase):
  def setUp(self):
    geofence_monitor.server.config['TESTING'] = True
    self.server = geofence_monitor.server.test_client()
    mock.patch('threading.Timer', mocks.MockTimer).start()

  def tearDown(self):
    self.server = None
    mock.patch.stopall()
    monitor.reset()

  def test_parse_args_without_car_ids(self):
    with self.assertRaises(SystemExit) as e:
      geofence_monitor.start([])
    self.assertEqual(e.exception.code, 2)

  def test_parse_args_defaults(self):
    geofence_monitor.start(['1', 'http://test.com'])

    self.assertEqual(monitor.args.car_ids, [1])
    self.assertEqual(monitor.args.car_status_url,
                     'http://skurt-interview-api.herokuapp.com/carStatus/%s')
    self.assertEqual(monitor.args.query_delay_s, 1.0)

  def test_parse_args_with_complex_args(self):
    geofence_monitor.start([
      '1-11', '13', '15-16',
      'http://test.com',
      '--car_status_url=http://test.com/carStatus/%s',
      '--max_query_qps=2.0',
    ])

    self.assertEqual(monitor.args.car_ids, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 16])
    self.assertEqual(monitor.args.car_status_url, 'http://test.com/carStatus/%s')
    self.assertEqual(monitor.args.query_delay_s, 0.5)

  def test_parse_args_with_overlapping_car_id_ranges(self):
    geofence_monitor.start([
      '5-10', '1-7', '3',
      'http://test.com',
      '--car_status_url=http://test.com/carStatus/%s',
      '--max_query_qps=2.0',
    ])

    self.assertEqual(monitor.args.car_ids, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    self.assertEqual(monitor.args.car_status_url, 'http://test.com/carStatus/%s')
    self.assertEqual(monitor.args.query_delay_s, 0.5)

  def test_polling_one_car_that_times_out(self):
    def time_out(url, timeout=999):
      raise requests.exceptions.Timeout('Request timed out')

    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', side_effect=time_out) as mock_get:
        geofence_monitor.start([
          '-2',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://test.com/carStatus/-2', timeout=10)

      mock_alert.assert_called_once_with('Geofence monitor errors', 'geofence_monitor_errors',
                                         {'car_errors': [(-2, 'FETCH_TIMED_OUT')]})

  def test_polling_one_car_with_404_response(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=CAR_NEGATIVE_1_404_RESPONSE) as mock_get:
        geofence_monitor.start([
          '-1',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://test.com/carStatus/-1', timeout=10)

      mock_alert.assert_called_once_with('Geofence monitor errors', 'geofence_monitor_errors',
                                         {'car_errors': [(-1, 'INVALID_FETCH_RESPONSE')]})

  def test_polling_one_car_with_no_coordinates(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=CAR_0_NO_COORDINATES_RESPONSE) as mock_get:
        geofence_monitor.start([
          '0',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://test.com/carStatus/0', timeout=10)

      mock_alert.assert_called_once_with('Geofence monitor errors', 'geofence_monitor_errors',
                                         {'car_errors': [(0, 'NO_CAR_COORDS')]})

  def test_polling_one_inside_geofence(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=CAR_1_INSIDE_GEOFENCE_RESPONSE) as mock_get:
        geofence_monitor.start([
          '1',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://test.com/carStatus/1', timeout=10)
        
      mock_alert.assert_not_called()

  def test_polling_one_inside_its_second_geofence(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE) as mock_get:
        geofence_monitor.start([
          '2',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://test.com/carStatus/2', timeout=10)

      mock_alert.assert_not_called()

  def test_polling_one_outside_its_geofences(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=CAR_3_OUTSIDE_ITS_GEOFENCES_RESPONSE) as mock_get:
        geofence_monitor.start([
          '3',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--google_maps_api_key=1234567890',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://test.com/carStatus/3', timeout=10)

      mock_alert.assert_called_once_with(
          'Cars outside of geofences',
          'geofence_monitor_geofence',
          {'car_coords': [(3, [-73.98, 40.76])], 'google_maps_api_key': '1234567890'})

  def test_polling_all_inside_geofences(self):
    def mock_get_response(url, timeout=999):
      return {
        '1': CAR_1_INSIDE_GEOFENCE_RESPONSE,
        '2': CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE,
      }[re.search(r'-?\d+$', url).group()]

    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', side_effect=mock_get_response) as mock_get:
        geofence_monitor.start([
          '1-2',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_has_calls([
          mock.call('http://test.com/carStatus/1', timeout=10),
          mock.call('http://test.com/carStatus/2', timeout=10),
        ])
        self.assertEqual(mock_get.call_count, 2)
      
      mock_alert.assert_not_called()

  def test_polling_some_inside_some_outside_their_geofences(self):
    def mock_get_response(url, timeout=999):
      return {
        '1': CAR_1_INSIDE_GEOFENCE_RESPONSE,
        '2': CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE,
        '3': CAR_3_OUTSIDE_ITS_GEOFENCES_RESPONSE,
      }[re.search(r'-?\d+$', url).group()]

    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', side_effect=mock_get_response) as mock_get:
        geofence_monitor.start([
          '1-3',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--google_maps_api_key=1234567890',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_has_calls([
          mock.call('http://test.com/carStatus/1', timeout=10),
          mock.call('http://test.com/carStatus/2', timeout=10),
          mock.call('http://test.com/carStatus/3', timeout=10),
        ])
        self.assertEqual(mock_get.call_count, 3)
      
      mock_alert.assert_called_once_with(
          'Cars outside of geofences',
          'geofence_monitor_geofence',
          {'car_coords': [(3, [-73.98, 40.76])], 'google_maps_api_key': '1234567890'})

  def test_polling_triggering_both_alerts(self):
    def mock_get_response(url, timeout=999):
      if url[-2:] == '-2':
        raise requests.exceptions.Timeout('Request timed out')

      return {
        '-1': CAR_NEGATIVE_1_404_RESPONSE,
        '0': CAR_0_NO_COORDINATES_RESPONSE,
        '1': CAR_1_INSIDE_GEOFENCE_RESPONSE,
        '2': CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE,
        '3': CAR_3_OUTSIDE_ITS_GEOFENCES_RESPONSE,
      }[re.search(r'-?\d+$', url).group()]

    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', side_effect=mock_get_response) as mock_get:
        geofence_monitor.start([
          '-2', '-1', '0-3',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--google_maps_api_key=1234567890',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_has_calls([
          mock.call('http://test.com/carStatus/-2', timeout=10),
          mock.call('http://test.com/carStatus/-1', timeout=10),
          mock.call('http://test.com/carStatus/0', timeout=10),
          mock.call('http://test.com/carStatus/1', timeout=10),
          mock.call('http://test.com/carStatus/2', timeout=10),
          mock.call('http://test.com/carStatus/3', timeout=10),
        ])
        self.assertEqual(mock_get.call_count, 6)
      
      mock_alert.assert_has_calls([
        mock.call('Cars outside of geofences',
                  'geofence_monitor_geofence',
                  {'car_coords': [(3, [-73.98, 40.76])], 'google_maps_api_key': '1234567890'}),
        mock.call('Geofence monitor errors', 'geofence_monitor_errors',
                  {'car_errors': [
                    (-2, 'FETCH_TIMED_OUT'),
                    (-1, 'INVALID_FETCH_RESPONSE'),
                    (0, 'NO_CAR_COORDS')
                  ]}),
      ], any_order=True)

  def test_polling_with_duplicate_car_ids(self):
    def mock_get_response(url, timeout=999):
      return {
        '1': CAR_1_INSIDE_GEOFENCE_RESPONSE,
        '2': CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE,
      }[re.search(r'-?\d+$', url).group()]

    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', side_effect=mock_get_response) as mock_get:
        geofence_monitor.start([
          '1-2', '1', '2',
          'http://test.com',
          '--car_status_url=http://test.com/carStatus/%s',
          '--max_query_qps=2.0',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=0',
        ])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_has_calls([
          mock.call('http://test.com/carStatus/1', timeout=10),
          mock.call('http://test.com/carStatus/2', timeout=10),
        ])
        # Assert that it's only making two requests.
        self.assertEqual(mock_get.call_count, 2)

      mock_alert.assert_not_called()

  def test_polling_request_throttling(self):
    request_times = []
      
    def mock_get_response(url, timeout=999):
      request_times.append(time.time())
      time.sleep(0.1)
      return {
        '1': CAR_1_INSIDE_GEOFENCE_RESPONSE,
        '2': CAR_2_INSIDE_SECOND_GEOFENCE_RESPONSE,
      }[re.search(r'-?\d+$', url).group()]

    with mock.patch('requests.get', side_effect=mock_get_response) as mock_get:
      geofence_monitor.start([
        '1-2',
        'http://test.com',
        '--car_status_url=http://test.com/carStatus/%s',
        '--max_query_qps=2.0',
        '--poll_period_s=10',
        '--min_poll_padding_period_s=0',
      ])

      monitor.poll_timer.mock_tick(1.0)
      mock_get.assert_has_calls([
        mock.call('http://test.com/carStatus/1', timeout=10),
        mock.call('http://test.com/carStatus/2', timeout=10),
      ])
      self.assertEqual(mock_get.call_count, 2)

    self.assertTrue(request_times[1] - request_times[0] >= 0.5)


if __name__ == '__main__':
  unittest.main()