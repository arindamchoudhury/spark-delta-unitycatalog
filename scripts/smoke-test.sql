-- Metadata operations work against Unity Catalog on Spark 4.2.
SHOW CATALOGS;
SHOW NAMESPACES IN unity;
SHOW TABLES IN unity.default;

-- Disabled on Spark 4.2: the UC Spark connector is compiled against Spark 4.1
-- and no 4.2 build is published yet, so anything that resolves or creates a
-- table fails with NoSuchMethodError -- Spark 4.2 added multipartIdentifier to
-- CatalogTable and serdeName to CatalogStorageFormat. See the "Known
-- limitation" section in README.md. Re-enable once UC publishes
-- unitycatalog-spark_4.2_2.13.
--
-- CREATE TABLE IF NOT EXISTS unity.default.smoke_delta (
-- 	id INT,
-- 	note STRING
-- )
-- USING DELTA
-- LOCATION 's3://warehouse/smoke_delta';
