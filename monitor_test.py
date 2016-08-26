import flask
import logging
import mock
import monitor
import unittest


class MockRequests():
  def post(self, url, auth=None, data={}):
    raise NotImplementedError('post() should be mocked out')


class MockTimer():
  def __init__(self, seconds, fn):
    self.seconds = seconds
    self.fn = fn
    self.has_started = False
    self.has_stopped = False

  def start(self):
    if self.has_started:
      raise RuntimeError('threads can only be started once')
    self.has_started = True

  def cancel(self):
    self.has_stopped = True

  def mock_tick(self, seconds):
    if not self.has_started or self.has_stopped:
      return

    self.seconds -= seconds
    if self.seconds <= 0:
      self.fn()
      self.has_stopped = True


class MockTime():
  def __init__(self):
    self.now = 0.0

  def time(self):
    return self.now

  def mock_tick(self, seconds):
    self.now += seconds


class MonitorTest(unittest.TestCase):
  def setUp(self):
    monitor.server.config['TESTING'] = True
    self.server = monitor.server.test_client()
    self.deps = monitor.Deps(requests=MockRequests(), time=MockTime(), Timer=MockTimer)

  def tearDown(self):
    self.server, self.deps = None, None
    monitor.reset()

  def test_parse_args_defaults(self):
    monitor.callbacks.append(lambda: None)
    monitor.start('Test monitor', 'Test description', [], [], self.deps)

    self.assertEqual(monitor.args.alert_emails, ['Cameron Behar <0x24a537r9@gmail.com>'])
    self.assertEqual(monitor.args.monitor_email,
                     'Test monitor <engineering+test_monitor@skurt.com>')
    self.assertEqual(monitor.args.poll_period_s, 300)
    self.assertEqual(monitor.args.min_poll_padding_period_s, 10)
    self.assertEqual(monitor.args.mailgun_messages_endpoint,
                     'https://api.mailgun.net/v3/sandboxf3f15ea9e4c743199c24cb3b628208c0.mailgun'
                     '.org/messages')
    self.assertEqual(monitor.args.mailgun_api_key, 'key-db805e58c7522624b6b6c7fbb96dcbb0')
    self.assertEqual(monitor.args.port, 5000)
    self.assertEqual(monitor.args.log_file_prefix, 'test_monitor')
    self.assertEqual(monitor.args.log_level, logging.INFO)


  def test_parse_args_with_complex_args(self):
    monitor.callbacks.append(lambda: None)
    monitor.start('Test monitor', 'Test description', [], [
      '--alert_emails=test1@test.com,test2@test.com',
      '--monitor_email=other_monitor@test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=0',
      '--mailgun_messages_endpoint=http://test.com/send_email',
      '--mailgun_api_key=123456789',
      '--port=8080',
      '--log_file_prefix=other_monitor',
      '--log=DEBUG',
    ], self.deps)

    self.assertEqual(monitor.args.alert_emails, ['test1@test.com', 'test2@test.com'])
    self.assertEqual(monitor.args.monitor_email, 'other_monitor@test.com')
    self.assertEqual(monitor.args.poll_period_s, 10.0)
    self.assertEqual(monitor.args.min_poll_padding_period_s, 0.0)
    self.assertEqual(monitor.args.mailgun_messages_endpoint, 'http://test.com/send_email')
    self.assertEqual(monitor.args.mailgun_api_key, '123456789')
    self.assertEqual(monitor.args.port, 8080)
    self.assertEqual(monitor.args.log_file_prefix, 'other_monitor')
    self.assertEqual(monitor.args.log_level, logging.DEBUG)

  def test_parse_args_with_additional_arg_defs(self):
    monitor.callbacks.append(lambda: None)
    monitor.start('Test monitor', 'Test description', [{
      'name': '--arg_a',
      'dest': 'arg_a',
      'default': 'default-a',
      'help': 'A simple string arg.',
    }, {
      'name': '--arg_b',
      'dest': 'renamed_arg_b',
      'default': 3.141,
      'type': float,
      'help': 'The simple float arg.',
    }, {
      'name': '--arg_c',
      'dest': 'arg_c',
      'default': 'default',
      'help': 'The simple default arg.',
    }], [
      '--arg_a=non-default-a',
      '--arg_b=1.618'
    ], self.deps)

    self.assertEqual(monitor.args.arg_a, 'non-default-a')
    self.assertEqual(monitor.args.renamed_arg_b, 1.618)
    self.assertEqual(monitor.args.arg_c, 'default')

  def test_polling_with_no_callbacks(self):
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    monitor.poll_timer.mock_tick(0.5)

    with self.assertRaises(NotImplementedError):
      monitor.poll_timer.mock_tick(0.5)

  def test_polling_with_one_callback(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    poll.assert_not_called()
    monitor.poll_timer.mock_tick(0.5)
    poll.assert_not_called()

    monitor.poll_timer.mock_tick(0.5)
    poll.assert_called_once()

    for i in xrange(3):
      poll.reset_mock()
      monitor.poll_timer.mock_tick(9)
      poll.assert_not_called()

      monitor.poll_timer.mock_tick(1)
      poll.assert_called_once()

  def test_polling_with_multiple_callbacks(self):
    poll_0 = mock.Mock()
    poll_1 = mock.Mock()
    monitor.callbacks.append(poll_0)
    monitor.callbacks.append(poll_1)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    poll_0.assert_not_called()
    poll_1.assert_not_called()
    monitor.poll_timer.mock_tick(0.5)
    poll_0.assert_not_called()
    poll_1.assert_not_called()

    monitor.poll_timer.mock_tick(0.5)
    poll_0.assert_called_once()
    poll_1.assert_called_once()

    for i in xrange(3):
      poll_0.reset_mock()
      poll_1.reset_mock()
      monitor.poll_timer.mock_tick(9)
      poll_0.assert_not_called()
      poll_1.assert_not_called()

      monitor.poll_timer.mock_tick(1)
      poll_0.assert_called_once()
      poll_1.assert_called_once()

  def test_polling_overrunning_alert(self):
    def slow_operation():
      self.deps.time.mock_tick(15)
    monitor.callbacks.append(slow_operation)
    self.deps.requests.post = mock.Mock()

    monitor.start('Test monitor', 'Test description', [], [
      '--alert_emails=test1@test.com,test2@test.com',
      '--monitor_email=other_monitor@test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
      '--mailgun_messages_endpoint=http://test.com/send_email',
      '--mailgun_api_key=1234567890',
    ], self.deps)

    monitor.poll_timer.mock_tick(1)
    self.deps.requests.post.assert_called_once_with(
        'http://test.com/send_email',
        auth=('api', '1234567890'),
        data={
          'from': 'other_monitor@test.com',
          'to': 'test1@test.com, test2@test.com',
          'subject': '[ALERT] Test monitor is overrunning',
          'text': 'Test monitor is unable to poll as frequently as expected because the polling '
                  'method is taking 5.0s longer than the polling period (10.0s). Either optimize '
                  'the polling method to run more quickly or configure the monitor with a longer '
                  'polling period.',
        })

  def test_polling_in_danger_of_overrunning_alert(self):
    def slow_operation():
      self.deps.time.mock_tick(8)
    monitor.callbacks.append(slow_operation)
    self.deps.requests.post = mock.Mock()

    monitor.start('Test monitor', 'Test description', [], [
      '--alert_emails=test1@test.com,test2@test.com',
      '--monitor_email=other_monitor@test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
      '--mailgun_messages_endpoint=http://test.com/send_email',
      '--mailgun_api_key=1234567890',
    ], self.deps)

    monitor.poll_timer.mock_tick(1)
    self.deps.requests.post.assert_called_once_with(
        'http://test.com/send_email',
        auth=('api', '1234567890'),
        data={
          'from': 'other_monitor@test.com',
          'to': 'test1@test.com, test2@test.com',
          'subject': '[ALERT] Test monitor is in danger of overrunning',
          'text': 'Test monitor is in danger of being unable to poll as frequently as expected '
                  'because the polling method is taking only 2.0s less than the polling period '
                  '(10.0s). Either optimize the polling method to run more quickly or configure '
                  'the monitor with a longer polling period.',
        })

  def test_alert(self):
    self.deps.requests.post = mock.Mock()
    
    monitor.start('Test monitor', 'Test description', [], [
      '--alert_emails=test1@test.com,test2@test.com',
      '--monitor_email=other_monitor@test.com',
      '--mailgun_messages_endpoint=http://test.com/send_email',
      '--mailgun_api_key=1234567890',
    ], self.deps)

    monitor.alert('Test subject', 'Test message')

    self.deps.requests.post.assert_called_once_with(
        'http://test.com/send_email',
        auth=('api', '1234567890'),
        data={
          'from': 'other_monitor@test.com',
          'to': 'test1@test.com, test2@test.com',
          'subject': '[ALERT] Test subject',
          'text': 'Test message',
        })

  def test_ok(self):
    response = self.server.get('/ok')
    self.assertEqual(response.data, 'ok')

  def test_silence_default(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    response = self.server.get('/silence')
    self.assertEqual(response.data, 'Silenced for 1h.')

    monitor.poll_timer.mock_tick(60 * 60 - 5)
    monitor.silence_timer.mock_tick(60 * 60 - 5)
    poll.assert_not_called()

    monitor.poll_timer.mock_tick(5)
    monitor.silence_timer.mock_tick(5)
    poll.assert_called_once()

  def test_silence_with_complex_duration(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    response = self.server.get('/silence/1h30m15s')
    self.assertEqual(response.data, 'Silenced for 1h30m15s.')

    monitor.poll_timer.mock_tick((60 * 60) + (30 * 60) + (15) - 5)
    monitor.silence_timer.mock_tick((60 * 60) + (30 * 60) + (15) - 5)
    poll.assert_not_called()

    monitor.poll_timer.mock_tick(5)
    monitor.silence_timer.mock_tick(5)
    poll.assert_called_once()

  def test_silence_while_already_silenced_resets_timer(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    response = self.server.get('/silence')
    self.assertEqual(response.data, 'Silenced for 1h.')

    monitor.poll_timer.mock_tick(30 * 60)
    monitor.silence_timer.mock_tick(30 * 60)
    poll.assert_not_called()

    response = self.server.get('/silence')
    self.assertEqual(response.data, 'Silenced for 1h.')

    monitor.poll_timer.mock_tick(60 * 60 - 5)
    monitor.silence_timer.mock_tick(60 * 60 - 5)
    poll.assert_not_called()

    monitor.poll_timer.mock_tick(5)
    monitor.silence_timer.mock_tick(5)
    poll.assert_called_once()

  def test_unsilence_when_silenced(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    response = self.server.get('/silence')
    self.assertEqual(response.data, 'Silenced for 1h.')

    monitor.poll_timer.mock_tick(30 * 60)
    monitor.silence_timer.mock_tick(30 * 60)
    poll.assert_not_called()

    response = self.server.get('/unsilence')
    self.assertEqual(response.data, 'Unsilenced.')
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

  def test_unsilence_when_already_unsilenced(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'], self.deps)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    response = self.server.get('/unsilence')
    self.assertEqual(response.data, 'Already unsilenced.')
    poll.assert_not_called()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    poll.assert_called_once()

  def test_kill_in_prod(self):
    response = self.server.get('/killkillkill')
    self.assertEquals(response.status_code, 404)


if __name__ == '__main__':
  unittest.main()