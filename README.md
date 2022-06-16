# pd-oncall-chat-topic

AWS Lambda Function that updates a Chat Room topic (eg, Slack)

![Screenshot](https://raw.githubusercontent.com/PagerDuty/pd-oncall-chat-topic/master/screenshot.png)

This repo is a fork of the original repo by PagerDuty. We have modified it to
suit our internal purposes, and have submitted the features to the original
repository.

## Teachers Pay Teachers

Note to Teachers Pay Teachers employees:

This is a **public** GitHub repository. Do not put sensitive information in
here.  Do not change the LICENSE, and make sure to retain the original
copyright notice.

For TpT employees who want to connect their Slack handle with a PagerDuty
Schedule, see
[this internal wiki](https://teacherspayteachers.atlassian.net/wiki/spaces/ENGINEERING/pages/2772107268/Syncing+On-Call+Slack+Handle+with+PagerDuty+Schedules).

## Motivation

At Teachers Pay teachers, we maintain on-call rotations in PagerDuty, and often
we want to be able to reach the person who is on-call in Slack.

This repository integrates PagerDuty with a Slack handle.

## Setup

1. Create an App that you can invite to your channel.
  - Go to [Slack Apps](https://api.slack.com/apps) and click "Create New App"
  - Set App Name and Development Slack Workspace
  - Add OAuth scopes: `channels.manage`, `channels:read`, `groups:read`,
    `im:write`, `mpim:read`, `users:read`, `users:read.email`
  - To have this integration replace set the membership for one or more
    user groups, add the scope `usergroups.read` and `usergroups:write`
  - Install App to Workspace
  - Invite App to channel where you want topic updated
2. Obtain a PagerDuty API Key (v2) [Directions Here](https://support.pagerduty.com/docs/using-the-api#section-generating-an-api-key)
3. Deploy CloudFormation
  - Clone repo
  - Modify 2 variables for your AWS Environment
    ([Makefile#L1-L2](https://github.com/PagerDuty/pd-oncall-chat-topic/blob/master/Makefile#L1-L2))
  - `make deploy`
4. Write API Keys to EC2 SSM Parameter Store.
  - The lambda function expects certain key names by default so the following
    commands should work unless modified elsewhere (advanced config).
  - `make put-pd-key`
  - `make put-slack-key`
5. Write Config to DynomoDB for which channels to update.
  - It is possible to use the AWS CLI for this (or finish
    [#4](https://github.com/PagerDuty/pd-oncall-chat-topic/issues/4) for ease of
    use)
  - In lieu of above, manually update the table with item entries of this format:
    ```
    {
      "schedule": "P123456",
      "slack": "C123456",
      "sched_name": "Optional schedule name to use in topic"
    }
    ```
    (where `schedule` is the PagerDuty Schedule ID, and `slack` is the Slack
    Channel ID. You can have a space-separated list of channels. `sched_name` is
    optional and if omitted will be looked up)
  - This integration can be configured to update the membership of one or more
    Slack user groups by setting `slack_groups` to a list of comma-separated
    group IDs, e.g.:
    ```
    {
      "schedule": "P123456",
      "slack": "C123456",
      "slack_groups": "S05J8PR5H0B",
      "sched_name": "Optional schedule name to use in topic"
    }
    ```
    Keep in mind that when this integration updates a user group, it will replace
    remove all existing members of the group.

## Contributing

Note that the main branch of our fork is `tpt`. This is on purpose. Pull
requests should be made against this branch, and should also be submitted
upstream to PagerDuty's clone.

Do not make changes to the `master` branch. Pull changes to that branch from
PagerDuty's clone.

## Deploy

To deploy new code changes, run `make deploy` locally.

## Architecture

The main part of this infrastructure is an AWS Lambda Function that operates on
a schedule (cron), reads configuration information from an DynomoDB Table and
secrets from AWS EC2 Parameter Store. This is all deployed from a AWS
CloudFormation template.

![Architecture Diagram](https://raw.githubusercontent.com/PagerDuty/pd-oncall-chat-topic/master/diagram.png)

## Cost

The way that this Lambda Function is configured, is to run on a schedule every 5
minutes. Some basic (anecdotal) testing revealed that the execution is about 5
seconds per 5 updates (via threading). Assuming double that and erroring on the
side of a large configuration (10x) the execution time will cost below $2/month.
The DDB table will cost, ~$0.60/month.
