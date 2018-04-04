import json
from cStringIO import StringIO
from uuid import uuid4
import os

import boto3
import arrow
import requests

env_state_bucket = os.environ['state_bucket']
env_data_bucket = os.environ['rain_data_bucket']
env_config_bucket = os.environ['configuration_bucket']
env_sns_arn = os.environ['sns_arn']

#config bucket keys
radar_facts_key = 'radar_facts.json'
enabled_push_radars_key = 'enabled_radar_ids.json'

#state bucket keys
state_obj = 'state.json'

#locations
rain_prefix = 'rain/'

s3_resource = boto3.resource('s3')
s3_client = boto3.client('s3')
sns_client = boto3.client('sns')

data_bkt = s3_resource.Bucket(env_data_bucket)
state_bkt = s3_resource.Bucket(env_state_bucket)

#load configs
radar_facts = json.loads(s3_resource.Object(env_config_bucket, radar_facts_key).get()['Body'].read().decode('utf-8'))
enabled_push_radars_lst = json.loads(s3_resource.Object(env_config_bucket, enabled_push_radars_key).get()['Body'].read().decode('utf-8'))['push_radars']

STALE_MINS = 30

 
def get_radar_conf(radar_id):
    for radar in radar_facts['radars']:
        if radar['id'] == radar_id:
            return radar
    raise Exception('could not find radar_id {} in global configuration'.format(radar_id))


def get_s3_states():
    try:
        obj = s3_resource.Object(env_state_bucket, state_obj)
        return json.loads(obj.get()['Body'].read().decode('utf-8'))
    except:
        print('could not retrieve state file from s3')
        return {}


def init_state(dt_now, res, offset):
    min_remainder = dt_now.minute % res
    tmp_dt = dt_now.replace(minutes=-min_remainder).replace(minutes=+offset)
    next_str = tmp_dt.format('YYYYMMDDHHmm')
    return {"attempt": 0, "next": int(next_str)}


def get_states(dt_now):
    existing_states = get_s3_states()
    print(existing_states)

    states = {}

    #create the full list of states
    for id in enabled_push_radars_lst:
        #either from s3 state file
        if id in existing_states:
            states[id] = existing_states[id]
        #or create new
        else:
            print('could not retrive {} from state file - init'.format(id))
            rc = get_radar_conf(id)
            states[id] = init_state(dt_now, rc['resolution_mins'], rc['add_offset_mins'] )

    return states


def save_states_to_s3(states):

    track_f = StringIO(json.dumps(states))
    track_f.seek(0)

    response = s3_client.put_object(
        Body=track_f,
        Bucket=env_state_bucket,
        Key=state_obj
    )


def isStale(cur_str, next_str, stale_max):
    cur_dt = arrow.get(cur_str, 'YYYYMMDDHHmm')
    fwd_dt = arrow.get(next_str, 'YYYYMMDDHHmm').replace(minutes=+stale_max)

    #if the 'next' time is less than current time after moving
    #it 'state_max' mins into future, then it's stale
    if fwd_dt < cur_dt:
        return True
    else:
        return False


def downloadPNG(cdn, radar_id, timestamp):
    url = '{}/radar/{}.T.{}.png'.format(cdn, radar_id, timestamp)

    try:
        r = requests.get(url, timeout=3)
    except:
        print(p+'!!! REQUEST TIMEOUT')
        return False

    if r.status_code == 200:
        #write image to local file then upload to s3
        local_file = '/tmp/{}'.format(str(uuid4())[:4])

        with open(local_file, 'wb') as fp:
            fp.write(r.content)

        return local_file
    else:
        return False


def move_to_next(cur, res):
    next = arrow.get(str(cur), 'YYYYMMDDHHmm').replace(minutes=+res).format('YYYYMMDDHHmm')
    return {'next': int(next), 'attempt': 0}


def upload_file_to_s3(file, key):

    try:
        s3_client.upload_file(file, env_data_bucket, key, ExtraArgs={"ContentType": "image/png"})
        os.remove(file)
        return True
    except Exception, e:
        print(str(e))
        os.remove(file)
        return False



