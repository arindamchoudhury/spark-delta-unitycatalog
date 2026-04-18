SHOW CATALOGS;
SHOW NAMESPACES IN unity;
SHOW TABLES IN unity.default;

CREATE TABLE IF NOT EXISTS unity.default.smoke_delta (
	id INT,
	note STRING
)
USING DELTA
LOCATION 's3://warehouse/smoke_delta';

DELETE FROM unity.default.smoke_delta;

INSERT INTO unity.default.smoke_delta VALUES (1, 'ok'), (2, 'delta+uc');
SELECT * FROM unity.default.smoke_delta ORDER BY id;
