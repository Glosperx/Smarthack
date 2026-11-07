CREATE OR REPLACE VIEW upward_turbine_mentenance AS
SELECT * 
FROM turbine_mentenance 
WHERE predicted_date > CURRENT_DATE and status <> 'NORMAL';