#!/usr/bin/env python

import os
import datetime
import json
from botocore.vendored import requests
import boto3

# Fetch the PD API token from API_KEY_NAME key in SSM
API_KEY = boto3.client('ssm').get_parameters(
        Names=[os.environ['API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']


# Get the Current User on-call for a given schedule
def get_user(schedule_id):
    global API_KEY

    headers = {
            'Accept': 'application/vnd.pagerduty+json;version=2',
            'Authorization': 'Token token={token}'.format(token=API_KEY)
            }
    url = 'https://api.pagerduty.com/schedules/{0}/users'.format(
        schedule_id
    )
    # This value should be less than the running interval
    t = datetime.datetime.now() - datetime.timedelta(minutes=1)
    payload = {}
    payload['since'] = t.isoformat()
    payload['until'] = datetime.datetime.now().isoformat()
    r = requests.get(url, headers=headers, params=payload)
    try:
        return r.json()['users'][0]['name']
    except KeyError:
        print(r.status_code)
        print(r.json())
        return None

def handler(event, context):
    print(event)
    configset = json.load(open('config.json'))
    for i in configset.keys():
        print("Operating on {}".format(i))
        print(configset[i])
        if 'schedule' in configset[i]:
            u = get_user(configset[i]['schedule'])
            print(u)

if __name__ == '__main__':
    get_user('P31BKVS')
