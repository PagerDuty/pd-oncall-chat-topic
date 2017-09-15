#!/usr/bin/env python

import os
import datetime
from botocore.vendored import requests
import boto3

API_KEY = boto3.client('ssm').get_parameters(
        Names=[os.environ['API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']

headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=API_KEY)
        }

# Get the Current User on-call for a given schedule
def get_user(schedule_id):
    global headers
    url = 'https://api.pagerduty.com/schedules/{0}/users'.format(
        schedule_id
    )
    # This value should be less than the running interval
    t = datetime.datetime.now() - datetime.timedelta(minutes=1)
    payload = {}
    payload['since'] = t.isoformat()
    payload['until'] = datetime.datetime.now().isoformat()
    r = requests.get(url, headers=headers, params=payload)
    return r.json()['users'][0]['name']

def handler(event, context):
    print(event)
    print(context)
    return get_user('P31BKVS')

if __name__ == '__main__':
    get_user('P31BKVS')
