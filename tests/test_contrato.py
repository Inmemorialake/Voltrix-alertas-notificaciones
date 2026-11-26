"""Respuestas de la API validadas contra openapi.yaml."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from app.config import Config
from app.main import create_app
from conftest import RAIZ, RepositorioFalso, solo_en_proceso

LECTURA_BB = {"plantaId": "PL-002", "activoId": "PL-002-BB-01", "tipoActivo": "banco_baterias",
              "metrica": "temperatura", "unidad": "C"}


def lecturas_bateria(valores: list[float]) -> list[dict]:
    return [LECTURA_BB | {"fechaHora": f"2026-11-25T13:05:{i * 10:02d}Z", "valor": v} for i, v in enumerate(valores)]


def assert_error(resp: httpx.Response, status: int, codigo: str) -> dict:
    assert resp.status_code == status, resp.text
    cuerpo = resp.json()
    assert cuerpo["codigo"] == codigo
    assert cuerpo["requestId"] == resp.headers["X-Request-Id"]
    return cuerpo


# ---------------------------------- operación ----------------------------------
def test_health_disponible(cliente, validar):
    resp = validar(cliente.get("/health"))
    assert resp.status_code == 200
    assert resp.json()["estado"] == "disponible"
    assert resp.json()["baseDatos"] == "ok"


def test_toda_respuesta_lleva_request_id_uuid(cliente):
    ids = set()
    for ruta in ("/health", "/openapi.yaml", "/alertas/estado", "/no-existe"):
        rid = cliente.get(ruta).headers["X-Request-Id"]
        uuid.UUID(rid)
        ids.add(rid)
    assert len(ids) == 4


def test_openapi_yaml_se_sirve_tal_cual(cliente):
    # openapi-core no decodifica cuerpos application/yaml; se compara byte a byte con el archivo.
    resp = cliente.get("/openapi.yaml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/yaml")
    assert resp.content == (RAIZ / "openapi.yaml").read_bytes()


def test_ruta_inexistente_usa_esquema_error(cliente):
    assert_error(cliente.get("/no-existe"), 404, "NO_ENCONTRADO")


# --------------------------------- POST /alertas --------------------------------
def test_evaluar_lote_crea_alerta_critica(cliente, validar):
    resp = validar(cliente.post("/alertas", json={"lecturas": lecturas_bateria([46.3, 47.0, 45.8, 39.0])},
                                headers={"X-Equipo-Consumidor": "equipo-6"}))
    assert resp.status_code == 200
    cuerpo = resp.json()
    assert cuerpo["lecturasEvaluadas"] == 4
    assert cuerpo["alertasNuevas"] == 1
    alerta = cuerpo["alertas"][0]
    assert (alerta["activoId"], alerta["severidad"], alerta["ocurrencias"]) == ("PL-002-BB-01", "critica", 3)
    assert alerta["umbralAplicado"] == 45
    assert cuerpo["metricas"] == {"modo": "paralelo", "workers": 4, "elementos": 4,
                                  "duracionMs": cuerpo["metricas"]["duracionMs"]}


def test_menos_de_tres_violaciones_no_crea_alerta(cliente, validar):
    resp = validar(cliente.post("/alertas", json={"lecturas": lecturas_bateria([46.3, 47.0])}))
    assert resp.json()["alertasNuevas"] == 0


def test_tipo_se_deduce_del_id_y_turbina_fuera_de_rango(cliente, validar):
    lecturas = [{"plantaId": "PL-041", "activoId": "PL-041-TB-03", "fechaHora": f"2026-11-25T13:0{i}:00Z",
                 "metrica": "velocidad_viento", "valor": v, "unidad": "m/s"} for i, v in enumerate([2.1, 1.5, 2.8])]
    alerta = validar(cliente.post("/alertas", json={"lecturas": lecturas})).json()["alertas"][0]
    assert (alerta["tipoActivo"], alerta["severidad"], alerta["umbralAplicado"]) == ("turbina", "critica", 3)


def test_modo_secuencial_usa_un_worker(cliente, validar):
    resp = validar(cliente.post("/alertas?modo=secuencial&workers=8", json={"lecturas": lecturas_bateria([41])}))
    assert resp.json()["metricas"]["modo"] == "secuencial"
    assert resp.json()["metricas"]["workers"] == 1


def test_modo_paralelo_respeta_workers(cliente, validar):
    resp = validar(cliente.post("/alertas?modo=paralelo&workers=8", json={"lecturas": lecturas_bateria([41])}))
    assert resp.json()["metricas"]["workers"] == 8


def test_evaluar_desde_telemetria(cliente, validar):
    cuerpo = {"plantaId": "PL-002", "desde": "2026-11-25T12:00:00Z", "hasta": "2026-11-25T13:00:00Z"}
    resp = validar(cliente.post("/alertas", json=cuerpo))
    assert resp.status_code == 200
    assert resp.json()["lecturasEvaluadas"] > 0


@pytest.mark.parametrize(
    ("cuerpo", "campo"),
    [
        ({"lecturas": lecturas_bateria([46]), "plantaId": "PL-002"}, "lecturas"),
        ({}, "plantaId"),
        ({"plantaId": "PL-002", "desde": "2026-11-25T12:00:00Z"}, "hasta"),
        ({"plantaId": "PL-002", "desde": "2026-11-25T13:00:00Z", "hasta": "2026-11-25T12:00:00Z"}, "hasta"),
        ({"lecturas": []}, "lecturas"),
        ({"lecturas": [LECTURA_BB | {"fechaHora": "2026-11-25T13:05:00", "valor": 1}]}, "lecturas[0].fechaHora"),
        ({"lecturas": [LECTURA_BB | {"fechaHora": "2026-11-25T13:05:00Z", "valor": "alto"}]}, "lecturas[0].valor"),
        ({"lecturas": [LECTURA_BB | {"fechaHora": "2026-11-25T13:05:00Z", "valor": 1, "extra": 1}]}, "lecturas[0].extra"),
        ({"lecturas": [LECTURA_BB | {"activoId": "PL 002", "fechaHora": "2026-11-25T13:05:00Z", "valor": 1}]}, "lecturas[0].activoId"),
    ],
)
def test_cuerpo_invalido_400(cliente, validar, cuerpo, campo):
    cuerpo_error = assert_error(validar(cliente.post("/alertas", json=cuerpo)), 400, "SOLICITUD_INVALIDA")
    assert campo in [d["campo"] for d in cuerpo_error["detalles"]]


def test_json_malformado_400(cliente, validar):
    resp = cliente.post("/alertas", content=b"{no es json", headers={"Content-Type": "application/json"})
    assert_error(resp, 400, "SOLICITUD_INVALIDA")


@pytest.mark.parametrize("query", ["modo=turbo", "workers=0", "workers=65"])
def test_parametros_invalidos_400(cliente, validar, query):
    resp = validar(cliente.post(f"/alertas?{query}", json={"lecturas": lecturas_bateria([41])}))
    assert_error(resp, 400, "SOLICITUD_INVALIDA")


def test_equipo_consumidor_invalido_400(cliente, validar):
    resp = validar(cliente.get("/alertas/estado", headers={"X-Equipo-Consumidor": "equipo-9"}))
    cuerpo = assert_error(resp, 400, "SOLICITUD_INVALIDA")
    assert cuerpo["detalles"][0]["campo"] == "X-Equipo-Consumidor"


# ----------------------------- GET /alertas/estado ------------------------------
def test_estado_por_defecto_solo_activas(cliente, validar):
    cuerpo = validar(cliente.get("/alertas/estado", headers={"X-Equipo-Consumidor": "equipo-6"})).json()
    assert cuerpo["totalActivas"] == 4
    assert cuerpo["porSeveridad"] == {"advertencia": 2, "critica": 2}
    assert cuerpo["total"] == 4
    assert {d["estado"] for d in cuerpo["datos"]} == {"activa"}
    assert cuerpo["resumenPorActivo"] == [
        {"plantaId": "PL-001", "activoId": "PL-001-PS-07", "activas": 1, "criticas": 0},
        {"plantaId": "PL-002", "activoId": "PL-002-BB-01", "activas": 1, "criticas": 1},
        {"plantaId": "PL-041", "activoId": "PL-041-TB-03", "activas": 2, "criticas": 1},
    ]
    assert (cuerpo["limit"], cuerpo["offset"]) == (50, 0)


@pytest.mark.parametrize(
    ("query", "total", "ids"),
    [
        ("plantaId=PL-041", 2, {"ALR-20261125-003", "ALR-20261125-004"}),
        ("activoId=PL-002-BB-01&estado=todas", 2, {"ALR-20261125-001", "ALR-20261124-001"}),
        ("severidad=critica", 2, {"ALR-20261125-001", "ALR-20261125-003"}),
        ("estado=resuelta", 2, {"ALR-20261124-001", "ALR-20261124-002"}),
        ("estado=todas", 6, None),
        ("plantaId=PL-999", 0, set()),
    ],
)
def test_estado_filtros(cliente, validar, query, total, ids):
    cuerpo = validar(cliente.get(f"/alertas/estado?{query}")).json()
    assert cuerpo["total"] == total
    if ids is not None:
        assert {d["id"] for d in cuerpo["datos"]} == ids


def test_estado_paginacion(cliente, validar):
    completo = cliente.get("/alertas/estado?estado=todas").json()["datos"]
    pagina = validar(cliente.get("/alertas/estado?estado=todas&limit=2&offset=2")).json()
    assert pagina["total"] == 6
    assert [d["id"] for d in pagina["datos"]] == [d["id"] for d in completo[2:4]]
    # resumenPorActivo no se pagina.
    assert len(pagina["resumenPorActivo"]) == 3


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "severidad=media", "estado=x", "plantaId=PL%20001"])
def test_estado_parametros_invalidos_400(cliente, validar, query):
    assert_error(validar(cliente.get(f"/alertas/estado?{query}")), 400, "SOLICITUD_INVALIDA")


# ------------------------- fallos de base de datos y carga ------------------------
@solo_en_proceso
def test_health_503_sin_base_datos(cliente, repo, validar):
    repo.caido = True
    resp = validar(cliente.get("/health"))
    assert resp.status_code == 503
    assert resp.json()["estado"] == "no_disponible"
    assert resp.json()["baseDatos"] == "error"


@solo_en_proceso
def test_estado_503_sin_base_datos(cliente, repo, validar):
    repo.caido = True
    assert_error(validar(cliente.get("/alertas/estado")), 503, "NO_DISPONIBLE")


@solo_en_proceso
def test_sobrecarga_429_con_retry_after(contrato, validar):
    app = create_app(Config(max_concurrencia=1), repositorio=RepositorioFalso(retardo=0.3))

    async def disparar():
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://localhost:8080") as c:
            return await asyncio.gather(*(c.get("/alertas/estado") for _ in range(3)),
                                        c.get("/health"))

    *consultas, salud = asyncio.run(disparar())
    estados = sorted(r.status_code for r in consultas)
    assert estados == [200, 429, 429]
    for r in consultas:
        validar(r)
        if r.status_code == 429:
            assert r.headers["Retry-After"] == "1"
            assert r.json()["codigo"] == "SOBRECARGA"
    # /health no cuenta contra el límite.
    assert salud.status_code == 200
