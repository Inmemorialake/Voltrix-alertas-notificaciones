"""Genera la colección y los entornos de Postman (formato v2.1)."""
import json, sys, uuid
from pathlib import Path

DEST = Path(sys.argv[1])

def lectura(activo, planta, tipo, metrica, valor, unidad, seg):
    d = {"plantaId": planta, "activoId": activo}
    if tipo:
        d["tipoActivo"] = tipo
    d |= {"fechaHora": f"2026-11-25T13:05:{seg:02d}Z", "metrica": metrica, "valor": valor, "unidad": unidad}
    return d

COMUNES = r"""
pm.test("X-Request-Id es un uuid", () => {
  pm.expect(pm.response.headers.get("X-Request-Id")).to.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
});
pm.test("Responde en menos de 2 s", () => pm.expect(pm.response.responseTime).to.be.below(2000));
"""

ERROR = r"""
const e = pm.response.json();
pm.test("Esquema común Error", () => {
  ["codigo", "mensaje", "requestId"].forEach(k => pm.expect(e).to.have.property(k));
  Object.keys(e).forEach(k => pm.expect(["codigo", "mensaje", "requestId", "detalles"]).to.include(k));
  pm.expect(e.codigo).to.match(/^[A-Z_]+$/);
  pm.expect(e.requestId).to.eql(pm.response.headers.get("X-Request-Id"));
});
"""

def peticion(nombre, metodo, ruta, query=None, cuerpo=None, headers=None, tests="", descripcion="", raw=None):
    url_raw = "{{baseUrl}}" + ruta + ("?" + "&".join(f"{k}={v}" for k, v in query) if query else "")
    url = {"raw": url_raw, "host": ["{{baseUrl}}"], "path": [p for p in ruta.strip("/").split("/")]}
    if query:
        url["query"] = [{"key": k, "value": str(v)} for k, v in query]
    hdrs = [{"key": "X-Equipo-Consumidor", "value": "{{equipoConsumidor}}"}] if headers is None else headers
    req = {"method": metodo, "header": list(hdrs), "url": url, "description": descripcion}
    if cuerpo is not None or raw is not None:
        req["header"].append({"key": "Content-Type", "value": "application/json"})
        req["body"] = {"mode": "raw", "raw": raw if raw is not None else json.dumps(cuerpo, ensure_ascii=False, indent=2),
                       "options": {"raw": {"language": "json"}}}
    return {"name": nombre, "event": [{"listen": "test", "script": {"type": "text/javascript",
            "exec": (COMUNES + tests).strip().splitlines()}}], "request": req}

LOTE_CRITICO = {"lecturas": [lectura("PL-002-BB-01", "PL-002", "banco_baterias", "temperatura", v, "C", s)
                             for v, s in ((46.3, 0), (47.1, 10), (45.9, 20))]}
LOTE_MIXTO = {"lecturas": [
    *[lectura("PL-041-TB-03", "PL-041", None, "velocidad_viento", v, "m/s", s) for v, s in ((2.1, 0), (1.5, 10), (2.8, 20))],
    *[lectura("PL-001-PS-07", "PL-001", "panel_solar", "potencia", v, "W", s) for v, s in ((1000, 0), (1010, 5), (990, 10), (1005, 15), (520, 30), (510, 40), (530, 50))],
    lectura("PL-002-BB-01", "PL-002", "banco_baterias", "temperatura", 41.0, "C", 30),
]}

operacion = [
    peticion("GET /health", "GET", "/health", headers=[], descripcion="Salud del servicio y de su base de datos (esquema común `Salud`).", tests=r"""
pm.test("200 disponible", () => {
  pm.response.to.have.status(200);
  const s = pm.response.json();
  pm.expect(s.estado).to.eql("disponible");
  pm.expect(s.baseDatos).to.eql("ok");
  pm.expect(s).to.have.property("tiempoActivoSeg");
});"""),
    peticion("GET /openapi.yaml", "GET", "/openapi.yaml", headers=[], descripcion="Contrato servido tal cual.", tests=r"""
pm.test("200 application/yaml", () => {
  pm.response.to.have.status(200);
  pm.expect(pm.response.headers.get("Content-Type")).to.include("application/yaml");
  pm.expect(pm.response.text()).to.include("openapi: 3.0.3");
});"""),
]

