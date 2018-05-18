import json
import boto3
import os
import traceback
from datetime import datetime, timezone, timedelta

from botocore.vendored import requests
from main import figure_out_schedule, PD_API_KEY, logger

def get_ssm_param(env_name):
    try:
        return boto3.client('ssm').get_parameters(
            Names=[os.environ[env_name]],
            WithDecryption=True)['Parameters'][0]['Value']
    except:
        print('could not get parameter for env var', env_name, os.environ[env_name])
        traceback.print_exc()

VERIFICATION_TOKEN = get_ssm_param('SLACK_VERIFICATION_TOKEN_NAME')

OAUTH_ACCESS_TOKEN = get_ssm_param('SLACK_OAUTH_ACCESS_TOKEN_NAME')

BOT_OAUTH_ACCESS_TOKEN = get_ssm_param('SLACK_BOT_OAUTH_ACCESS_TOKEN_NAME')

def respond(err, res=None):
    return {
        'statusCode': '400' if err else '200',
        'body': err.message if err else json.dumps(res),
        'headers': {
            'Content-Type': 'application/json',
        },
    }

def read_table():
    # we don't have an index yet... but it's 20something items
    ddb = boto3.client('dynamodb')
    response = ddb.scan(TableName=os.environ['CONFIG_TABLE'])

    channel_to_schedule = {}
    for obj in response['Items']:
        schedule_id = obj['schedule']['S']
        slack = obj['slack']['S']
        for channel in slack.split(' '):
            channel_to_schedule[channel] = schedule_id

    print(channel_to_schedule)
    return channel_to_schedule

# Get the Current User on-call for a given schedule
def get_oncall_user(schedule_id):
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
        username = normal.json()['users'][0]['name']
        email = normal.json()['users'][0]['email']
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
        email = ""

    logger.info("Currently on call: {}".format(username))
    return (username, email)

def get_slack_user(email_address):
    userinfo_url = 'https://slack.com/api/users.lookupByEmail'
    headers = {'Authorization': 'Bearer ' + BOT_OAUTH_ACCESS_TOKEN}
    payload = {}
    payload['email'] = email_address
    userinfo = requests.get(userinfo_url, headers=headers, params=payload)
    if userinfo.status_code != 200:
        logger.critical("ABORT: Slack API returned {}".format(userinfo.status_code))
        return False
    try:
        userinfo_json = userinfo.json()
        if userinfo_json['ok'] == True:
            slack_user_id = userinfo_json['user']['id']
            logger.info("Slack user ID: {}".format(slack_user_id))
            return slack_user_id
        else:
            logger.critical("ERROR: Slack API returned: {}".format(userinfo_json['error']))
            return False
    except IndexError:
        return False

def build_response(table, channel):
    if channel not in table:
        return "Sorry, I don't have an on-call schedule set for this channel"
    schedule = table[channel]
    # this is currently a no-op with the data we have
    schedule = figure_out_schedule(schedule)
    if not schedule:
        return "Sorry, I can't understand the current schedule"
    username, email = get_oncall_user(schedule)
    if not email:
        return f"{username} is on call, but I don't know their slack username because I don't know their email"
    slack_user = get_slack_user(email)
    if not slack_user:
        return f"{username} is on call, but I couldn't find their slack username from their email"
    return f"{username} is on call with slack id <@{slack_user}>"



def handler(event, context):
    try:
        table = read_table()
    except:
        print('could not read table')
        traceback.print_exc()
        respond(None, {})
    print('in mention handler')
    print(event)
    body = json.loads(event['body'])
    print(body)
    print(body['type'])
    assert body['token'] == VERIFICATION_TOKEN
    if body['type'] == 'url_verification':
        return respond(None, {'challenge': body['challenge']})
    elif body['type'] == 'event_callback':
        print(body['event'])
        channel = body['event']['channel']
        ts = body['event']['ts']
        response = build_response(table, channel)
        requests.post('https://slack.com/api/chat.postMessage',
                      headers={'Authorization': 'Bearer ' + BOT_OAUTH_ACCESS_TOKEN},
                      json={'channel': channel, 'thread_ts': ts, 'text': response})
        return respond(None, {})
    else:
        raise Exception('unknown body type!')


