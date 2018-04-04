
#### Dependencies

The below assumes you've already setup a data stack and a configuration stack. [See here for details](https://github.com/rainradartools/Instructions)

#### 1. Deploy stack

Deploy as a stack in AWS using the `cloudformation/rain-collector.yml` template

Parameters:

SNSArn: the arn of an SNS topic to send messages to (optional - leave empty if not using this feature)
CollectorFrequency: How frequently the CloudWatch event should trigger lambda check for new data
ConfigurationBucket: the name of the configuration bucket you created in the configuration stack
DataBucket: the name of the data bucket you created in the configuration stack

#### 2. Deploy lambda

##### Upload Collector Lambda


Either upload the pre-packaged `Collector` lambda _packaged/Collector.zip_ using the lambda console, or run:

```
Package and upload from source
./lambda_deploy.sh rain-collector-<yourname> Collector
```
