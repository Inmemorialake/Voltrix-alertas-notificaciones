-- Esquema del servicio Alertas y Notificaciones (ver docs/diseno.md, sección 3).

CREATE TABLE IF NOT EXISTS umbral (
    id                      text PRIMARY KEY,
    tipo_activo             text NOT NULL CHECK (tipo_activo IN ('panel_solar', 'turbina', 'banco_baterias')),
    metrica                 text NOT NULL,
    operador                text NOT NULL CHECK (operador IN ('gt', 'lt', 'fuera_rango')),
    valor_advertencia       double precision NOT NULL,
    valor_critico           double precision NOT NULL,
    -- Solo para operador fuera_rango: límite inferior crítico (turbina: < 3 m/s).
    valor_critico_inferior  double precision,
    lecturas_minimas        integer NOT NULL DEFAULT 3 CHECK (lecturas_minimas >= 1),
    UNIQUE (tipo_activo, metrica)
);

CREATE TABLE IF NOT EXISTS alerta (
    id                 text PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9_-]{1,64}$'),
    umbral_id          text NOT NULL REFERENCES umbral (id),
    planta_id          text NOT NULL,
    activo_id          text NOT NULL,
    tipo_activo        text NOT NULL CHECK (tipo_activo IN ('panel_solar', 'turbina', 'banco_baterias')),
    metrica            text NOT NULL,
    severidad          text NOT NULL CHECK (severidad IN ('advertencia', 'critica')),
    estado             text NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'resuelta')),
    valor_observado    double precision,
    umbral_aplicado    double precision,
    ocurrencias        integer NOT NULL DEFAULT 1 CHECK (ocurrencias >= 1),
    primera_deteccion  timestamptz NOT NULL,
    ultima_deteccion   timestamptz NOT NULL,
    CHECK (ultima_deteccion >= primera_deteccion)
);

-- Clave de deduplicación: una sola alerta activa por (activo, métrica, severidad).
-- Es la protección entre réplicas: INSERT ... ON CONFLICT (Avance 2) se apoya en este índice.
CREATE UNIQUE INDEX IF NOT EXISTS alerta_activa_unica
    ON alerta (activo_id, metrica, severidad)
    WHERE estado = 'activa';

CREATE INDEX IF NOT EXISTS alerta_planta_estado ON alerta (planta_id, estado);
CREATE INDEX IF NOT EXISTS alerta_ultima_deteccion ON alerta (ultima_deteccion DESC);
