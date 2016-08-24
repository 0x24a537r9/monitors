# skurt
A (not so) simple interview project for Skurt, implementing an email alerting geofence monitor for their cars.

## Setup
In order to run `geofence_monitor.py`, you'll need to set a few things up first.

1. First, you will need to clone the repo with `git clone https://github.com/x2y/skurt.git`.
2. I'm using [Shapely](https://github.com/Toblerity/Shapely) for its geofencing capabilities. It depends on GEOS for the core computations so, per their GitHub, you should run `sudo apt-get install libgeos-dev` to install the C library. This must be done before the next step.
3. Assuming you already have [pip](https://pypi.python.org/pypi/pip) and Python 2.7 installed, you can simply run `pip install -r pip-packages.txt` to download the necessary packages. If you're not familiar with [virtualenv](https://pypi.python.org/pypi/virtualenv) and [virtualenvwrapper](https://pypi.python.org/pypi/virtualenvwrapper), I highly recommend using them to isolate these packages, per [The Hitchhiker's Guide to Python](http://docs.python-guide.org/en/latest/dev/virtualenvs/).

## Use
The geofencing monitor runs as a very simple [Flask](http://flask.pocoo.org/) HTTP server that provides a number of useful endpoints in addition to the core geofencing polling behavior:

| *Route*         | *Function* |
|-----------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `/`             | The default route, providing basic access to the current alerting/silencing status, as well as the day's event log.|
| `/silence`      | Silences any alerts by temporarily suspending polling. Silences 1 hour by default, configured with the `duration` query param using basic time strings such as `30s`, `10m15s`, `5h`, and `1d12h`. For example, `GET`ting `/silence?duration=1h30m` will silence the monitor for exactly 1 hour and 30 minutes. |
| `/unsilence`    | Unsilences any alerts by immediately resuming standard polling.|
| `/ok`           | Simply returns "ok" if the server is up. Used by `ok_monitor.py` to ensure that the monitor itself is up and running.|
| `/killkillkill` | Kills the server and monitor.|

Simply run `python geofence_monitor.py` to see its command-line options (powered by Python's `argparse` module). At minimum, it expects at least one car ID range, specified as either a single integer (e.g.  `3`) or a range (e.g. `1-11). To test its basic functionality in an accelerated timescale, I suggest running with:

    python geofence_monitor.py 1 --max_query_qps=1 --poll_period_s=10 --min_poll_padding_period_s=0

Remember to use the [http://localhost:5000/killkillkill](http://localhost:5000/killkillkill) to kill the server.

## Explanation
I know this repo is significantly overengineered for the task of an interview question, but it was a fun exercise, and I've needed this kind of monitoring framework for my own projects anyway, so it was a good chance to kill two birds with one stone. That said, if you'd like to see what I would've created with less time available to me, check out the code at some of my [earlier commits](https://github.com/x2y/skurt/blob/8129c30419d83f67cf64426a2bf6f8511ba4eb9f/geofence_monitor.py).

`geofence_monitor.py` is the main monitoring script, extending the behavior of the more generic, reusable `polling_monitor.py` module. Since I decided to treat this exercise as though this were being used for a real production service, I've added full Google-level logging (see the `*.log` files produced upon run), unit tests, and a separate monitor, `ok_monitor.py` designed to be run on another machine to ensure that the geofencing monitor is itself up and running (this kind of metamonitoring is standard at Google for production services).

Beyond what I've implemented, I would recommend modifying the car status endpoint to accept multiple car ids to minimize the number of HTTP requests sent. And, depending on the number of car statuses I would need to monitor, I might also consider making the `poll()` function multithreaded and/or asynchronous (although that probably would've been easier with Node.js).