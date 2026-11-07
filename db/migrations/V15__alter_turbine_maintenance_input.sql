ALTER TABLE turbine_maintenance_input
ADD COLUMN turbine_id BIGINT REFERENCES turbine(id);