estado = [
    peticion("Estado vigente (Equipo 6)", "GET", "/alertas/estado", descripcion="Lo que consume Mantenimiento Predictivo: solo activas, con `porSeveridad` y `resumenPorActivo`.", tests=r"""
const d = pm.response.json();
pm.test("200 con forma EstadoAlertas", () => {
  pm.response.to.have.status(200);
  pm.expect(d).to.include.keys("generadoEn","totalActivas","porSeveridad","resumenPorActivo","datos","total","limit","offset");
});
pm.test("Solo alertas activas", () => d.datos.forEach(a => pm.expect(a.estado).to.eql("activa")));
pm.test("totalActivas = advertencia + critica", () => pm.expect(d.totalActivas).to.eql(d.porSeveridad.advertencia + d.porSeveridad.critica));
pm.test("resumenPorActivo trae activas y criticas", () => d.resumenPorActivo.forEach(r => pm.expect(r).to.have.all.keys("plantaId","activoId","activas","criticas")));"""),
    peticion("Filtrar por planta PL-041", "GET", "/alertas/estado", query=[("plantaId", "PL-041")], tests=r"""
pm.test("Solo PL-041", () => pm.response.json().datos.forEach(a => pm.expect(a.plantaId).to.eql("PL-041")));"""),
    peticion("Filtrar por severidad crítica", "GET", "/alertas/estado", query=[("severidad", "critica")], tests=r"""
pm.test("Solo críticas", () => pm.response.json().datos.forEach(a => pm.expect(a.severidad).to.eql("critica")));"""),
    peticion("Historial de un activo (estado=todas)", "GET", "/alertas/estado", query=[("activoId", "PL-002-BB-01"), ("estado", "todas")], tests=r"""
const d = pm.response.json();
pm.test("Incluye activas y resueltas", () => {
  const estados = new Set(d.datos.map(a => a.estado));
  pm.expect([...estados]).to.include("resuelta");
});"""),
    peticion("Paginación (limit=2, offset=2)", "GET", "/alertas/estado", query=[("estado", "todas"), ("limit", 2), ("offset", 2)], tests=r"""
const d = pm.response.json();
pm.test("Página de 2 y total sin paginar", () => {
  pm.expect(d.datos.length).to.be.at.most(2);
  pm.expect(d.limit).to.eql(2);
  pm.expect(d.offset).to.eql(2);
  pm.expect(d.total).to.be.at.least(d.datos.length);
});"""),
]

evaluar = [
    peticion("Lote: sobrecalentamiento de batería (crítica)", "POST", "/alertas", query=[("modo", "paralelo"), ("workers", 4)], cuerpo=LOTE_CRITICO,
             descripcion="3 lecturas sobre 45 °C del mismo banco: crea 1 alerta crítica con `ocurrencias: 3`.", tests=r"""
const r = pm.response.json();
pm.test("200 con 1 alerta crítica", () => {
  pm.response.to.have.status(200);
  pm.expect(r.alertasNuevas).to.eql(1);
  pm.expect(r.alertas[0]).to.include({activoId: "PL-002-BB-01", severidad: "critica", ocurrencias: 3, umbralAplicado: 45});
});
pm.test("MetricasProcesamiento", () => pm.expect(r.metricas).to.include({modo: "paralelo", workers: 4, elementos: 3}));"""),
    peticion("Lote mixto: turbina y panel (secuencial)", "POST", "/alertas", query=[("modo", "secuencial")], cuerpo=LOTE_MIXTO,
             descripcion="Turbina sin `tipoActivo` (se deduce de `TB`) con viento < 3 m/s, y panel cuya potencia cae ~48 % frente a su mediana.", tests=r"""
const r = pm.response.json();
pm.test("200 con turbina crítica y caída de panel", () => {
  pm.response.to.have.status(200);
  const porActivo = Object.fromEntries(r.alertas.map(a => [a.activoId + "/" + a.metrica, a]));
  pm.expect(porActivo["PL-041-TB-03/velocidad_viento"]).to.include({tipoActivo: "turbina", severidad: "critica"});
  pm.expect(porActivo["PL-001-PS-07/caida_potencia"]).to.include({tipoActivo: "panel_solar"});
});
pm.test("Secuencial usa 1 worker", () => pm.expect(r.metricas).to.include({modo: "secuencial", workers: 1, elementos: 11}));"""),
    peticion("Desde Telemetría (plantaId + ventana)", "POST", "/alertas", cuerpo={"plantaId": "PL-002", "desde": "2026-11-25T12:00:00Z", "hasta": "2026-11-25T13:00:00Z"},
             descripcion="Sin `TELEMETRIA_URL` el servicio usa lecturas de ejemplo; con ella, consulta al Equipo 2.", tests=r"""
pm.test("200 con lecturas evaluadas", () => {
  pm.response.to.have.status(200);
  pm.expect(pm.response.json().lecturasEvaluadas).to.be.above(0);
});"""),
]

