-- Seed mock telemetry data for turbine_maintenance_input (29 physical SCADA features + turbine_id)
-- References real turbine IDs (1..12) across registered Romanian wind parks

-- Turbine 1 (Park 1, Fântânele): Critical Generator Drive-End Bearing Overheating
INSERT INTO turbine_maintenance_input (
    turbine_id, sensor_0_avg, wind_speed_3_avg, sensor_18_avg, power_30_avg, sensor_5_avg, sensor_52_avg,
    thermal_lift_bearing_de, thermal_lift_bearing_nde, bearing_temp_ratio, thermal_lift_gearbox_bearing,
    thermal_lift_gearbox_oil, thermal_lift_hydraulic_oil, thermal_lift_transformer, transformer_phase_imbalance,
    thermal_lift_stator, stator_phase_imbalance, bearing_de_roll_mean_6h, bearing_de_roll_std_6h,
    bearing_de_roll_max_6h, bearing_de_drift_24h, gearbox_oil_roll_mean_6h, gearbox_oil_roll_std_6h,
    gearbox_bearing_drift_24h, hydraulic_oil_roll_mean_6h, hydraulic_oil_drift_24h, transformer_roll_mean_6h,
    transformer_drift_24h, gearbox_speed_ratio, rpm_deviation
) VALUES (
    1, 17.56, 7.62, 1317.2, 236.2, 0.0, 13.18,
    67.25, 18.60, 2.35, 28.64,
    23.98, 19.17, 38.29, 2.41,
    31.14, 1.25, 73.62, 6.66,
    87.46, 24.25, 39.04, 1.63,
    -0.02, 32.96, -0.22, 36.87,
    -0.71, 99.94, 402.80
);

-- Turbine 2 (Park 1, Fântânele): Healthy Baseline Operation
INSERT INTO turbine_maintenance_input (
    turbine_id, sensor_0_avg, wind_speed_3_avg, sensor_18_avg, power_30_avg, sensor_5_avg, sensor_52_avg,
    thermal_lift_bearing_de, thermal_lift_bearing_nde, bearing_temp_ratio, thermal_lift_gearbox_bearing,
    thermal_lift_gearbox_oil, thermal_lift_hydraulic_oil, thermal_lift_transformer, transformer_phase_imbalance,
    thermal_lift_stator, stator_phase_imbalance, bearing_de_roll_mean_6h, bearing_de_roll_std_6h,
    bearing_de_roll_max_6h, bearing_de_drift_24h, gearbox_oil_roll_mean_6h, gearbox_oil_roll_std_6h,
    gearbox_bearing_drift_24h, hydraulic_oil_roll_mean_6h, hydraulic_oil_drift_24h, transformer_roll_mean_6h,
    transformer_drift_24h, gearbox_speed_ratio, rpm_deviation
) VALUES (
    2, 18.25, 7.66, 1337.5, 238.2, 0.0, 13.16,
    23.31, 20.28, 1.08, 28.73,
    25.03, 18.22, 37.36, 1.41,
    33.48, 2.40, 36.76, 1.91,
    41.56, -0.00, 38.96, 1.87,
    1.06, 33.18, -0.45, 36.99,
    -1.52, 101.63, 418.30
);

