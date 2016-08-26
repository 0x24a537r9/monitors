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