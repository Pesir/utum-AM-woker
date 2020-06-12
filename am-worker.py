import os
import argparse
import json
import subprocess
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from json import JSONDecodeError
from time import sleep
import logging
import signal

from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, Gauge
from prometheus_client.metrics_core import GaugeMetricFamily, CounterMetricFamily
from importlib import import_module

import yaml

class EXECUTE_COMMAND(BaseHTTPRequestHandler):
    calls = {}
    failed_calls = {}
    failed_task_starts = 0
    config = None
    def __init__(self, request, client_address, server):
        super().__init__(request, client_address, server)

    def _set_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    @staticmethod
    def pre_load_modules():
        logging.info("preloading all modules and installing all required dependencies")
        for _,task in EXECUTE_COMMAND.config["task"].items():
            module = task.get('required_modules')
            if not module is None:
                for x in module:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", x])
                logging.info("installed module: %s"% x)
    def do_POST(self):
        content_length = int(self.headers['Content-Length']) # <--- Gets the size of data
        post_data = self.rfile.read(content_length)# <--- Gets the data itself
        data = None
        try:
            data = json.loads(post_data)
        except JSONDecodeError as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write("Error \n:  {}".format(e.args[0]).encode('utf-8'))
            return
        for alert in data['alerts']:
            labels = alert.get("labels")
            task_in_alert = labels.get("task")

            if not task_in_alert is None:
                task_in_config = EXECUTE_COMMAND.config.get("task",{}).get(task_in_alert)
                if not task_in_config is None:
                    try:
                        success = 0
                        if 'command' in task_in_config and 'python-file' in task_in_config:
                            logging.error("command and python file defined in task %s" % task_in_alert)
                        elif 'command' in task_in_config:
                            os.system(task_in_config['command'])
                        elif 'python-file' in task_in_config:
                            module = task_in_config['python-file']
                            if module.endswith(".py"):
                                module = module[:-3]
                            path = os.path.split(module)
                            sys.path.insert(1,path[0])
                            mod = import_module(path[1])
                            execute = getattr(mod, "execute")
                            params = {}
                            params.update(alert['labels'])
                            extralabels = task_in_config.get("extralabels")
                            if not extralabels is None:
                                if "configfile" in extralabels:
                                    if not os.path.isabs(extralabels.get("configfile")):
                                        new_path = os.path.join(path[0],extralabels.get("configfile"))
                                        extralabels["configfile"] = new_path
                                params.update(extralabels)
                            logging.info("Execute task: %s" % task_in_alert)
                            success = execute(**params)
                        if not task_in_alert in EXECUTE_COMMAND.calls:
                            EXECUTE_COMMAND.calls[task_in_alert] = 0
                        if not task_in_alert in EXECUTE_COMMAND.failed_calls:
                            EXECUTE_COMMAND.failed_calls[task_in_alert] = 0
                        if success != -1:
                            EXECUTE_COMMAND.calls[task_in_alert] += 1
                            logging.info("Successfully performed : %s" % task_in_alert)
                        else:
                            logging.info("Failed to perform : %s" % task_in_alert)
                            EXECUTE_COMMAND.failed_calls[task_in_alert] += 1
                    except Exception as e:
                        traceback.print_exc(file=sys.stdout)
                        EXECUTE_COMMAND.failed_task_starts += 1
                        logging.error(e)
        self._set_response()

class CustomCollector(object):
    config = None
    service = None
    def __init__(self, c):
        self.config = c

    def collect(self):
        #metric_desc = (config["metrics"][k]).get("description", "no Description for query")
        a = CounterMetricFamily(name="failed_calls", documentation="number of failed tasks",labels=[])
        a.add_metric(value=str(EXECUTE_COMMAND.failed_task_starts), labels=[])
        f = CounterMetricFamily(name="am_alert_failed_calls",
                                documentation="all failed calls",labels=["command_name"])
        for key,value in EXECUTE_COMMAND.failed_calls.items():
            f.add_metric(value=str(value),labels=[key])
        yield f

        g = CounterMetricFamily(name="am_alert_calls",
                                documentation="all successful calls",labels=["command_name"])
        for key,value in EXECUTE_COMMAND.calls.items():
            g.add_metric(value=str(value),labels=[key])
        yield g


parser = argparse.ArgumentParser()
parser.add_argument("config", help="path of the config file")
parser.add_argument("-v",dest="verbose",default=False,action='store_true', help="enable verbose logging")

args = parser.parse_args()

if args.verbose :
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)

config = None

with open(args.config, 'r') as stream:
    try:
        config = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        logging.error("failed to load config")
        logging.error(exc)
        exit(-1)

logging.debug("loaded yaml config")


logging.debug("Starting web server")

collector = CustomCollector(config)

REGISTRY.register(collector)

start_http_server(int(config.get("prom_port","9455")))
server_address = ('0.0.0.0', config["port_am"])

EXECUTE_COMMAND.config = config
EXECUTE_COMMAND.pre_load_modules()
httpd = HTTPServer(server_address, EXECUTE_COMMAND)

try:
    httpd.serve_forever()
except KeyboardInterrupt:
    pass


logging.info('Starting httpd...\n')

def exitExporter(signum, frame):
    logging.info("Exit am actor")
    exit(0)

signal.signal(signal.SIGTERM, exitExporter)
while True:
    sleep(100)