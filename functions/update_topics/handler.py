#!/usr/bin/env python

import os
from datetime import datetime, timezone, timedelta
import threading
import logging
import re

from botocore.vendored import requests
from botocore.exceptions import NoRegionError
import boto3


MAX_THREADS = None
SEMA = None
LOGGER = None

PD_API_KEY = None
PD_API_FQDN = None
PD_API_ROUTE_SCHEDULES = None
PD_API_ROUTE_SCHEDULE_USERS = None
PD_API_ROUTE_SCHEDULE_OVERRIDES = None


class EnvironmentVariableNotReadyError(Exception):
    variable_name = None

    """
    Exception raised for errors using global variables mapped to environment
    variables before they are ready.
    """
    def __init__(self, variable_name):
        self.variable_name = variable_name
        self.message = f"Variable '{variable_name}' is not instantiated! Invoke '{init_config.__name__}()' before use!"
        super().__init__(self.message)


def get_pdapi_schedules_route():
    if PD_API_FQDN is None:
        raise EnvironmentVariableNotReadyError('PD_API_FQDN')

    if PD_API_ROUTE_SCHEDULES is None:
        raise EnvironmentVariableNotReadyError('PD_API_ROUTE_SCHEDULES')

    route = f"https://{PD_API_FQDN}/{PD_API_ROUTE_SCHEDULES}"
    return route    


def get_pdapi_schedule_users_route(schedule_id):
    if PD_API_FQDN is None:
        raise EnvironmentVariableNotReadyError('PD_API_FQDN')

    if PD_API_ROUTE_SCHEDULE_USERS is None:
        raise EnvironmentVariableNotReadyError('PD_API_ROUTE_SCHEDULE_USERS')

    route = f"https://{PD_API_FQDN}/{PD_API_ROUTE_SCHEDULE_USERS}".format(schedule_id)
    return route


def get_pdapi_schedule_overrides_route(schedule_id):
    if PD_API_FQDN is None:
        raise EnvironmentVariableNotReadyError('PD_API_FQDN')

    if PD_API_ROUTE_SCHEDULE_OVERRIDES is None:
        raise EnvironmentVariableNotReadyError('PD_API_ROUTE_SCHEDULE_OVERRIDES')
    
    route = f"https://{PD_API_FQDN}/{PD_API_ROUTE_SCHEDULE_OVERRIDES}".format(schedule_id)
    return route


def get_pdapi_headers():
    # TODO: Add a dictionary argument and merge with headers for flexibility
    if PD_API_KEY is None:
        raise EnvironmentVariableNotReadyError('PD_API_KEY')

    headers = {
        'Accept': 'application/vnd.pagerduty+json;version=2',
        'Authorization': 'Token token={token}'.format(token=PD_API_KEY)
    }
    return headers


# Get the Current User on-call for a given schedule
def get_user(schedule_id):
    global PD_API_KEY
    headers = get_pdapi_headers()
    normal_url = get_pdapi_schedule_users_route(schedule_id)
    override_url = get_pdapi_schedule_overrides_route(schedule_id)
    # This value should be less than the running interval
    # It is best to use UTC for the datetime object
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=1)  # One minute ago
    payload = {}
    payload['since'] = since.isoformat()
    payload['until'] = now.isoformat()
    normal = requests.get(normal_url, headers=headers, params=payload)
    if normal.status_code == 404:
        LOGGER.critical("ABORT: Not a valid schedule: {}".format(schedule_id))
        return False
    try:
        username = normal.json()['users'][0]['name']
        # Check for overrides
        # If there is *any* override, then the above username is an override
        # over the normal schedule. The problem must be approached this way
        # because the /overrides endpoint does not guarentee an order of the
        # output.
        override = requests.get(override_url, headers=headers, params=payload)
        if override.json()['overrides']:  # is not empty list
            username = username + " (Override)"
    except IndexError:
        username = "No One :thisisfine:"

    LOGGER.info("Currently on call: {}".format(username))
    return username


def get_pd_schedule_name(schedule_id):
    global PD_API_KEY
    headers = get_pdapi_headers()
    url = get_pdapi_schedules_route(schedule_id)
    r = requests.get(url, headers=headers)
    try:
        return r.json()['schedule']['name']
    except KeyError:
        LOGGER.debug(r.status_code)
        LOGGER.debug(r.json())
        return None


