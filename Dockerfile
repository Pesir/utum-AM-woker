FROM python:3-slim

RUN pip3 install prometheus_client PyYAML paramiko

ADD ./am-worker.py /
ADD ./task-modules /

CMD [ "python3", "./am-worker.py", "/etc/am-worker/config"]
