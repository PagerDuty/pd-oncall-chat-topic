#!/usr/bin/env python

import os
from datetime import datetime, timezone, timedelta
import threading
import logging
import re

import json
from urllib3 import PoolManager
import boto3

# semaphore limit of 5, picked this number arbitrarily
maxthreads = 5
sema = threading.Semaphore(value=maxthreads)
http = PoolManager()

logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# Fetch the PD API token. PAGERDUTY_API_KEY env var bypasses SSM for testing.
PD_API_KEY = os.environ.get('PAGERDUTY_API_KEY') or boto3.client('ssm').get_parameters(
    Names=[os.environ['PD_API_KEY_NAME']],
    WithDecryption=True)['Parameters'][0]['Value']


def get_user(schedule_id):
    """Return the on-call username for a schedule, dispatching to v3 for shift-based schedules and v2 for layer-based."""
    # Try shift-based (v3) path first; falls back to layer-based (v2) on None
    username = get_user_v3(schedule_id)
    if username is not None:
        logger.info("Currently on call: {}".format(username))
        return username

    # v2 layer-based path
    global PD_API_KEY
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    normal_url = 'https://api.pagerduty.com/schedules/{0}/users'.format(schedule_id)
    override_url = 'https://api.pagerduty.com/schedules/{0}/overrides'.format(schedule_id)
    # This value should be less than the running interval
    # It is best to use UTC for the datetime object
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=1)  # One minute ago
    payload = {}
    payload['since'] = since.isoformat()
    payload['until'] = now.isoformat()
    response = http.request('GET', normal_url, headers=headers, fields=payload)
    body = response.data.decode('utf-8')
    if response.status == 404:
        logger.critical("ABORT: Not a valid schedule: {}".format(schedule_id))
        return False
    normal = json.loads(body)
    try:
        username = normal['users'][0]['name']
        # Check for overrides
        # If there is *any* override, then the above username is an override
        # over the normal schedule. The problem must be approached this way
        # because the /overrides endpoint does not guarentee an order of the
        # output.
        override_response = http.request('GET', override_url, headers=headers, fields=payload)
        override = json.loads(override_response.data.decode('utf-8'))
        if override.get('overrides'):
            username = username + " (Override)"
    except IndexError:
        username = "No One :thisisfine:"
    except KeyError:
        username = "Deactivated User :scream: ({})".format(normal['users'][0]['summary'])

    logger.info("Currently on call: {}".format(username))
    return username


def get_user_v3(schedule_id):
    """Return the on-call username for a shift-based (v3) schedule, or None if the schedule is layer-based."""
    global PD_API_KEY
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=1)
    payload = {
        'since': since.isoformat(),
        'until': now.isoformat(),
        'include[]': 'final_schedule',
    }
    response = http.request(
        'GET',
        'https://api.pagerduty.com/v3/schedules/{0}'.format(schedule_id),
        headers=headers,
        fields=payload
    )
    if response.status == 400:
        return None  # not a shift-based schedule
    if response.status == 404:
        logger.critical("ABORT: Not a valid schedule: {}".format(schedule_id))
        return False

    body = json.loads(response.data.decode('utf-8'))
    assignments = (
        body.get('schedule', {})
            .get('final_schedule', {})
            .get('computed_shift_assignments', [])
    )

    active = [a for a in assignments if a['member']['type'] == 'user_member']
    if not active:
        return 'No One :thisisfine:'

    assignment = active[0]
    username = get_user_name(assignment['member']['user_id'])
    if assignment.get('source', {}).get('type', '').endswith('_override'):
        username += ' (Override)'
    return username


def get_user_name(user_id):
    """Resolve a PagerDuty user_id to a display name via the v2 /users endpoint."""
    global PD_API_KEY
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    response = http.request('GET', 'https://api.pagerduty.com/users/{0}'.format(user_id), headers=headers)
    try:
        return json.loads(response.data.decode('utf-8'))['user']['name']
    except (KeyError, ValueError):
        return user_id


def get_pd_schedule_name(schedule_id):
    """Return the human-readable name for a schedule, trying v3 first then v2."""
    global PD_API_KEY
    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    # Try v3 first (shift-based schedules return 400 on the v2 endpoint)
    for url in [
        'https://api.pagerduty.com/v3/schedules/{0}'.format(schedule_id),
        'https://api.pagerduty.com/schedules/{0}'.format(schedule_id),
    ]:
        response = http.request('GET', url, headers=headers)
        if response.status == 400:
            continue
        try:
            return json.loads(response.data.decode('utf-8'))['schedule']['name']
        except KeyError:
            logger.debug(response.status)
            logger.debug(response.data)
            return None
    return None


