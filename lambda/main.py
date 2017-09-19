#!/usr/bin/env python

import os
import datetime
from botocore.vendored import requests
import boto3

# Get the Current User on-call for a given schedule
def get_user(schedule_id):
    # Fetch the PD API token from PD_API_KEY_NAME key in SSM
    PD_API_KEY = boto3.client('ssm').get_parameters(
            Names=[os.environ['PD_API_KEY_NAME']],
            WithDecryption=True)['Parameters'][0]['Value']

    headers = {
            'Accept': 'application/vnd.pagerduty+json;version=2',
            'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
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

def get_slack_topic(channel):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['channel'] = channel
    r = requests.post('https://slack.com/api/channels.info', data=payload)
    print(r.json())
    return r.json()['channel']['topic']['value']

def update_slack_topic(channel, topic):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['channel'] = channel
    payload['topic'] = topic
    r = requests.post('https://slack.com/api/channels.setTopic', data=payload)
    return r.json()

def handler(event, context):
    print(event)
    ddb = boto3.client('dynamodb')
    response = ddb.scan(
                TableName=os.environ['CONFIG_TABLE'],
                )
    for i in response['Items']:
        print("Operating on {}".format(i))
        # schedule will ALWAYS be there, it is a ddb primarykey
        schedule = i['schedule']['S']
        u = get_user(schedule)
        topic = "{} is on-call for {}".format(u, "schedule")
        if 'slack' in i.keys():
            slack = i['slack']['S']
            if u is not None:
                if get_slack_topic(slack) != topic:
                    update_slack_topic(slack, topic)
                else:
                    print("Not updating slack, topic is the same")
        elif 'hipchat' in i.keys():
            hipchat = i['hipchat']['S']
            print("HipChat is not supported yet. Ignoring this entry...")
            continue

if __name__ == '__main__':
    get_user('P31BKVS')
