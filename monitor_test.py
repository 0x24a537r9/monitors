import flask
import logging
import mock
import mocks
import monitor
import unittest



class MonitorTest(unittest.TestCase):
  def setUp(self):
    monitor.server.config['TESTING'] = True
    self.server = monitor.server.test_client()
    mock.patch('threading.Timer', mocks.MockTimer).start()

  def tearDown(self):
    self.server = None
    mock.patch.stopall()
    monitor.reset()

  def test_parse_args_defaults(self):
    monitor.callbacks.append(lambda: None)
    monitor.start('Test monitor', 'Test description', [], [])

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
    ])

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
    ])

    self.assertEqual(monitor.args.arg_a, 'non-default-a')
    self.assertEqual(monitor.args.renamed_arg_b, 1.618)
    self.assertEqual(monitor.args.arg_c, 'default')

  def test_polling_with_no_callbacks(self):
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

    monitor.poll_timer.mock_tick(0.5)

    with self.assertRaises(NotImplementedError):
      monitor.poll_timer.mock_tick(0.5)

  def test_polling_with_one_callback(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

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
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

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
    mock_time = mocks.MockTime()
    with mock.patch('time.time', new=mock_time.time):
      def slow_operation():
        mock_time.mock_tick(15)
      monitor.callbacks.append(slow_operation)
    
      with mock.patch('requests.post') as mock_post:
        monitor.start('Test monitor', 'Test description', [], [
          '--alert_emails=test1@test.com,test2@test.com',
          '--monitor_email=other_monitor@test.com',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=5',
          '--mailgun_messages_endpoint=http://test.com/send_email',
          '--mailgun_api_key=1234567890',
        ])

        monitor.poll_timer.mock_tick(1)
        mock_post.assert_called_once_with(
            'http://test.com/send_email',
            auth=('api', '1234567890'),
            data={
              'from': 'other_monitor@test.com',
              'to': 'test1@test.com, test2@test.com',
              'subject': '[ALERT] Test monitor is overrunning',
              'text': 'Test monitor is unable to poll as frequently as expected because the '
                      'polling method is taking 5.0s longer than the polling period (10.0s). '
                      'Either optimize the polling method to run more quickly or configure the '
                      'monitor with a longer polling period.',
            },
            timeout=10)

  def test_polling_in_danger_of_overrunning_alert(self):
    mock_time = mocks.MockTime()
    with mock.patch('time.time', new=mock_time.time):
      def slow_operation():
        mock_time.mock_tick(8)
      monitor.callbacks.append(slow_operation)

      with mock.patch('requests.post') as mock_post:
        monitor.start('Test monitor', 'Test description', [], [
          '--alert_emails=test1@test.com,test2@test.com',
          '--monitor_email=other_monitor@test.com',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=5',
          '--mailgun_messages_endpoint=http://test.com/send_email',
          '--mailgun_api_key=1234567890',
        ])

        monitor.poll_timer.mock_tick(1)
        mock_post.assert_called_once_with(
            'http://test.com/send_email',
            auth=('api', '1234567890'),
            data={
              'from': 'other_monitor@test.com',
              'to': 'test1@test.com, test2@test.com',
              'subject': '[ALERT] Test monitor is in danger of overrunning',
              'text': 'Test monitor is in danger of being unable to poll as frequently as expected '
                      'because the polling method is taking only 2.0s less than the polling period '
                      '(10.0s). Either optimize the polling method to run more quickly or '
                      'configure the monitor with a longer polling period.'
            },
            timeout=10)

  def test_alert(self):
    with mock.patch('requests.post') as mock_post:
      monitor.start('Test monitor', 'Test description', [], [
        '--alert_emails=test1@test.com,test2@test.com',
        '--monitor_email=other_monitor@test.com',
        '--mailgun_messages_endpoint=http://test.com/send_email',
        '--mailgun_api_key=1234567890',
      ])

      monitor.alert('Test subject', 'Test message')

      mock_post.assert_called_once_with(
          'http://test.com/send_email',
          auth=('api', '1234567890'),
          data={
            'from': 'other_monitor@test.com',
            'to': 'test1@test.com, test2@test.com',
            'subject': '[ALERT] Test subject',
            'text': 'Test message',
          },
          timeout=10)

  def test_ok(self):
    response = self.server.get('/ok')
    self.assertEqual(response.data, 'ok')

  def test_silence_default(self):
    poll = mock.Mock()
    monitor.callbacks.append(poll)
    monitor.start('Test monitor', 'Test description', [],
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

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
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

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
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

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
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

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
                  ['--poll_period_s=10', '--min_poll_padding_period_s=5'])

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
    response = self.server.get('/kill')
    self.assertEquals(response.status_code, 404)


if __name__ == '__main__':
  unittest.main()