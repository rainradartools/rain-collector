#!/bin/bash
echo START
STACK_NAME=$1
LAMBDA=$2

TMP_DIR=/tmp/deployment_package

rm -rf $TMP_DIR/
mkdir -p $TMP_DIR

cp ./lambda_functions/Collector/* $TMP_DIR 2>/dev/null

echo "installing packages"
while read package
do
  pip install $package -t $TMP_DIR/
done <$TMP_DIR/requirements.txt

find $TMP_DIR -name \*.pyc -delete
(cd $TMP_DIR ; zip -r $LAMBDA.zip *)

aws lambda update-function-code \
    --function-name "$STACK_NAME"_"$LAMBDA" \
    --zip-file fileb://$TMP_DIR/$LAMBDA.zip
