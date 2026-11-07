drop view upward_turbine_mentenance;

CREATE OR REPLACE VIEW upward_turbine_mentenance AS
SELECT tm.*, p.id as park_id, p.name as park_name
FROM turbine_mentenance tm
join turbine t on (t.id = tm.turbine_id)
join park p on (p.id = t.park_id) 
WHERE predicted_date > CURRENT_DATE and status <> 'NORMAL';