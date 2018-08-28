#!/usr/bin/env bash

# Quick script to assist with dynamodb config
STACKNAME_BASE=$(grep -E -o -m 1 '"([^"]*)"' ./Makefile | sed 's/"//g')
TABLE_NAME=$(aws cloudformation list-exports |grep -E -o "$STACKNAME_BASE-ConfigTable-.*?" | sed 's/",//g')

read -sp "Pagerduty schedule ID (PXXXXX): " schedule; echo
read -sp "Slack channel (CXXXXXXXX): " slack; echo

# build dynamodb json. variable handling makes it janky
read -r -d '' TABLE_ITEM << EOM
{"schedule":
{
"S": "$schedule"},"slack":
{
"S": "$slack"
}
}
EOM
echo $STACKNAME_BASE
echo $TABLE_ITEM

# update dynamodb table
aws dynamodb put-item --table-name $TABLE_NAME --item "$TABLE_ITEM"
