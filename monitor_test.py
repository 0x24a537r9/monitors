import io
import logging
import mock
import mocks
import monitor
import re
import time
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
    monitor.parse_args('Test monitor', 'Test description', [], ['http://test.com'])

    self.assertEqual(monitor.args.alert_emails, ['Cameron Behar <0x24a537r9@gmail.com>'])
    self.assertEqual(monitor.args.monitor_email,
                     'Test monitor <engineering+test_monitor@skurt.com>')
    self.assertEqual(monitor.args.poll_period_s, 300)
    self.assertEqual(monitor.args.min_poll_padding_period_s, 10)
    self.assertEqual(monitor.args.mailgun_messages_url,
                     'https://api.mailgun.net/v3/sandboxf3f15ea9e4c743199c24cb3b628208c0.mailgun'
                     '.org/messages')
    self.assertEqual(monitor.args.mailgun_api_key, '')
    self.assertEqual(monitor.args.port, 5000)
    self.assertEqual(monitor.args.log_file_prefix, 'test_monitor')
    self.assertEqual(monitor.args.log_level, logging.INFO)

  def test_parse_args_with_complex_args(self):
    monitor.parse_args('Test monitor', 'Test description', [], [
      'http://test.com',
      '--alert_emails=test1@test.com,test2@test.com',
      '--monitor_email=other_monitor@test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=0',
      '--mailgun_messages_url=http://test.com/send_email',
      '--mailgun_api_key=123456789',
      '--port=8080',
      '--log_file_prefix=other_monitor',
      '--log=DEBUG',
    ])

    self.assertEqual(monitor.args.alert_emails, ['test1@test.com', 'test2@test.com'])
    self.assertEqual(monitor.args.monitor_email, 'other_monitor@test.com')
    self.assertEqual(monitor.args.poll_period_s, 10.0)
    self.assertEqual(monitor.args.min_poll_padding_period_s, 0.0)
    self.assertEqual(monitor.args.mailgun_messages_url, 'http://test.com/send_email')
    self.assertEqual(monitor.args.mailgun_api_key, '123456789')
    self.assertEqual(monitor.args.port, 8080)
    self.assertEqual(monitor.args.log_file_prefix, 'other_monitor')
    self.assertEqual(monitor.args.log_level, logging.DEBUG)

  def test_parse_args_with_additional_arg_defs(self):
    monitor.parse_args('Test monitor', 'Test description', [{
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
      'http://test.com',
      '--arg_a=non-default-a',
      '--arg_b=1.618',
    ])

    self.assertEqual(monitor.args.arg_a, 'non-default-a')
    self.assertEqual(monitor.args.renamed_arg_b, 1.618)
    self.assertEqual(monitor.args.arg_c, 'default')

  def test_polling_with_no_poll_fns(self):
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
      'http://test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
    ])
    monitor.start()

    monitor.poll_timer.mock_tick(0.5)

    with self.assertRaises(NotImplementedError):
      monitor.poll_timer.mock_tick(0.5)

  def test_polling_with_one_poll_fn(self):
    poll = mock.Mock()
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
      'http://test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
    ])
    monitor.start(poll)

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

  def test_polling_with_multiple_poll_fns(self):
    poll_0, poll_1 = mock.Mock(), mock.Mock()
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
      'http://test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
    ])
    monitor.start([poll_0, poll_1])

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
    
      with mock.patch('requests.post') as mock_post:
        monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
          'http://test.com',
          '--alert_emails=test1@test.com,test2@test.com',
          '--monitor_email=other_monitor@test.com',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=5',
          '--mailgun_messages_url=http://test.com/send_email',
          '--mailgun_api_key=1234567890',
        ])
        monitor.start(slow_operation)

        monitor.poll_timer.mock_tick(1)
        mock_post.assert_called_once_with(
            'http://test.com/send_email',
            auth=('api', '1234567890'),
            data={
              'from': 'other_monitor@test.com',
              'to': 'test1@test.com, test2@test.com',
              'subject': '[ALERT] Test monitor is overrunning',
              'html': mock.ANY,
            },
            timeout=10)
        filtered_html = re.sub(r'\s+', ' ', mock_post.call_args[1]['data']['html'])
        self.assertIn('the polling method is taking 5.0s longer than the polling period',
                      filtered_html)

  def test_polling_in_danger_of_overrunning_alert(self):
    mock_time = mocks.MockTime()
    with mock.patch('time.time', new=mock_time.time):
      def slow_operation():
        mock_time.mock_tick(8)

      with mock.patch('requests.post') as mock_post:
        monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
          'http://test.com',
          '--alert_emails=test1@test.com,test2@test.com',
          '--monitor_email=other_monitor@test.com',
          '--poll_period_s=10',
          '--min_poll_padding_period_s=5',
          '--mailgun_messages_url=http://test.com/send_email',
          '--mailgun_api_key=1234567890',
        ])
        monitor.start(slow_operation)

        monitor.poll_timer.mock_tick(1)
        mock_post.assert_called_once_with(
            'http://test.com/send_email',
            auth=('api', '1234567890'),
            data={
              'from': 'other_monitor@test.com',
              'to': 'test1@test.com, test2@test.com',
              'subject': '[ALERT] Test monitor is in danger of overrunning',
              'html': mock.ANY,
            },
            timeout=10)
        filtered_html = re.sub(r'\s+', ' ', mock_post.call_args[1]['data']['html'])
        self.assertIn('the polling method is taking only 2.0s less than the polling period',
                      filtered_html)

  def test_polling_unhandled_exception_alert(self):
    def unhandled_exception():
      raise Exception('unhandled exception')
  
    with mock.patch('requests.post') as mock_post:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
        'http://test.com',
        '--alert_emails=test1@test.com,test2@test.com',
        '--monitor_email=other_monitor@test.com',
        '--poll_period_s=10',
        '--min_poll_padding_period_s=5',
        '--mailgun_messages_url=http://test.com/send_email',
        '--mailgun_api_key=1234567890',
      ])
      monitor.start(unhandled_exception)

      monitor.poll_timer.mock_tick(1)
      mock_post.assert_called_once_with(
          'http://test.com/send_email',
          auth=('api', '1234567890'),
          data={
            'from': 'other_monitor@test.com',
            'to': 'test1@test.com, test2@test.com',
            'subject': '[ALERT] Test monitor encountered an exception',
            'html': mock.ANY,
          },
          timeout=10)

      # We can't test the actual email text here because it contains traceback line numbers, which
      # are liable to change with modifications to this file and monitor.py. First we'll need to
      # filter the HTML to make it more stable over time.
      filtered_html = mock_post.call_args[1]['data']['html']
      filtered_html = re.sub(r'\s+', ' ', filtered_html)
      filtered_html = re.sub(r'line\s\d+', 'line #', filtered_html)
      filtered_html = re.sub(r'File\s&#34;[^&]+&#34;', 'File &#34;/home/script.py&#34;', filtered_html)
      self.assertIn('Unhandled exception in Test monitor\'s poll function:', filtered_html)
      self.assertIn('Traceback (most recent call last): '
                    'File &#34;/home/script.py&#34;, line #, in poll '
                    'poll_fn() '
                    'File &#34;/home/script.py&#34;, line #, in unhandled_exception '
                    'raise Exception(&#39;unhandled exception&#39;) '
                    'Exception: unhandled exception',
                    filtered_html)


  def test_alert(self):
    with mock.patch('requests.post') as mock_post:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
        'http://test.com',
        '--alert_emails=test1@test.com,test2@test.com',
        '--monitor_email=other_monitor@test.com',
        '--mailgun_messages_url=http://test.com/send_email',
        '--mailgun_api_key=1234567890',
      ])
      monitor.start(lambda: None)

      monitor.alert('Test subject', 'test', {'a': 'string'})

      mock_post.assert_called_once_with(
          'http://test.com/send_email',
          auth=('api', '1234567890'),
          data={
            'from': 'other_monitor@test.com',
            'to': 'test1@test.com, test2@test.com',
            'subject': '[ALERT] Test subject',
            'html': mock.ANY,
          },
          timeout=10)
      filtered_html = re.sub(r'\s+', ' ', mock_post.call_args[1]['data']['html'])
      self.assertIn('Test message with string replacement', filtered_html)
      self.assertIn('Check on this monitor\'s status', filtered_html)
      self.assertIn('Silence this alert for', filtered_html)
      self.assertIn('Unsilence this alert', filtered_html)

  def test_render_page(self):
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                       raw_args=['http://test.com'])

    with monitor.server.app_context():
      html = monitor.render_page('error', 'Error', {'message': 'message', 'traceback': 'traceback'})
      filtered_html = re.sub(r'\s+', ' ', html)
      self.assertEquals(
          filtered_html,
          '<!DOCTYPE html> <html> <head> <title>Test monitor - Error</title> </head> <body> '
          'message <pre>traceback</pre> </body> </html>')

  def test_silence(self):
    poll = mock.Mock()
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
      'http://test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
    ])
    monitor.start(poll)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    monitor.silence(60 * 60)

    monitor.poll_timer.mock_tick(60 * 60 - 5)
    monitor.silence_timer.mock_tick(60 * 60 - 5)
    poll.assert_not_called()

    monitor.poll_timer.mock_tick(5)
    monitor.silence_timer.mock_tick(5)
    poll.assert_called_once()

  def test_unsilence_when_silenced(self):
    poll = mock.Mock()
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
      'http://test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
    ])
    monitor.start(poll)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    monitor.silence(60 * 60)

    monitor.poll_timer.mock_tick(30 * 60)
    monitor.silence_timer.mock_tick(30 * 60)
    poll.assert_not_called()

    self.assertTrue(monitor.unsilence())
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

  def test_unsilence_when_already_unsilenced(self):
    poll = mock.Mock()
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
      'http://test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
    ])
    monitor.start(poll)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    self.assertFalse(monitor.unsilence())
    poll.assert_not_called()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    poll.assert_called_once()

  def test_silence_while_already_silenced_resets_timer(self):
    poll = mock.Mock()
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[], raw_args=[
      'http://test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=5',
    ])
    monitor.start(poll)

    monitor.poll_timer.mock_tick(1)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(10)
    poll.assert_called_once()

    poll.reset_mock()
    monitor.poll_timer.mock_tick(5)
    monitor.silence(60 * 60)

    monitor.poll_timer.mock_tick(30 * 60)
    monitor.silence_timer.mock_tick(30 * 60)
    poll.assert_not_called()

    monitor.silence(60 * 60)

    monitor.poll_timer.mock_tick(60 * 60 - 5)
    monitor.silence_timer.mock_tick(60 * 60 - 5)
    poll.assert_not_called()

    monitor.poll_timer.mock_tick(5)
    monitor.silence_timer.mock_tick(5)
    poll.assert_called_once()

  def test_handle_ok(self):
    response = self.server.get('/ok')
    self.assertEqual(response.data, 'ok')

  def test_handle_silence_default(self):
    with mock.patch('monitor.silence') as mock_silence:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com'])
      monitor.start(lambda: None)

      response = self.server.get('/silence')
      mock_silence.assert_called_once_with(60 * 60)
      filtered_html = re.sub(r'\s+', ' ', response.data)    
      self.assertIn('Silenced for 1h.', filtered_html)

  def test_handle_silence_with_complex_duration(self):
    with mock.patch('monitor.silence') as mock_silence:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com'])
      monitor.start(lambda: None)
      
      response = self.server.get('/silence/1h30m15s')
      mock_silence.assert_called_once_with((60 * 60) + (30 * 60) + (15))
      filtered_html = re.sub(r'\s+', ' ', response.data)    
      self.assertIn('Silenced for 1h30m15s.', filtered_html)

  def test_handle_unsilence_when_silenced(self):
    with mock.patch('monitor.unsilence', return_value=True) as mock_unsilence:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com'])
      monitor.start(lambda: None)

      monitor.silence(60 * 60)

      response = self.server.get('/unsilence')
      mock_unsilence.assert_called_once_with()
      filtered_html = re.sub(r'\s+', ' ', response.data)    
      self.assertIn('Unsilenced.', filtered_html)

  def test_handle_unsilence_when_already_unsilenced(self):
    with mock.patch('monitor.unsilence', return_value=False) as mock_unsilence:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com'])
      monitor.start(lambda: None)

      response = self.server.get('/unsilence')
      mock_unsilence.assert_called_once_with()
      filtered_html = re.sub(r'\s+', ' ', response.data)
      self.assertIn('Already unsilenced.', filtered_html)

  def test_handle_args(self):
    monitor.parse_args('Test monitor', 'Test description', [{
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
      'http://test.com',
      '--arg_a=non-default-a',
      '--arg_b=1.618',
      '--alert_emails=test1@test.com,test2@test.com',
      '--monitor_email=other_monitor@test.com',
      '--poll_period_s=10',
      '--min_poll_padding_period_s=0',
      '--mailgun_messages_url=http://test.com/send_email',
      '--mailgun_api_key=123456789',
      '--port=8080',
      '--log_file_prefix=other_monitor',
      '--log=DEBUG',
    ])

    response = self.server.get('/args')
    self.assertIn(
        '--alert_emails=[&#39;test1@test.com&#39;, &#39;test2@test.com&#39;]\n'
        '--arg_a=non-default-a\n'
        '--arg_c=default\n'
        '--log_file_prefix=other_monitor\n'
        '--log_level=10\n'
        '--mailgun_api_key=123456789\n'
        '--mailgun_messages_url=http://test.com/send_email\n'
        '--min_poll_padding_period_s=0.0\n'
        '--monitor_email=other_monitor@test.com\n'
        '--monitor_url=http://test.com\n'
        '--poll_period_s=10.0\n'
        '--port=8080\n'
        '--renamed_arg_b=1.618\n',
        response.data)

  def test_handle_logs_invalid_level(self):
    monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                       raw_args=['http://test.com'])
    monitor.start(lambda: None)

    response = self.server.get('/logs/invalid')
    filtered_html = re.sub(r'\s+', ' ', response.data)    
    self.assertIn('Invalid log level: &#34;INVALID&#34;', filtered_html)

  def test_handle_logs_default_level(self):
    with mock.patch('monitor.open', return_value=io.BytesIO(b'logs record')) as mock_open:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com', '--log_file_prefix=/tmp/test_monitor'])
      monitor.start(lambda: None)

      response = self.server.get('/logs')
      mock_open.assert_called_once_with('/tmp/test_monitor.INFO.log', 'r')
      filtered_html = re.sub(r'\s+', ' ', response.data)    
      self.assertIn('logs record', filtered_html)

  def test_handle_logs_info_level(self):
    with mock.patch('monitor.open', return_value=io.BytesIO(b'logs record')) as mock_open:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com', '--log_file_prefix=/tmp/test_monitor'])
      monitor.start(lambda: None)

      response = self.server.get('/logs/info')
      mock_open.assert_called_once_with('/tmp/test_monitor.INFO.log', 'r')
      filtered_html = re.sub(r'\s+', ' ', response.data)    
      self.assertIn('logs record', filtered_html)

  def test_handle_logs_warning_level(self):
    with mock.patch('monitor.open', return_value=io.BytesIO(b'logs record')) as mock_open:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com', '--log_file_prefix=/tmp/test_monitor'])
      monitor.start(lambda: None)

      response = self.server.get('/logs/warning')
      mock_open.assert_called_once_with('/tmp/test_monitor.WARNING.log', 'r')
      filtered_html = re.sub(r'\s+', ' ', response.data)    
      self.assertIn('logs record', filtered_html)

  def test_handle_logs_error_level(self):
    with mock.patch('monitor.open', return_value=io.BytesIO(b'logs record')) as mock_open:
      monitor.parse_args('Test monitor', 'Test description', raw_arg_defs=[],
                         raw_args=['http://test.com', '--log_file_prefix=/tmp/test_monitor'])
      monitor.start(lambda: None)

      response = self.server.get('/logs/error')
      mock_open.assert_called_once_with('/tmp/test_monitor.ERROR.log', 'r')
      filtered_html = re.sub(r'\s+', ' ', response.data)    
      self.assertIn('logs record', filtered_html)

  def test_kill_in_prod(self):
    response = self.server.get('/kill')
    self.assertEquals(response.status_code, 404)


if __name__ == '__main__':
  unittest.main()
