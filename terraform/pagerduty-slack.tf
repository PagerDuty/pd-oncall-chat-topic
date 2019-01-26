locals {
  app = "pagerduty-slack-topic"
}

variable "pager_duty_api_key" {}
variable "slack_api_token" {}
variable "pagerduty_schedule_description" {}
variable "pagerduty_schedule_id" {}

# Uncomment to let Terraform manage PD/Slack configs.
# variable "slack_channel_id" {}

resource "aws_ssm_parameter" "pdkey" {
  name  = "${local.app}-pdkey"
  type  = "SecureString"
  value = "${var.pager_duty_api_key}"
}

resource "aws_ssm_parameter" "slackkey" {
  name  = "${local.app}-slackkey"
  type  = "SecureString"
  value = "${var.slack_api_token}"
}

resource "aws_dynamodb_table" "dynamo" {
  name           = "${local.app}-dynamo"
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "hash_key"
  attribute {
    name = "hash_key"
    type = "S"
  }
  tags = {
    Name        = "${local.app}-dynamo"
    Environment = "production"
  }
}

resource "aws_iam_role" "iam-role" {
  name = "${local.app}"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
EOF
}

resource "aws_iam_role_policy" "iam-policy-ddb" {
  name = "DDB"
  role = "${aws_iam_role.iam-role.id}"

  policy = <<EOF
{
    "Statement": [
        {
            "Action": [
                "dynamodb:scan"
            ],
            "Resource": [
                "${aws_dynamodb_table.dynamo.arn}"
            ],
            "Effect": "Allow"
        }
    ]
}
EOF
}

resource "aws_iam_role_policy" "iam-policy-ssm" {
  name = "SSM"
  role = "${aws_iam_role.iam-role.id}"

  policy = <<EOF
{
    "Statement": [
        {
            "Action": [
                "ssm:GetParameters"
            ],
            "Resource": [
                "${aws_ssm_parameter.pdkey.arn}",
                "${aws_ssm_parameter.slackkey.arn}"
            ],
            "Effect": "Allow"
        }
    ]
}
EOF
}

# Let Terraform manage PD/Slack configs.
/*
resource "aws_dynamodb_table_item" "dynamo-item-1" {
  table_name = "${aws_dynamodb_table.dynamo.name}"
  hash_key   = "${aws_dynamodb_table.dynamo.hash_key}"

  item = <<ITEM
{
  "hash_key": {
    "S": "1"
  },
  "sched_name": {
    "S": "${var.pagerduty_schedule_description}"
  },
  "schedule": {
    "S": "${var.pagerduty_schedule_id}"
  },
  "slack": {
    "S": "${var.slack_channel_id}"
  }
}
ITEM
}
*/

resource "aws_iam_role_policy_attachment" "AWSLambdaBasicExecutionRole" {
  role       = "${aws_iam_role.iam-role.id}"
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "lambda" {
  filename         = "/tmp/deployment.zip"
  function_name    = "${local.app}"
  role             = "${aws_iam_role.iam-role.arn}"
  handler          = "main.handler"
  source_code_hash = "${base64sha256(file("/tmp/deployment.zip"))}"
  runtime          = "python3.6"
  timeout          = "120"
  environment {
    variables = {
      PD_API_KEY_NAME = "${local.app}-pdkey"
      SLACK_API_KEY_NAME = "${local.app}-slackkey"
      CONFIG_TABLE = "${local.app}-dynamo"
    }
  }
}

resource "aws_cloudwatch_event_rule" "cloudwatch-rule" {
  name = "${local.app}"
  depends_on = [
    "aws_lambda_function.lambda"
  ]
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "cloudwatch-target" {
  target_id = "lambda"
  rule = "${aws_cloudwatch_event_rule.cloudwatch-rule.name}"
  arn = "${aws_lambda_function.lambda.arn}"
}

resource "aws_lambda_permission" "lambda-permission" {
  statement_id = "AllowExecutionFromCloudWatch"
  action = "lambda:InvokeFunction"
  function_name = "${aws_lambda_function.lambda.function_name}"
  principal = "events.amazonaws.com"
  source_arn = "${aws_cloudwatch_event_rule.cloudwatch-rule.arn}"
}
