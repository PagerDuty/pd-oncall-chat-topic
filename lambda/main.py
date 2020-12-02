#!/usr/bin/env python

import os
from datetime import datetime, timezone, timedelta
import threading
import logging
import re

from botocore.vendored import requests
import boto3

# semaphore limit of 5, picked this number arbitrarily
maxthreads = 5
sema = threading.Semaphore(value=maxthreads)

logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

CHAT_USER_NOT_FOUND_RESULT = {
    'at_handle': None,
    'id': None,
    'email': None,
    'exists': False,
    'name': None
}

# Fetch the PD API token from PD_API_KEY_NAME key in SSM
PD_API_KEY = boto3.client('ssm').get_parameters(
    Names=[os.environ['PD_API_KEY_NAME']],
    WithDecryption=True)['Parameters'][0]['Value']

PD_USER_NOT_FOUND_RESULT = {
    'email': None,
    'exists': False,
    'is_override': False,
    'name': 'No one :thisisfine:'
}


# Get the Current User on-call for a given schedule
def get_pd_user(schedule_id):
    global PD_API_KEY
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    normal_url = 'https://api.pagerduty.com/schedules/{0}/users'.format(
        schedule_id
    )
    override_url = 'https://api.pagerduty.com/schedules/{0}/overrides'.format(
        schedule_id
    )
    # This value should be less than the running interval
    # It is best to use UTC for the datetime object
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=1)  # One minute ago
    payload = {}
    payload['since'] = since.isoformat()
    payload['until'] = now.isoformat()
    normal = requests.get(normal_url, headers=headers, params=payload)
    if normal.status_code == 404:
        logger.critical("ABORT: Not a valid schedule: {}".format(schedule_id))
        return False
    try:
        user = normal.json()['users'][0]
        user['exists'] = True
        user['is_override'] = False
        # Check for overrides
        # If there is *any* override, then the above username is an override
        # over the normal schedule. The problem must be approached this way
        # because the /overrides endpoint does not guarentee an order of the
        # output.
        override = requests.get(override_url, headers=headers, params=payload)
        if override.json()['overrides']:  # is not empty list
            user['is_override'] = True
    except IndexError:
        user = PD_USER_NOT_FOUND_RESULT

    logger.info("Currently on call: {}".format(user['name']))
    return user


def get_pd_schedule_name(schedule_id):
    global PD_API_KEY
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    url = 'https://api.pagerduty.com/schedules/{0}'.format(schedule_id)
    r = requests.get(url, headers=headers)
    try:
        return r.json()['schedule']['name']
    except KeyError:
        logger.debug(r.status_code)
        logger.debug(r.json())
        return None


def get_chat_user(chat_provider_name, pd_email, pd_name):
    chat_user = CHAT_USER_NOT_FOUND_RESULT
    if chat_provider_name == 'slack':
        chat_user = get_slack_user(pd_email, pd_name)
    return chat_user


def get_slack_user(email, name):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['email'] = email

    slack_user = {
        'at_handle': None,
        'id': None,
        'email': email,
        'exists': False,
        'name': name
    }

    try:
        r = requests.get('https://slack.com/api/users.lookupByEmail', payload)
        slack_user['id'] = r.json()['user']['id']
        slack_user['exists'] = True
        slack_user['at_handle'] = '<@{}>'.format(slack_user['id'])
    except KeyError:
        logger.warn("Could not Slack username from email {}.".format(email))

    return slack_user


def get_slack_topic(channel):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['channel'] = channel
    try:
        r = requests.post('https://slack.com/api/conversations.info', data=payload)
        current = r.json()['channel']['topic']['value']
        logger.debug("Current Topic: '{}'".format(current))
    except KeyError:
        logger.critical("Could not find '{}' on slack, has the on-call bot been removed from this channel?".format(channel))
    return current


def update_chat_channel(chat_provider_name, channel_id, proposed_update):
    if chat_provider_name == 'slack':
        update_slack_topic(channel_id, proposed_update)


def update_slack_topic(channel, proposed_update):
    logger.debug("Entered update_slack_topic() with: {} {}".format(
        channel,
        proposed_update)
    )
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['channel'] = channel

    current_full_topic = get_slack_topic(channel)

    in_link = False
    pipe_idx = -1
    for pos in range(0, len(current_full_topic)):
        if current_full_topic[pos] == '<':
            in_link = True
        if current_full_topic[pos] == '>':
            in_link = False
        if current_full_topic[pos] == '|':
            if not in_link:
                pipe_idx = pos
                break

    first_part = 'none'
    second_part = '.'
    if pipe_idx != -1:
        first_part = current_full_topic[0:pipe_idx].strip()
        second_part = current_full_topic[pipe_idx + 1:].strip()

    if proposed_update != first_part:
        # slack limits topic to 250 chars
        topic = "{} | {}".format(proposed_update, second_part)
        if len(topic) > 250:
            topic = topic[0:247] + "..."
        payload['topic'] = topic
        r = requests.post('https://slack.com/api/conversations.setTopic', data=payload)
        logger.debug("Response for '{}' was: {}".format(channel, r.json()))
    else:
        logger.info("Not updating slack, topic is the same")
        return None


