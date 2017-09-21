#!/usr/bin/env python

import os
from datetime import datetime, timezone, timedelta
from botocore.vendored import requests
import boto3

# Fetch the PD API token from PD_API_KEY_NAME key in SSM
PD_API_KEY = boto3.client('ssm').get_parameters(
        Names=[os.environ['PD_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']

# Get the Current User on-call for a given schedule
def get_user(schedule_id):
    global PD_API_KEY
    headers = {
            'Accept': 'application/vnd.pagerduty+json;version=2',
            'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
            }
    normal_schedule_url = 'https://api.pagerduty.com/schedules/{0}/users'.format(
        schedule_id
    )
    override_schedule_url = 'https://api.pagerduty.com/schedules/{0}/overrides'.format(
        schedule_id
    )
    # This value should be less than the running interval
    t = datetime.now(timezone.utc) - timedelta(minutes=1)
    payload = {}
    payload['since'] = t.isoformat()
    payload['until'] = datetime.now().isoformat()
    # If there is no override, then check the schedule directly
    override = requests.get(override_schedule_url, headers=headers, params=payload)
    try:
        username = override.json()['overrides'][0]['user']['summary'] + " (Override)"
    except IndexError:
        normal = requests.get(normal_schedule_url, headers=headers, params=payload)
        username = normal.json()['users'][0]['name']
    print("Currently on call: {}".format(username))
    return username

def get_pd_schedule_name(schedule_id):
    global PD_API_KEY
    headers = {
            'Accept': 'application/vnd.pagerduty+json;version=2',
            'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
            }
    url = 'https://api.pagerduty.com/schedules/{0}'.format(
        schedule_id
    )
    r = requests.get(url, headers=headers)
    try:
        return r.json()['schedule']['name']
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

def update_slack_topic(channel, proposed_update):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['channel'] = channel

    # This is tricky to get correct
    current_full_topic = get_slack_topic(channel)
    try:
        first_part = current_full_topic.split('|')[0].strip()
        second_part = current_full_topic.split('|')[1].strip()
    except IndexError: # if there is no '|' in the topic
        first_part = "none"
        second_part = current_full_topic

    if proposed_update != first_part:
        payload['topic'] = "{} | {}".format(proposed_update, second_part)
        r = requests.post('https://slack.com/api/channels.setTopic', data=payload)
        return r.json()
    else:
        print("Not updating slack, topic is the same")
        return None


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
        username = get_user(schedule)
        topic = "{} is on-call for {}".format(username, get_pd_schedule_name(schedule))
        if 'slack' in i.keys():
            slack = i['slack']['S']
            update_slack_topic(slack, topic)
        elif 'hipchat' in i.keys():
            hipchat = i['hipchat']['S']
            print("HipChat is not supported yet. Ignoring this entry...")
            continue

if __name__ == '__main__':
    get_user('P31BKVS')