def get_slack_topic(channel):
    payload = {}
    payload['token'] = boto3.client('ssm').get_parameters(
        Names=[os.environ['SLACK_API_KEY_NAME']],
        WithDecryption=True)['Parameters'][0]['Value']
    payload['channel'] = channel
    try:
        r = requests.post('https://slack.com/api/conversations.info', data=payload)
        current = r.json()['channel']['topic']['value']
        LOGGER.debug("Current Topic: '{}'".format(current))
    except KeyError:
        LOGGER.critical("Could not find '{}' on slack, has the on-call bot been removed from this channel?".format(channel))
    return current


def update_slack_topic(channel, proposed_update):
    LOGGER.debug("Entered update_slack_topic() with: {} {}".format(
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

    if proposed_update != first_part:
        # slack limits topic to 250 chars
        topic = "{} | {}".format(proposed_update, second_part)
        if len(topic) > 250:
            topic = topic[0:247] + "..."
        payload['topic'] = topic
        r = requests.post('https://slack.com/api/conversations.setTopic', data=payload)
        LOGGER.debug("Response for '{}' was: {}".format(channel, r.json()))
    else:
        LOGGER.info("Not updating slack, topic is the same")
        return None


def figure_out_schedule(s):
    # Purpose here is to find the schedule id if given a human readable name
    # fingers crossed that this regex holds for awhile. "PXXXXXX"
    if re.match('^P[a-zA-Z0-9]{6}', s):
        return s
    global PD_API_KEY
    headers = get_pdapi_headers()
    url = get_pdapi_schedules_route()
    payload = {}
    payload['query'] = s
    # If there is no override, then check the schedule directly
    r = requests.get(url, headers=headers, params=payload)
    try:
        # This is fragile. fuzzy search may not do what you want
        sid = r.json()['schedules'][0]['id']
    except IndexError:
        LOGGER.debug("Schedule Not Found for: {}".format(s))
        sid = None
    return sid


def do_work(obj):
    # entrypoint of the thread
    SEMA.acquire()
    LOGGER.debug("Operating on {}".format(obj))
    # schedule will ALWAYS be there, it is a ddb primarykey
    schedules = obj['schedule']['S']
    schedule_list = schedules.split(',')
    oncall_dict = {}
    for schedule in schedule_list:  #schedule can now be a whitespace separated 'list' in a string
        schedule = figure_out_schedule(schedule)

        if schedule:
            username = get_user(schedule)
        else:
            LOGGER.critical("Exiting: Schedule not found or not valid, see previous errors")
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
            LOGGER.critical("HipChat is not supported yet. Ignoring this entry...")
    SEMA.release()


def init_threading():
    global MAX_THREADS, SEMA
    # semaphore limit of 5, picked this number arbitrarily
    MAX_THREADS = 5
    SEMA = threading.Semaphore(value=MAX_THREADS)
    

def init_logging():
    global LOGGER
    logging.getLogger('boto3').setLevel(logging.CRITICAL)
    logging.getLogger('botocore').setLevel(logging.CRITICAL)
    LOGGER = logging.getLogger()
    LOGGER.setLevel(logging.DEBUG)


def load_pd_api_key():
    pd_api_key = None
    
    # Fetch the PD API token from PD_API_KEY_NAME key in SSM
    try:
        pd_api_key = boto3.client('ssm').get_parameters(
            Names=[os.environ['PD_API_KEY_NAME']],
            WithDecryption=True)['Parameters'][0]['Value']
    except NoRegionError:
        return None
        # TODO: Actually handle me

    return pd_api_key

def init_config():
    global PD_API_KEY, MAX_THREADS, PD_API_FQDN
    global PD_API_ROUTE_SCHEDULES, PD_API_ROUTE_SCHEDULE_USERS, PD_API_ROUTE_SCHEDULE_OVERRIDES

    init_threading()
    init_logging()

    MAX_THREADS = os.environ.get('MAX_THREADS')
    PD_API_FQDN = os.environ.get('PD_API_FQDN')
    PD_API_ROUTE_SCHEDULES = os.environ.get('PD_API_ROUTE_SCHEDULES')
    PD_API_ROUTE_SCHEDULE_USERS = os.environ.get('PD_API_ROUTE_SCHEDULE_USERS')
    PD_API_ROUTE_SCHEDULE_OVERRIDES = os.environ.get('PD_API_ROUTE_SCHEDULE_OVERRIDES')
    PD_API_KEY = load_pd_api_key()


def handler(event, context):
    print(event)
    init_config()
    ddb = boto3.client('dynamodb')
    response = ddb.scan(TableName=os.environ['CONFIG_TABLE'])
    threads = []
    for i in response['Items']:
        thread = threading.Thread(target=do_work, args=(i,))
        threads.append(thread)
    # Start threads and wait for all to finish
    [t.start() for t in threads]
    [t.join() for t in threads]
