import logging
import os
import uuid
from urllib.parse import unquote_plus

import boto3
import json
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_values_from_ssm(keys):
    client_ssm = boto3.client('ssm')
    logger.info("GetParameter called for ssm key: {}".format(keys))
    response = client_ssm.get_parameters(Names=keys)
    parameters = response['Parameters']
    invalidParameters = response['InvalidParameters']

    if invalidParameters:
        raise KeyError('Found invalid ssm parameter keys:' + ','.join(invalidParameters))

    parameter_dictionary = {}
    for parameter in parameters:
        parameter_dictionary[parameter['Name']] = parameter['Value']

    return parameter_dictionary


def is_partial_load(file_name, prefixes_str):
    prefix_list = prefixes_str.split(",")
    for prefix in prefix_list:
        if file_name.startswith(prefix):
            return True
    return False


def lambda_handler(event, context):
    client_step_function = boto3.client('stepfunctions')

    step_function_arn = os.environ['stepFunctionArn']
    env = os.environ['env']
    intermediate_s3_storage = os.environ['intermediateStorageS3']
    logger.info('Prize Zone lambda triggered by: ')
    logger.info(event)
    s3 = event['Records'][0]['s3']
    s3_object_key = unquote_plus(s3['object']['key'])
    s3_path = "s3://" + s3['bucket']['name'] + "/" + s3_object_key
    etl_timestamp = str(int(time.time()))
    partial_load_prefixes_key = '/CP/' + env + '/ETL/REF_PRICE/PRICE_ZONE/PARTIAL_LOAD_PREFIXES'
    partial_load_prefixes_val = get_values_from_ssm([partial_load_prefixes_key])
    partial_load = is_partial_load(s3_object_key, partial_load_prefixes_val[partial_load_prefixes_key])

    active_opcos_key = '/CP/' + env + '/ETL/REF_PRICE/PRICE_ZONE/ACTIVE/BUSINESS/UNITS'

    # here file name is not included to the path to prevent errors from filenames containing special characters
    unique_path_prefix = 'etl_output_' + etl_timestamp + '_' \
                         + str(uuid.uuid4())  # generate unique Id to handle concurrent uploads
    etl_worker_type_key = '/CP/' + env + '/ETL/REF_PRICE/PRICE_ZONE/WORKER_TYPE'
    if partial_load:
        custom_path = 'new/' + unique_path_prefix
        folder_key = 'price_zone/' + custom_path
        min_worker_count_key = '/CP/' + env + '/ETL/REF_PRICE/PRICE_ZONE/WORKER_COUNT/MIN'
        ssm_keys = [min_worker_count_key, etl_worker_type_key, active_opcos_key]
        ssm_key_values = get_values_from_ssm(ssm_keys)
        glue_NumberOfWorkers = int(ssm_key_values[min_worker_count_key])
        glue_worker_type = ssm_key_values[etl_worker_type_key]
        active_opco_list = ssm_key_values[active_opcos_key]
    else:  # handle full load
        custom_path = 'all/' + unique_path_prefix
        folder_key = 'price_zone/' + custom_path
        max_worker_count_key = '/CP/' + env + '/ETL/REF_PRICE/PRICE_ZONE/WORKER_COUNT/MAX'
        ssm_keys = [max_worker_count_key, etl_worker_type_key, active_opcos_key]
        ssm_key_values = get_values_from_ssm(ssm_keys)
        glue_NumberOfWorkers = int(ssm_key_values[max_worker_count_key])
        glue_worker_type = ssm_key_values[etl_worker_type_key]
        active_opco_list = ssm_key_values[active_opcos_key]

    if glue_NumberOfWorkers == 0:
        error_msg = 'Received illegal value for glue_NumberOfWorkers: {}'.format(glue_NumberOfWorkers)
        raise ValueError(error_msg)

    intermediate_directory_path = "s3://" + intermediate_s3_storage + "/" + folder_key
    decompressed_file_path = intermediate_directory_path + "/decompress.csv"
    partitioned_files_key = folder_key + "/partitioned"
    partitioned_files_path = intermediate_directory_path + "/partitioned/"

    params = {
        "s3_path": s3_path,
        "intermediate_s3_name": intermediate_s3_storage,
        "partitioned_files_path": partitioned_files_path,
        "decompressed_file_path": decompressed_file_path,
        "partitioned_files_key": partitioned_files_key,
        "etl_timestamp": etl_timestamp,
        "etl_output_path_key": custom_path,
        "s3_input_bucket": s3['bucket']['name'],
        "s3_input_file_key": s3_object_key,
        "partial_load": partial_load,
        "worker_count": glue_NumberOfWorkers,
        "worker_type": glue_worker_type,
        "active_opcos": active_opco_list,
        "intermediate_directory_path": folder_key
    }

    logger.info("Prize Zone data file Path: {}".format(s3_path))
    logger.info("Prize Zone data intermediate s3 storage:{}".format(intermediate_s3_storage))
    response = client_step_function.start_execution(
        stateMachineArn=step_function_arn,
        input=json.dumps(params)
    )
    logger.info('Started the Step Function: {}'.format(step_function_arn))
    logger.info('Started at:' + str(response['startDate']))
    return {
        'arn': response['executionArn'],
        'startDate': str(response['startDate'])
    }