def get_slack_topic(channel):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['channel'] = channel
    try:
        response = http.request('POST', 'https://slack.com/api/conversations.info', fields=payload)
        body = response.data.decode('utf-8')
        r = json.loads(body)
        current = r['channel']['topic']['value']
        logger.debug("Current Topic: '{}'".format(current))
    except KeyError:
        logger.critical("Could not find '{}' on slack, has the on-call bot been removed from this channel?".format(channel))
    return current


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

    # This is tricky to get correct for all the edge cases
    # Because Slack adds a '<mailto:foo@example.com|foo@example.com>' behind the
    # scenes, we need to match the email address in the first capturing group,
    # then replace the rest of the string with the address
    # None of this is really ideal because we lose the "linking" aspect in the
    # Slack Topic.
    current_full_topic = re.sub(r'<mailto:([a-zA-Z@.]*)(?:[|a-zA-Z@.]*)>',
            r'\1', get_slack_topic(channel))
    # Also handle Slack "Subteams" in the same way as above
    current_full_topic = re.sub(r'<(?:!subteam\^[A-Z0-9|]*)([@A-Za-z-]*)>', r'\1',
            current_full_topic)
    # Also handle Slack Channels in the same way as above
    current_full_topic = re.sub(r'<(?:#[A-Z0-9|]*)([@A-Za-z-]*)>', r'#\1',
            current_full_topic)

    if current_full_topic:
        # This should match every case EXCEPT when onboarding a channel and it
        # already has a '|' in it. Workaround: Fix topic again and it will be
        # correct in the future
        current_full_topic_delimit_count = current_full_topic.count('|')
        c_delimit_count = current_full_topic_delimit_count - 1
        if c_delimit_count < 1:
            c_delimit_count = 1

        # This rsplit is fragile too!
        # The original intent was to preserve a '|' in the scehdule name but
        # that means multiple pipes in the topic do not work...
        try:
            first_part = current_full_topic.rsplit('|', c_delimit_count)[0].strip()
            second_part = current_full_topic.replace(first_part + " |", "").strip()
        except IndexError:  # if there is no '|' in the topic
            first_part = "none"
            second_part = current_full_topic
    else:
        first_part = "none"
        second_part = "."  # if there is no topic, just add something

    proposed_update = proposed_update.strip()
    if proposed_update != first_part:
        # slack limits topic to 250 chars
        topic = "{} | {}".format(proposed_update, second_part)
        if len(topic) > 250:
            topic = topic[0:247] + "..."
        payload['topic'] = topic
        response = http.request('POST', 'https://slack.com/api/conversations.setTopic', fields=payload)
        body = response.data.decode('utf-8')
        r = json.loads(body)
        logger.debug("Response for '{}' was: {}".format(channel, r))
    else:
        logger.info("Not updating slack, topic is the same")
        return None


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
    response = http.request('GET', url, headers=headers, fields=payload)
    body = response.data.decode('utf-8')
    r = json.loads(body)
    try:
        # This is fragile. fuzzy search may not do what you want
        sid = r['schedules'][0]['id']
    except IndexError:
        logger.debug("Schedule Not Found for: {}".format(s))
        sid = None
    return sid


def do_work(obj):
    # entrypoint of the thread
    sema.acquire()
    logger.debug("Operating on {}".format(obj))
    # schedule will ALWAYS be there, it is a ddb primarykey
    schedules = obj['schedule']['S']
    schedule_list = schedules.split(',')
    oncall_dict = {}
    for schedule in schedule_list:  #schedule can now be a whitespace separated 'list' in a string
        schedule = figure_out_schedule(schedule)

        if schedule:
            username = get_user(schedule)
        else:
            logger.critical("Exiting: Schedule not found or not valid, see previous errors")
            return 127
        try:
            sched_names = (obj['sched_name']['S']).split(',')
            sched_name = sched_names[schedule_list.index(schedule)] #We want the schedule name in the same position as the schedule we're using
        except:
            sched_name = get_pd_schedule_name(schedule)
        oncall_dict[username] = sched_name

    if oncall_dict:  # then it is valid and update the chat topic
        topic = ""
        i = 0
        for user in oncall_dict:
            if i != 0:
                topic += ", "
            topic += "{} is on-call for {}".format(
                user,
                oncall_dict[user]
            )
            i += 1

        if 'slack' in obj.keys():
            slack = obj['slack']['S']
            # 'slack' may contain multiple channels seperated by whitespace
            for channel in slack.split():
                update_slack_topic(channel, topic)
        elif 'hipchat' in obj.keys():
            # hipchat = obj['hipchat']['S']
            logger.critical("HipChat is not supported yet. Ignoring this entry...")
    sema.release()


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
