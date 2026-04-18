SHOW CATALOGS;
SHOW NAMESPACES IN unity;
SHOW TABLES IN unity.default;

CREATE TABLE IF NOT EXISTS unity.default.smoke_delta (
	id INT,
	note STRING
)
USING DELTA
LOCATION 's3://warehouse/smoke_delta';