def handler(event, context):

    print('________ handler ________')

    #print prefix
    p = ''

    dt_now = arrow.utcnow()
    now_str = dt_now.format('YYYYMMDDHHmm')
    print('time now: {}'.format(now_str))
    print('enabled radars: {}'.format(', '.join(enabled_push_radars_lst)))

    states = get_states(dt_now)

    if not states:
        print('did not get any states from S3')

    for radar_id in enabled_push_radars_lst:
        p = radar_id+': '
        print(p+'START')

        #config for radar_id#processing a single radar
        rc = get_radar_conf(radar_id)
        print(p+' '.join(['{0}={1}'.format(k, v) for k,v in rc.iteritems()]))

        #get the state from 'states'
        state = states[radar_id]

        if isStale(now_str, str(state['next']), STALE_MINS):
            print(p+'STALE TIMESTAMP. now: {} next: {} (exceeded global_config stale_mins: {})'.format(now_str, state['next'], STALE_MINS))
            print(p+'ire-initialising state')
            state = init_state(dt_now, rc['resolution_mins'], rc['add_offset_mins'])
            states[radar_id] = state

        print(p+'next expected bom timestamp: {}'.format(state['next']))
        print(p+'current time: {}'.format(now_str))
        print(p+'attempt #{}'.format(str(int(state['attempt']) + 1)))

        if int(now_str) > (int(state['next']) + rc['cdn_wait_mins']):
            elapsed_mins = int(now_str) - state['next']
            print(p+'+{} mins since next timestamp'.format(elapsed_mins))

            tmp_file = downloadPNG(radar_facts['bom_cdn_url'], radar_id, state['next'])

            if tmp_file:
                print(p+'download SUCCESS')
                target_key = '{}{}/{}/{}.png'.format(
                    rain_prefix,
                    radar_id,
                    radar_facts['raw_radar_image_size'],
                    str(state['next'])
                )

                if upload_file_to_s3(tmp_file, target_key):
                    print(p+'uploaded: {}'.format(target_key))
                    print(p+'upload SUCCESS. waited {}m for cdn cdn_wait_mins={}'.format(elapsed_mins, rc['cdn_wait_mins'] ))
                    
                    try:
                        #if it's top of the hour for IDR762
                        if str(state['next'])[-2:] == "00" and radar_id == "IDR762":
                            print(p+'going to try sns for {}'.format(state['next']))
                            message = {
                                "lambda": {
                                    "key": target_key,
                                    "bucket": env_data_bucket
                                    }
                                }

                            response = sns_client.publish(
                                TopicArn=env_sns_tweet_topic_arn,
                                MessageStructure='json',
                                Message=json.dumps({
                                    "default": "default",
                                    "lambda": json.dumps(message)
                                })
                            )

                            print(p+"sns sent")
                    except Exception,e:
                        print(str(e))

                    state = move_to_next(state['next'], rc['resolution_mins'])
                    print(p+'moved next to {}'.format(state['next']))
                    states[radar_id] = state
                else:
                    print(p+'upload FAILED')

            else:
                print(p+'download FAILED')
                #increment attempts

                attempts = state['attempt'] + 1

                if attempts >= rc['max_attempts']:
                    print(p+'MAX ATTEMPTS: {} attempts have been made. max_attempts for this radar is {}'.format(str(attempts), rc['max_attempts']))
                    print(p+'initialising new state for {}'.format(radar_id))
                    state = init_state(dt_now, rc['resolution_mins'], rc['add_offset_mins'])
                    states[radar_id] = state
                else:
                    state['attempt'] = attempts
                    states[radar_id] = state
                    print(p+'incremented attempts')

        else:
            print(p+'bailing (too early). cdn_wait_mins for this radar is {} mins'.format(rc['cdn_wait_mins']))


    print('saving states to s3')
    save_states_to_s3(states)
    
