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

## Architecture
The main part of this infrastructure is an AWS Lambda Function that operates on
a schedule (cron), reads configuration information from an DynomoDB Table and
secrets from AWS EC2 Parameter Store. This is all deployed from a AWS
CloudFormation template.

< insert picture here >

## Cost
The way that this Lambda Function is configured, is to run on a schedule every 5
minutes. Some basic (anecdotal) testing revealed that the execution is about 5
seconds per 5 updates (via threading). Assuming double that and erroring on the
side of a large configuration (10x) the execution time will cost below $2/month.
The DDB table will cost, ~$0.60/month.


## Contact
This integration is primarily maintained by the SRE Team at PagerDuty. The best
way to reach us is by opening a GitHub issue.