errores = [
    peticion("400: lecturas y plantaId a la vez", "POST", "/alertas", cuerpo={**LOTE_CRITICO, "plantaId": "PL-002"}, tests=ERROR + r"""
pm.test("400 SOLICITUD_INVALIDA en 'lecturas'", () => {
  pm.response.to.have.status(400);
  pm.expect(e.codigo).to.eql("SOLICITUD_INVALIDA");
  pm.expect(e.detalles.map(d => d.campo)).to.include("lecturas");
});"""),
    peticion("400: fecha sin zona horaria", "POST", "/alertas",
             cuerpo={"lecturas": [lectura("PL-002-BB-01", "PL-002", "banco_baterias", "temperatura", 46.3, "C", 0) | {"fechaHora": "2026-11-25T13:05:00"}]},
             tests=ERROR + r"""
pm.test("400 en lecturas[0].fechaHora", () => {
  pm.response.to.have.status(400);
  pm.expect(e.detalles.map(d => d.campo)).to.include("lecturas[0].fechaHora");
});"""),
    peticion("400: JSON malformado", "POST", "/alertas", raw='{"lecturas": [', tests=ERROR + r"""
pm.test("400 SOLICITUD_INVALIDA", () => pm.response.to.have.status(400));"""),
    peticion("400: limit fuera de rango", "GET", "/alertas/estado", query=[("limit", 500)], tests=ERROR + r"""
pm.test("400 en limit", () => {
  pm.response.to.have.status(400);
  pm.expect(e.detalles[0].campo).to.eql("limit");
});"""),
    peticion("400: X-Equipo-Consumidor inválido", "GET", "/alertas/estado", headers=[{"key": "X-Equipo-Consumidor", "value": "equipo-9"}], tests=ERROR + r"""
pm.test("400 en X-Equipo-Consumidor", () => {
  pm.response.to.have.status(400);
  pm.expect(e.detalles[0].campo).to.eql("X-Equipo-Consumidor");
});"""),
    peticion("404: ruta inexistente", "GET", "/no-existe", headers=[], tests=ERROR + r"""
pm.test("404 NO_ENCONTRADO", () => {
  pm.response.to.have.status(404);
  pm.expect(e.codigo).to.eql("NO_ENCONTRADO");
});"""),
]

coleccion = {
    "info": {
        "_postman_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "voltrix-alertas-postman")),
        "name": "Voltrix · Alertas y Notificaciones (Equipo 3)",
        "description": "Peticiones del contrato `openapi.yaml` con pruebas automáticas. Elija un entorno (EC2, EC2 por túnel SSH o Local) y ejecute la colección con *Run*. Guía en `postman/README.md`.",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        {"name": "1. Operación", "item": operacion},
        {"name": "2. Estado de alertas", "item": estado},
        {"name": "3. Evaluar lotes", "item": evaluar},
        {"name": "4. Errores del contrato", "item": errores},
    ],
    "variable": [{"key": "equipoConsumidor", "value": "equipo-6"}],
}

def entorno(nombre, base):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, nombre)), "name": nombre,
            "values": [{"key": "baseUrl", "value": base, "type": "default", "enabled": True},
                       {"key": "equipoConsumidor", "value": "equipo-6", "type": "default", "enabled": True}],
            "_postman_variable_scope": "environment"}

DEST.mkdir(parents=True, exist_ok=True)
(DEST / "voltrix-alertas.postman_collection.json").write_text(json.dumps(coleccion, ensure_ascii=False, indent=2) + "\n")
for archivo, nombre, base in (("ec2", "Voltrix Alertas · EC2", "http://voltrix-alertas.inmemorialake.dev:8080"),
                              ("ec2-tunel", "Voltrix Alertas · EC2 por túnel SSH", "http://localhost:18080"),
                              ("local", "Voltrix Alertas · Local", "http://localhost:8080")):
    (DEST / f"{archivo}.postman_environment.json").write_text(json.dumps(entorno(nombre, base), ensure_ascii=False, indent=2) + "\n")
print("ok", sum(len(g["item"]) for g in coleccion["item"]), "peticiones")
