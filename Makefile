STACKNAME_BASE=pagerduty-oncall-chat-topic
# if REGION is changed, use table in https://aws.amazon.com/blogs/compute/upcoming-changes-to-the-python-sdk-in-aws-lambda/ to update ChatTopicFunction lambda layer value
REGION="ca-central-1"
# Bucket in REGION that is used for deployment (`pd-oncall-chat-topic` is already used)
BUCKET=$(STACKNAME_BASE)
SSMKeyArn=$(shell aws kms --region $(REGION) describe-key --key-id alias/aws/ssm --query KeyMetadata.Arn)
MD5=$(shell md5sum lambda/*.py | md5sum | cut -d ' ' -f 1)


deploy:
	cd lambda && \
		zip -r9 /tmp/deployment.zip *.py && \
		aws s3 cp --region $(REGION) /tmp/deployment.zip \
			s3://$(BUCKET)/$(MD5) && \
		rm -rf /tmp/deployment.zip
	aws cloudformation deploy \
		--template-file deployment.yml \
		--stack-name $(STACKNAME_BASE) \
		--region $(REGION) \
		--parameter-overrides \
		"Bucket=$(BUCKET)" \
		"md5=$(MD5)" \
		"SSMKeyArn"=$(SSMKeyArn) \
		"PDSSMKeyName"=$(STACKNAME_BASE) \
		"SlackSSMKeyName"=$(STACKNAME_BASE)-slack \
		--capabilities CAPABILITY_IAM || exit 0

discover:
	aws cloudformation --region $(REGION) \
		describe-stacks \
		--stack-name $(STACKNAME_BASE) \
		--query 'Stacks[0].Outputs'

put-pd-key:
	./scripts/put-ssm.sh $(STACKNAME_BASE) $(STACKNAME_BASE) $(REGION)
put-slack-key:
	./scripts/put-ssm.sh $(STACKNAME_BASE)-slack $(STACKNAME_BASE) $(REGION)
