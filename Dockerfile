FROM python:3.8

RUN mkdir -p /app
WORKDIR /app

COPY requirements.txt /app
RUN pip install -r requirements.txt
RUN pip install requests

ADD . /app
RUN python setup.py install
