ALTER TABLE employees
ADD COLUMN status text CHECK (status in ('AVAILABLE', 'DISPATCHED', 'OFF_SHIFT'));