import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame
from pyspark.sql.types import IntegerType
from validator import validate_column, validate_column_length_less_than, validate_column_length_equals, validate_data_range, validate_date_format, validate_and_get_as_date
from constants import CUST_NBR_LENGTH, SUPC_LENGTH, PRICE_ZONE_MIN_VALUE, PRICE_ZONE_MAX_VALUE, DATE_FORMAT_REGEX, OUTPUT_DATE_FORMAT, INPUT_DATE_FORMAT, CO_NBR_LENGTH

## @params: [JOB_NAME]
args = getResolvedOptions(sys.argv, ['JOB_NAME', 'decompressed_file_path', 'partitioned_files_path'])
decompressed_file_path = args['decompressed_file_path']
partitioned_files_path = args['partitioned_files_path']
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)


datasource0 = glueContext.create_dynamic_frame_from_options(connection_type="s3", connection_options={
    'paths': [decompressed_file_path]}, format="csv",
                                                            format_options={"separator": ",", 'withHeader': True},
                                                            transformation_ctx="datasource0")

# renaming columns and dropping off unnecessary columns
applyMapping1 = ApplyMapping.apply(frame=datasource0, mappings=[("co_nbr", "string", "opco_id", "string"),
                                                                ("supc", "string", "supc", "string"),
                                                                ("prc_zone", "string", "price_zone", "string"),
                                                                ("cust_nbr", "string", "customer_id", "string"),
                                                                ("eff_from_dttm", "string", "eff_from_dttm", "string")],
                                   transformation_ctx="applyMapping1")
sparkDF = applyMapping1.toDF()

# validate data
validate_column(sparkDF, 'opco_id')
validate_column(sparkDF, 'customer_id')
validate_column(sparkDF, 'supc')
validate_column(sparkDF, 'price_zone')
validate_date_format(sparkDF, 'eff_from_dttm', DATE_FORMAT_REGEX, INPUT_DATE_FORMAT)

validate_column_length_less_than(sparkDF, 'customer_id', CUST_NBR_LENGTH)
validate_column_length_less_than(sparkDF, 'supc', SUPC_LENGTH)
validate_column_length_equals(sparkDF, 'opco_id', CO_NBR_LENGTH)

sparkDF = sparkDF.withColumn("price_zone", sparkDF["price_zone"].cast(IntegerType()))
validate_data_range(sparkDF, 'price_zone', PRICE_ZONE_MIN_VALUE, PRICE_ZONE_MAX_VALUE)

sparkDF = validate_and_get_as_date(sparkDF, 'eff_from_dttm', 'effective_date', OUTPUT_DATE_FORMAT)

convertedDynamicFrame = DynamicFrame.fromDF(sparkDF, glueContext, "convertedDynamicFrame")

# drop eff_from_dttm
dropped_dynamicdataframe = DropFields.apply(frame=convertedDynamicFrame, paths=["eff_from_dttm"],
                                            transformation_ctx="dropped_dynamicdataframe")

# save dataframe to s3, partitioned per OPCO
datasink2 = glueContext.write_dynamic_frame.from_options(frame=dropped_dynamicdataframe, connection_type="s3",
                                                         connection_options={"path": partitioned_files_path,
                                                                             "partitionKeys": ["opco_id"]},
                                                         format="csv", transformation_ctx="datasink2")

job.commit()
