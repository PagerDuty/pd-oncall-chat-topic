#!/usr/bin/env bash

# Quick script to assist with syntax for SSM input
# $1 is the parameter name
# $2 is the stack name
# $3 is the region

read -sp "API Key (not eched to terminal): " passwd; echo

aws ssm --region ${3} \
    put-parameter --name ${1} \
    --description "Used by stack: ${2}" \
    --overwrite \
    --value ${passwd} --type SecureString
