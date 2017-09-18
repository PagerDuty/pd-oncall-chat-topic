STACKNAME_BASE=pd-oncall-chat-topic
REGION="ca-central-1"
SSMKeyArn=$(shell aws kms --region $(REGION) describe-key --key-id alias/aws/ssm --query KeyMetadata.Arn)
BUCKET=$(STACKNAME_BASE)
MD5=$(shell md5sum lambda/*.py lambda/*.json | md5sum | cut -d ' ' -f 1)


deploy:
	cd lambda && \
		zip -r9 /tmp/deployment.zip *.py config.json && \
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
		"SSMKeyName"=$(STACKNAME_BASE) \
		--capabilities CAPABILITY_IAM || exit 0