-- Turbine 3 (Park 1, Fântânele): Hydraulic Pitch Group Warning
INSERT INTO turbine_maintenance_input (
    turbine_id, sensor_0_avg, wind_speed_3_avg, sensor_18_avg, power_30_avg, sensor_5_avg, sensor_52_avg,
    thermal_lift_bearing_de, thermal_lift_bearing_nde, bearing_temp_ratio, thermal_lift_gearbox_bearing,
    thermal_lift_gearbox_oil, thermal_lift_hydraulic_oil, thermal_lift_transformer, transformer_phase_imbalance,
    thermal_lift_stator, stator_phase_imbalance, bearing_de_roll_mean_6h, bearing_de_roll_std_6h,
    bearing_de_roll_max_6h, bearing_de_drift_24h, gearbox_oil_roll_mean_6h, gearbox_oil_roll_std_6h,
    gearbox_bearing_drift_24h, hydraulic_oil_roll_mean_6h, hydraulic_oil_drift_24h, transformer_roll_mean_6h,
    transformer_drift_24h, gearbox_speed_ratio, rpm_deviation
) VALUES (
    3, 18.78, 7.71, 1377.3, 264.3, -2.57, 13.87,
    23.34, 19.70, 1.09, 27.67,
    25.92, 46.53, 37.99, 2.28,
    33.18, 1.87, 37.61, 1.94,
    42.12, 0.24, 39.52, 2.13,
    0.23, 57.18, 13.77, 37.27,
    -1.08, 99.30, 452.10
);

-- Turbine 4 (Park 2, Chirnogeni): Gearbox High-Speed Shaft Wear
INSERT INTO turbine_maintenance_input (
    turbine_id, sensor_0_avg, wind_speed_3_avg, sensor_18_avg, power_30_avg, sensor_5_avg, sensor_52_avg,
    thermal_lift_bearing_de, thermal_lift_bearing_nde, bearing_temp_ratio, thermal_lift_gearbox_bearing,
    thermal_lift_gearbox_oil, thermal_lift_hydraulic_oil, thermal_lift_transformer, transformer_phase_imbalance,
    thermal_lift_stator, stator_phase_imbalance, bearing_de_roll_mean_6h, bearing_de_roll_std_6h,
    bearing_de_roll_max_6h, bearing_de_drift_24h, gearbox_oil_roll_mean_6h, gearbox_oil_roll_std_6h,
    gearbox_bearing_drift_24h, hydraulic_oil_roll_mean_6h, hydraulic_oil_drift_24h, transformer_roll_mean_6h,
    transformer_drift_24h, gearbox_speed_ratio, rpm_deviation
) VALUES (
    4, 18.02, 5.72, 1205.7, 45.7, 0.0, 12.15,
    20.94, 17.76, 1.09, 58.20,
    49.85, 18.76, 36.28, 2.54,
    30.41, 1.24, 37.04, 1.97,
    40.96, -2.61, 61.92, 3.63,
    12.80, 33.04, -0.25, 37.29,
    -2.96, 99.23, 519.30
);

-- Turbine 6 (Park 3, Casimcea): High-Voltage Transformer Severe Phase Imbalance
INSERT INTO turbine_maintenance_input (
    turbine_id, sensor_0_avg, wind_speed_3_avg, sensor_18_avg, power_30_avg, sensor_5_avg, sensor_52_avg,
    thermal_lift_bearing_de, thermal_lift_bearing_nde, bearing_temp_ratio, thermal_lift_gearbox_bearing,
    thermal_lift_gearbox_oil, thermal_lift_hydraulic_oil, thermal_lift_transformer, transformer_phase_imbalance,
    thermal_lift_stator, stator_phase_imbalance, bearing_de_roll_mean_6h, bearing_de_roll_std_6h,
    bearing_de_roll_max_6h, bearing_de_drift_24h, gearbox_oil_roll_mean_6h, gearbox_oil_roll_std_6h,
    gearbox_bearing_drift_24h, hydraulic_oil_roll_mean_6h, hydraulic_oil_drift_24h, transformer_roll_mean_6h,
    transformer_drift_24h, gearbox_speed_ratio, rpm_deviation
) VALUES (
    6, 16.49, 8.02, 1370.9, 290.6, 0.0, 13.76,
    22.55, 20.72, 1.05, 26.24,
    23.66, 18.69, 93.34, 25.81,
    31.93, 0.77, 36.92, 1.62,
    39.57, -2.41, 38.79, 1.68,
    -3.06, 32.76, -1.71, 84.84,
    26.21, 99.63, 408.50
);
