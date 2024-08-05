#!/bin/bash
# Check if sufficient arguments are provided
if [ "$#" -ne 3 ]; then
  echo "Usage: $0 STACKNAME_BASE REGION ITEM_FILE"
  exit 1
fi
# Quick script to assist with dynamodb config
STACKNAME_BASE="$1"
REGION="$2"
ITEMS_FILE="$3"
TABLE_NAME="pagerduty-oncall-chat-topic-ConfigTable-137M5Y1APE4WD"

# Check if the items file exists
if [ ! -f "$ITEMS_FILE" ]; then
  echo "Items file $ITEMS_FILE does not exist."
  exit 1
fi

# Read the items from the JSON file
ITEMS=$(cat "$ITEMS_FILE")

# Construct the request items JSON format for the batch-write-item command
REQUEST_ITEMS=$(jq -n --argjson items "$ITEMS" --arg table_name "$TABLE_NAME" '
{
  ($table_name): [$items[] | { PutRequest: { Item: { schedule: { S: .schedule }, slack: { S: .slack }, sched_name: { S: .sched_name } } } }]
}
')

echo $REQUEST_ITEMS

# Execute the AWS CLI command
aws dynamodb batch-write-item --region "$REGION" --request-items "$REQUEST_ITEMS"
