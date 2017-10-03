# pd-oncall-chat-topic
AWS Lambda Function that updates a Chat Room topic (eg, Slack)

## Motivation
At [PagerDuty](https://www.pagerduty.com/), we
[use](https://www.pagerduty.com/blog/how-does-pagerduty-use-pagerduty/)
PagerDuty to manage our on-call schedules. One integration that we like is
knowing who is on-call for a given team, via posting the information in a Slack
channel topic.

At PagerDuty Summit, one of our customers asked if we have this integration
open-sourced for them to use as well. At the time, we did not, it was deeply
integrated into our ChatOps tooling that is very specific to the PagerDuty
infrastructure. However, this integration is applicable to many other
organizations.

This project started at one of our Hack Days, a day put aside monthly for
employees to build and present projects or ideas that fulfill some kind of need
at the company.

## How to Deploy
1. Create a Slack App and obtain a API key. https://api.slack.com/apps
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
  - It is possible to use the AWS CLI for this (or finish #4 for ease of use.
  - In lieu of above, manually update the table with item entries of this format:
  ```
  {
    "schedule": "P123456",
    "slack": "C123456"
  }
  ```
  (where `schedule` is the PagerDuty Schedule ID, and `slack` is the Slack
  Channel ID)

## Architecture
The main part of this infrastructure is an AWS Lambda Function that operates on
a schedule (cron), reads configuration information from an DynomoDB Table and
secrets from AWS EC2 Parameter Store. This is all deployed from a AWS
CloudFormation template.

![Architecture
Diagram](https://raw.githubusercontent.com/PagerDuty/pd-oncall-chat-topic/master/diagram.png)

## Cost
The way that this Lambda Function is configured, is to run on a schedule every 5
minutes. Some basic (anecdotal) testing revealed that the execution is about 5
seconds per 5 updates (via threading). Assuming double that and erroring on the
side of a large configuration (10x) the execution time will cost below $2/month.
The DDB table will cost, ~$0.60/month.


## Contact
This integration is primarily maintained by the SRE Team at PagerDuty. The best
way to reach us is by opening a GitHub issue.