def update_chat_group(chat_provider_name, chat_group, chat_user_id):
    if chat_provider_name == 'slack':
        update_slack_group(chat_group, chat_user_id)


def update_slack_group(group_id, user_id):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['usergroup'] = group_id

    r = requests.get('https://slack.com/api/usergroups.users.list', params=payload)
    try:
        current_users = r.json()['users']
    except IndexError:
        current_users = []

    if user_id not in current_users:
        payload['users'] = user_id
        requests.post('https://slack.com/api/usergroups.users.update', data=payload)
    else:
        logger.debug("User {} is already in group {}".format(user_id, group_id))


def figure_out_schedule(s):
    # Purpose here is to find the schedule id if given a human readable name
    # fingers crossed that this regex holds for awhile. "PXXXXXX"
    if re.match('^P[a-zA-Z0-9]{6}', s):
        return s
    global PD_API_KEY
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    url = 'https://api.pagerduty.com/schedules/'
    payload = {}
    payload['query'] = s
    # If there is no override, then check the schedule directly
    r = requests.get(url, headers=headers, params=payload)
    try:
        # This is fragile. fuzzy search may not do what you want
        sid = r.json()['schedules'][0]['id']
    except IndexError:
        logger.debug("Schedule Not Found for: {}".format(s))
        sid = None
    return sid

def normalize_dynamodb_item(obj):
    config = {
        'chat_provider': {
            'channels':  [],
            'groups': [],
            'name': 'unknown',
            'supported': False
        },
        'pagerduty': {
            'schedule_id': obj['schedule']['S'],
            'schedule_name': obj['sched_name']['S'] if 'sched_name' in obj else None
        }
    }

    if 'slack' in obj.keys():
        config['chat_provider']['name'] = 'slack'
        config['chat_provider']['supported'] = True
        if 'S' in obj['slack']:
            slack = obj['slack']['S']
            config['chat_provider']['channels'] = slack.split()
        if 'slack_groups' in obj.keys():
            if 'S' in obj['slack_groups']:
                slack_groups = obj['slack_groups']['S']
                config['chat_provider']['groups'] = slack_groups.split()

    elif 'hipchat' in obj.keys():
        config['chat_provider']['name'] = 'hipchat'
        config['chat_provider']['supported'] = False

    return config


def do_work(obj):
    # entrypoint of the thread
    sema.acquire()
    logger.debug("Operating on {}".format(obj))

    return do_work_critical(obj)

    sema.release()


def do_work_critical(obj):
    config = normalize_dynamodb_item(obj)

    if not config['chat_provider']['supported']:
        logger.critical("{} is not supported yet. Ignoring this entry...".format(config['chat_provider']['name']))
        return 127

    # schedule will ALWAYS be there, it is a ddb primarykey
    schedule_id = figure_out_schedule(config['pagerduty']['schedule_id'])

    if not schedule_id:
        logger.critical("Exiting: Schedule not found or not valid, see previous errors")
        return 127

    # Get schedule name
    pd_schedule_name = config['pagerduty']['schedule_name']
    if not pd_schedule_name:
        pd_schedule_name = get_pd_schedule_name(schedule_id)

    # Get PagerDuty and chat user info
    pd_user = get_pd_user(schedule_id)
    chat_user = CHAT_USER_NOT_FOUND_RESULT
    if pd_user['exists']:
        chat_user = get_chat_user(config['chat_provider']['name'], pd_user['email'], pd_user['name'])

    # Get name to show in topic
    topic_user = pd_user['name']
    if chat_user['exists']:
        topic_user = chat_user['at_handle']

    # Prepare new topic
    topic = "{}{} is on-call for {}".format(
        topic_user,
        " (override)" if pd_user['is_override'] else "",
        pd_schedule_name
    )

    for channel in config['chat_provider']['channels']:
        update_chat_channel(config['chat_provider']['name'], channel, topic)

    if chat_user['exists']:
        for group in config['chat_provider']['groups']:
            update_chat_group(config['chat_provider']['name'], group, chat_user['id'])


def handler(event, context):
    print(event)
    ddb = boto3.client('dynamodb')
    response = ddb.scan(TableName=os.environ['CONFIG_TABLE'])
    threads = []
    for i in response['Items']:
        thread = threading.Thread(target=do_work, args=(i,))
        threads.append(thread)
    # Start threads and wait for all to finish
    [t.start() for t in threads]
    [t.join() for t in threads]
