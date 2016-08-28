import ok_monitor
import mock
import mocks
import monitor
import requests
import StringIO
import unittest


OK_RESPONSE = requests.Response()
OK_RESPONSE.status_code = 200
OK_RESPONSE.raw = StringIO.StringIO('ok')

SERVER_ERROR_RESPONSE = requests.Response()
SERVER_ERROR_RESPONSE.status_code = 500
SERVER_ERROR_RESPONSE.raw = StringIO.StringIO('server error')

NOT_OK_RESPONSE = requests.Response()
NOT_OK_RESPONSE.status_code = 200
NOT_OK_RESPONSE.raw = StringIO.StringIO('unknown error')



class OkMonitorTest(unittest.TestCase):
  def setUp(self):
    ok_monitor.server.config['TESTING'] = True
    self.server = ok_monitor.server.test_client()
    mock.patch('threading.Timer', mocks.MockTimer).start()

  def tearDown(self):
    self.server = None
    mock.patch.stopall()
    monitor.reset()

  def test_parse_args_without_server_url(self):
    with self.assertRaises(SystemExit) as e:
      ok_monitor.start([])
    self.assertEqual(e.exception.code, 2)

  def test_parse_args_defaults(self):
    ok_monitor.start(['http://localhost:5000'])
    
    self.assertEqual(monitor.args.server_url, 'http://localhost:5000')
    self.assertEqual(monitor.args.ok_timeout_s, 10.0)

  def test_parse_args_with_server_url_and_args(self):
    ok_monitor.start(['http://localhost:5000', '--ok_timeout_s=5'])

    self.assertEqual(monitor.args.server_url, 'http://localhost:5000')
    self.assertEqual(monitor.args.ok_timeout_s, 5.0)

  def test_polling_with_server_timing_out(self):
    def time_out(url, timeout=999):
      raise requests.exceptions.Timeout('Request timed out')

    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', side_effect=time_out) as mock_get:
        ok_monitor.start(['http://localhost:5000', '--ok_timeout_s=5'])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://localhost:5000/ok', timeout=5.0)

      mock_alert.assert_called_once_with(
          'http://localhost:5000 is timing out',
          'Request for "http://localhost:5000/ok" timed out after 5.0s.')

  def test_polling_with_server_unreachable(self):
    def time_out(url, timeout=999):
      raise Exception('Failed to establish a new connection')

    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', side_effect=time_out) as mock_get:
        ok_monitor.start(['http://localhost:5000', '--ok_timeout_s=5'])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://localhost:5000/ok', timeout=5.0)

      mock_alert.assert_called_once_with(
          'http://localhost:5000 is unreachable',
          '"http://localhost:5000/ok" could not be reached.')

  def test_polling_with_server_error(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=SERVER_ERROR_RESPONSE) as mock_get:
        ok_monitor.start(['http://localhost:5000', '--ok_timeout_s=5'])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://localhost:5000/ok', timeout=5.0)

      mock_alert.assert_called_once_with(
          'http://localhost:5000 is not ok',
          'Received 500 HTTP code from "http://localhost:5000/ok" with unexpected response: '
          '"server error"')

  def test_polling_with_unknown_error(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=NOT_OK_RESPONSE) as mock_get:
        ok_monitor.start(['http://localhost:5000', '--ok_timeout_s=5'])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://localhost:5000/ok', timeout=5.0)

      mock_alert.assert_called_once_with(
          'http://localhost:5000 is not ok',
          'Received 200 HTTP code from "http://localhost:5000/ok" with unexpected response: '
          '"unknown error"')

  def test_polling_ok(self):
    with mock.patch('monitor.alert') as mock_alert:
      with mock.patch('requests.get', return_value=OK_RESPONSE) as mock_get:
        ok_monitor.start(['http://localhost:5000', '--ok_timeout_s=5'])

        monitor.poll_timer.mock_tick(1.0)
        mock_get.assert_called_once_with('http://localhost:5000/ok', timeout=5.0)

      mock_alert.assert_not_called()


if __name__ == '__main__':
  unittest.main()