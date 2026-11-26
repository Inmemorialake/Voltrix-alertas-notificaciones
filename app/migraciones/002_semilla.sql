-- Datos de ejemplo del Avance 1. IDs según Inventario (Equipo 1).
-- Umbrales: supuestos del equipo (docs/diseno.md, sección 3).

INSERT INTO umbral (id, tipo_activo, metrica, operador, valor_advertencia, valor_critico, valor_critico_inferior, lecturas_minimas) VALUES
    ('UMB-BB-TEMPERATURA',  'banco_baterias', 'temperatura',      'gt',          40, 45, NULL, 3),
    ('UMB-PS-CAIDA',        'panel_solar',    'caida_potencia',   'gt',          20, 40, NULL, 3),
    ('UMB-TB-VIENTO',       'turbina',        'velocidad_viento', 'fuera_rango', 20, 25, 3,    3)
ON CONFLICT (id) DO NOTHING;

INSERT INTO alerta (id, umbral_id, planta_id, activo_id, tipo_activo, metrica, severidad, estado,
                    valor_observado, umbral_aplicado, ocurrencias, primera_deteccion, ultima_deteccion) VALUES
    ('ALR-20261125-001', 'UMB-BB-TEMPERATURA', 'PL-002', 'PL-002-BB-01', 'banco_baterias', 'temperatura',      'critica',     'activa',   46.3, 45, 3, '2026-11-25T13:05:00Z', '2026-11-25T13:05:20Z'),
    ('ALR-20261125-002', 'UMB-PS-CAIDA',       'PL-001', 'PL-001-PS-07', 'panel_solar',    'caida_potencia',   'advertencia', 'activa',   27.5, 20, 3, '2026-11-25T13:05:10Z', '2026-11-25T13:06:10Z'),
    ('ALR-20261125-003', 'UMB-TB-VIENTO',      'PL-041', 'PL-041-TB-03', 'turbina',        'velocidad_viento', 'critica',     'activa',   27.1, 25, 5, '2026-11-25T13:00:00Z', '2026-11-25T13:05:00Z'),
    ('ALR-20261125-004', 'UMB-TB-VIENTO',      'PL-041', 'PL-041-TB-03', 'turbina',        'velocidad_viento', 'advertencia', 'activa',   22.4, 20, 3, '2026-11-25T12:40:00Z', '2026-11-25T12:55:00Z'),
    ('ALR-20261124-001', 'UMB-BB-TEMPERATURA', 'PL-002', 'PL-002-BB-01', 'banco_baterias', 'temperatura',      'advertencia', 'resuelta', 41.8, 40, 4, '2026-11-24T09:10:00Z', '2026-11-24T09:40:00Z'),
    ('ALR-20261124-002', 'UMB-PS-CAIDA',       'PL-001', 'PL-001-PS-07', 'panel_solar',    'caida_potencia',   'critica',     'resuelta', 43.0, 40, 3, '2026-11-24T16:00:00Z', '2026-11-24T16:20:00Z')
-- Sin destino: tampoco falla si choca con el índice único parcial.
ON CONFLICT DO NOTHING;
