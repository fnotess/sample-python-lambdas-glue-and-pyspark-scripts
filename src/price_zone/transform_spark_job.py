import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame
from pyspark.sql.functions import substring, col, expr, to_date
from pyspark.sql.types import IntegerType
from validator import validate_column, validate_column_length, validate_data_range, validate_date_format, validate_and_get_as_date
from constants import CO_CUST_NBR_LENGTH, SUPC_LENGTH, PRICE_ZONE_MIN_VALUE, PRICE_ZONE_MAX_VALUE, DATE_FORMAT_REGEX, INPUT_DATE_FORMAT

## @params: [JOB_NAME]
args = getResolvedOptions(sys.argv, ['JOB_NAME'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)


datasource0 = glueContext.create_dynamic_frame_from_options(connection_type="s3", connection_options={
    'paths': ["s3://cp-ref-price-poc-bucket/_fin_cust_pz_df.csv.gz"], "compressionType": "gzip"}, format="csv",
                                                            format_options={"separator": ",", 'withHeader': True},
                                                            transformation_ctx="datasource0")

# renaming columns and dropping off unnecessary columns
applyMapping1 = ApplyMapping.apply(frame=datasource0, mappings=[("co_cust_nbr", "bigint", "co_cust_nbr", "string"),
                                                                ("supc", "bigint", "supc", "string"),
                                                                ("prc_zone", "bigint", "price_zone", "string"),
                                                                ("effective_date", "string", "effective_date_str", "string")],
                                   transformation_ctx="applyMapping1")
sparkDF = applyMapping1.toDF()

# validate data
validate_column(sparkDF, 'co_cust_nbr')
validate_column(sparkDF, 'supc')
validate_column(sparkDF, 'price_zone')
validate_date_format(sparkDF, 'effective_date', DATE_FORMAT_REGEX)

validate_column_length(sparkDF, 'co_cust_nbr', CO_CUST_NBR_LENGTH)
validate_column_length(sparkDF, 'supc', SUPC_LENGTH)

sparkDF = sparkDF.withColumn("price_zone", sparkDF["price_zone"].cast(IntegerType()))
validate_data_range(sparkDF, 'price_zone', PRICE_ZONE_MIN_VALUE, PRICE_ZONE_MAX_VALUE)

#creating new dataframe containing customer_id from co_cust_nbr
sparkDF = sparkDF.withColumn("customer_id", substring(col("co_cust_nbr"), -6, 6))

#creating new dataframe containing opco_id from co_cust_nbr
sparkDF = sparkDF.withColumn("opco_id", expr("substring(co_cust_nbr, 0, length(co_cust_nbr)-6)"))

sparkDF = validate_and_get_as_date(sparkDF, 'effective_date_str', 'effective_date', INPUT_DATE_FORMAT)

convertedDynamicFrame = DynamicFrame.fromDF(sparkDF, glueContext, "convertedDynamicFrame")

#drop co_cust_nbr
customer_nb_dropped_dynamicdataframe = DropFields.apply(frame = convertedDynamicFrame, paths = ["co_cust_nbr", "effective_date_str"], transformation_ctx = "customer_nb_dropped_dynamicdataframe")

#save dataframe to s3, partitioned per OPCO
datasink2 = glueContext.write_dynamic_frame.from_options(frame=customer_nb_dropped_dynamicdataframe, connection_type="s3", connection_options={"path": "s3://cp-ref-price-poc-bucket/output/glue_output_partioned/", "partitionKeys": ["opco_id"]}, format="csv", transformation_ctx="datasink2")

job.commit()