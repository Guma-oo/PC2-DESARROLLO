import os
import random
import string
import shutil
import functools
import asyncio
import copy
from datetime import datetime
from typing import Optional, List
from abc import ABC, abstractmethod

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pymongo import MongoClient

class ConexionBaseDatos:
    _instancia = None

    def __new__(cls):
        if cls._instancia is None:
            cls._instancia = super().__new__(cls)
            MONGO_URI = os.getenv(
                "MONGO_URI",
                "mongodb+srv://erickslonga24_db_user:ltg9xCcFwERsCsJL@todolistcluster.hrygcsc.mongodb.net/?appName=TodoListCluster"
            )
            cls._instancia.cliente        = MongoClient(MONGO_URI)
            cls._instancia.base           = cls._instancia.cliente["incidencias_db"]
            cls._instancia.incidencias    = cls._instancia.base["incidencias"]
            cls._instancia.notificaciones = cls._instancia.base["notificaciones"]
        return cls._instancia

    def verificar(self):
        self.cliente.admin.command("ping")

bd = ConexionBaseDatos()

class ObservadorBase(ABC):
    @abstractmethod
    def actualizar(self, evento: str, datos: dict): pass

class ObservadorBitacora(ObservadorBase):
    def actualizar(self, evento: str, datos: dict):
        registro = {"evento": evento, "datos": datos, "timestamp": datetime.now().isoformat()}
        bd.notificaciones.insert_one(registro)
        print(f"[BITÁCORA] {evento} → {datos.get('codigo_incidencia', '')}")

class ObservadorCorreo(ObservadorBase):
    def actualizar(self, evento: str, datos: dict):
        print(f"[CORREO] Notificando a {datos.get('correo', 'N/A')} — evento: {evento}")

class ObservadorFactory:
    @staticmethod
    def crear_observador(tipo: str) -> ObservadorBase:
        if tipo == "bitacora": return ObservadorBitacora()
        elif tipo == "correo": return ObservadorCorreo()
        else: raise ValueError(f"Tipo de observador desconocido: {tipo}")

class SistemaNotificaciones:
    def __init__(self):
        self._observadores: List[ObservadorBase] = []

    def suscribir(self, obs: ObservadorBase):
        self._observadores.append(obs)

    def notificar(self, evento: str, datos: dict):
        for obs in self._observadores:
            obs.actualizar(evento, datos)

notificador = SistemaNotificaciones()
notificador.suscribir(ObservadorFactory.crear_observador("bitacora"))
notificador.suscribir(ObservadorFactory.crear_observador("correo"))

class ValidadorCategoria(ABC):
    @abstractmethod
    def validar(self, categoria: str) -> bool: pass

class AsignadorPrioridad(ABC):
    @abstractmethod
    def obtener_prioridad_por_defecto(self) -> str: pass

class ValidadorEmergencia(ValidadorCategoria):
    def validar(self, cat: str): return cat in {"emergencia", "seguridad"}

class AsignadorEmergencia(AsignadorPrioridad):
    def obtener_prioridad_por_defecto(self): return "alta"

class ValidadorMantenimiento(ValidadorCategoria):
    def validar(self, cat: str): return cat in {"bache", "alumbrado", "basura"}

class AsignadorMantenimiento(AsignadorPrioridad):
    def obtener_prioridad_por_defecto(self): return "media"

class FabricaFlujoIncidencia(ABC):
    @abstractmethod
    def crear_validador(self) -> ValidadorCategoria: pass
    @abstractmethod
    def crear_asignador(self) -> AsignadorPrioridad: pass

class FabricaEmergencia(FabricaFlujoIncidencia):
    def crear_validador(self): return ValidadorEmergencia()
    def crear_asignador(self): return AsignadorEmergencia()

class FabricaMantenimiento(FabricaFlujoIncidencia):
    def crear_validador(self): return ValidadorMantenimiento()
    def crear_asignador(self): return AsignadorMantenimiento()

class IncidenciaBuilder:
    def __init__(self):
        self._documento = {}

    def set_datos_basicos(self, codigo: str, categoria: str, descripcion: str, direccion: str, prioridad: str):
        self._documento.update({
            "codigo_incidencia": codigo,
            "categoria": categoria,
            "descripcion": descripcion,
            "direccion": direccion,
            "estado": "pendiente",
            "prioridad": prioridad
        })
        return self

    def set_ubicacion(self, lat: float, lng: float):
        self._documento["ubicacion"] = {"latitud": lat, "longitud": lng}
        return self

    def set_ciudadano(self, nombres: str, correo: str, telefono: str):
        self._documento["ciudadano"] = {"nombres": nombres, "correo": correo, "telefono": telefono}
        return self

    def set_metadatos(self):
        self._documento.update({
            "fecha_registro": datetime.now().isoformat(),
            "fecha_actualizacion": None,
            "medios": [],
            "historial": []
        })
        return self

    def build(self) -> dict:
        return self._documento

class PrototipoIncidencia:
    def __init__(self, plantilla: dict):
        self._plantilla = plantilla

    def clonar(self, **kwargs) -> dict:
        clon = copy.deepcopy(self._plantilla)
        clon.update(kwargs)
        return clon

class GestorPrototipos:
    def __init__(self):
        self._prototipos = {}

    def registrar(self, nombre: str, prototipo: PrototipoIncidencia):
        self._prototipos[nombre] = prototipo

    def obtener_clon(self, nombre: str, **kwargs) -> dict:
        if nombre not in self._prototipos:
            raise ValueError("Plantilla no encontrada")
        return self._prototipos[nombre].clonar(**kwargs)

_builder_plantilla = IncidenciaBuilder()
_plantilla_bache = _builder_plantilla.set_datos_basicos(
    codigo="TEMPLATE", categoria="bache", descripcion="Bache reportado en vía pública", direccion="Sin especificar", prioridad="media"
).set_ubicacion(0.0, 0.0).set_ciudadano("Anónimo", "anon@ciudad.gob", "").set_metadatos().build()

gestor_prototipos = GestorPrototipos()
gestor_prototipos.registrar("bache_comun", PrototipoIncidencia(_plantilla_bache))

def decorador_log(nombre_operacion: str):
    def envolvente(func):
        @functools.wraps(func)
        async def envoltura_async(*args, **kwargs):
            print(f"[INICIO] {nombre_operacion}")
            try:
                res = await func(*args, **kwargs)
                print(f"[OK]    {nombre_operacion}")
                return res
            except Exception as e:
                print(f"[ERROR] {nombre_operacion}: {e}")
                raise

        @functools.wraps(func)
        def envoltura_sync(*args, **kwargs):
            print(f"[INICIO] {nombre_operacion}")
            try:
                res = func(*args, **kwargs)
                print(f"[OK]    {nombre_operacion}")
                return res
            except Exception as e:
                print(f"[ERROR] {nombre_operacion}: {e}")
                raise

        return envoltura_async if asyncio.iscoroutinefunction(func) else envoltura_sync
    return envolvente

aplicacion = FastAPI(title="IncidenciaVial API", version="1.1.0")
aplicacion.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

CARPETA_MEDIOS = "medios"
os.makedirs(CARPETA_MEDIOS, exist_ok=True)
aplicacion.mount("/medios", StaticFiles(directory=CARPETA_MEDIOS), name="medios")

def serializar(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc

def generar_codigo() -> str:
    sufijo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"INC-{sufijo}"

CATEGORIAS_VALIDAS = {"bache", "alumbrado", "basura", "seguridad", "emergencia"}
ESTADOS_VALIDOS    = {"pendiente", "en_proceso", "resuelto", "rechazado"}

@decorador_log("inicializar_base_de_datos")
def inicializar_bd():
    bd.verificar()
    bd.incidencias.create_index("codigo_incidencia", unique=True)
    bd.incidencias.create_index([("categoria", 1), ("estado", 1)])

try:
    inicializar_bd()
    print("✅ Conectado a MongoDB Atlas y colecciones verificadas.")
except Exception as e:
    print(f"⚠️ Error de conexión: {e}")

class UbicacionModelo(BaseModel):
    latitud: float
    longitud: float

class CiudadanoModelo(BaseModel):
    nombres: str
    correo: str
    telefono: str = ""

class IncidenciaCrear(BaseModel):
    categoria: str
    descripcion: str
    direccion: str
    ubicacion: UbicacionModelo
    ciudadano: CiudadanoModelo

class ActualizarEstado(BaseModel):
    estado: str
    observacion: Optional[str] = ""

@aplicacion.get("/", tags=["Root"])
def raiz():
    return {"mensaje": "IncidenciaVial API v1.1.0"}

@aplicacion.post("/api/incidencias/registrar", tags=["Incidencias"])
@decorador_log("registrar_incidencia")
def registrar_incidencia(incidencia: IncidenciaCrear):
    if incidencia.categoria not in CATEGORIAS_VALIDAS:
        raise HTTPException(400, f"Categoría inválida. Opciones: {CATEGORIAS_VALIDAS}")

    if incidencia.categoria in {"emergencia", "seguridad"}:
        fabrica = FabricaEmergencia()
    else:
        fabrica = FabricaMantenimiento()

    validador = fabrica.crear_validador()
    asignador = fabrica.crear_asignador()

    if not validador.validar(incidencia.categoria):
        raise HTTPException(400, "Error lógico en validación de categoría")

    prioridad_asignada = asignador.obtener_prioridad_por_defecto()
    codigo = generar_codigo()
    while bd.incidencias.find_one({"codigo_incidencia": codigo}):
        codigo = generar_codigo()

    builder = IncidenciaBuilder()
    documento = builder.set_datos_basicos(
        codigo, incidencia.categoria, incidencia.descripcion, incidencia.direccion, prioridad_asignada
    ).set_ubicacion(
        incidencia.ubicacion.latitud, incidencia.ubicacion.longitud
    ).set_ciudadano(
        incidencia.ciudadano.nombres, incidencia.ciudadano.correo, incidencia.ciudadano.telefono
    ).set_metadatos().build()

    bd.incidencias.insert_one(documento)
    notificador.notificar("INCIDENCIA_REGISTRADA", {
        "codigo_incidencia": codigo, "categoria": incidencia.categoria, "correo": incidencia.ciudadano.correo
    })

    return {
        "codigo_incidencia": codigo,
        "mensaje": "Incidencia registrada exitosamente",
        "prioridad_asignada": prioridad_asignada
    }

@aplicacion.post("/api/incidencias/reporte-rapido", tags=["Incidencias"])
@decorador_log("reporte_rapido_prototipo")
def reporte_rapido_prototipo(direccion: str, correo: str):
    codigo = generar_codigo()
    documento_clonado = gestor_prototipos.obtener_clon(
        "bache_comun", 
        codigo_incidencia=codigo, 
        direccion=direccion,
        fecha_registro=datetime.now().isoformat()
    )
    documento_clonado["ciudadano"]["correo"] = correo

    bd.incidencias.insert_one(documento_clonado)
    notificador.notificar("INCIDENCIA_REGISTRADA", {"codigo_incidencia": codigo, "categoria": "bache", "correo": correo})
    
    return {"codigo_incidencia": codigo, "mensaje": "Reporte rápido clonado desde prototipo"}

@aplicacion.post("/api/incidencias/{codigo}/subir-medio", tags=["Incidencias"])
async def subir_medio(codigo: str, archivo: UploadFile = File(...)):
    incidencia = bd.incidencias.find_one({"codigo_incidencia": codigo.upper()})
    if not incidencia: raise HTTPException(404, "Incidencia no encontrada")

    tipo_archivo = "desconocido"
    if archivo.content_type:
        if archivo.content_type.startswith("image/"): tipo_archivo = "imagen"
        elif archivo.content_type.startswith("video/"): tipo_archivo = "video"
        elif archivo.content_type.startswith("audio/"): tipo_archivo = "audio"

    extension = archivo.filename.rsplit(".", 1)[-1] if "." in archivo.filename else "bin"
    nombre_arch = f"{codigo.upper()}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
    ruta_archivo = os.path.join(CARPETA_MEDIOS, nombre_arch)

    with open(ruta_archivo, "wb") as destino:
        shutil.copyfileobj(archivo.file, destino)

    entrada_medio = {"tipo": tipo_archivo, "nombre": archivo.filename, "ruta": f"/medios/{nombre_arch}", "subido_en": datetime.now().isoformat()}

    bd.incidencias.update_one({"codigo_incidencia": codigo.upper()}, {"$push": {"medios": entrada_medio}})
    notificador.notificar("MEDIO_ADJUNTADO", {"codigo_incidencia": codigo, "tipo": tipo_archivo, "archivo": nombre_arch})
    
    return {"mensaje": "Archivo subido correctamente", "medio": entrada_medio}

@aplicacion.get("/api/incidencias/{codigo}", tags=["Incidencias"])
def obtener_incidencia(codigo: str):
    doc = bd.incidencias.find_one({"codigo_incidencia": codigo.upper()})
    if not doc: raise HTTPException(404, "Incidencia no encontrada")
    return serializar(doc)

@aplicacion.patch("/api/incidencias/{codigo}/estado", tags=["Incidencias"])
@decorador_log("actualizar_estado")
def actualizar_estado(codigo: str, cuerpo: ActualizarEstado):
    if cuerpo.estado not in ESTADOS_VALIDOS:
        raise HTTPException(400, f"Estado inválido. Opciones: {ESTADOS_VALIDOS}")

    doc = bd.incidencias.find_one({"codigo_incidencia": codigo.upper()})
    if not doc: raise HTTPException(404, "Incidencia no encontrada")

    entrada_historial = {"estado_anterior": doc["estado"], "estado_nuevo": cuerpo.estado, "observacion": cuerpo.observacion, "fecha": datetime.now().isoformat()}

    bd.incidencias.update_one(
        {"codigo_incidencia": codigo.upper()},
        {"$set": {"estado": cuerpo.estado, "fecha_actualizacion": datetime.now().isoformat()}, "$push": {"historial": entrada_historial}}
    )
    return {"codigo_incidencia": codigo, "estado_nuevo": cuerpo.estado, "mensaje": "Estado actualizado"}

@aplicacion.get("/api/incidencias", tags=["Incidencias"])
def listar_incidencias(categoria: Optional[str] = Query(None), estado: Optional[str] = Query(None), limite: int = Query(50, ge=1, le=200)):
    filtro = {}
    if categoria: filtro["categoria"] = categoria
    if estado:    filtro["estado"]    = estado
    docs = bd.incidencias.find(filtro).sort("fecha_registro", -1).limit(limite)
    return [serializar(d) for d in docs]

@aplicacion.get("/api/estadisticas", tags=["Dashboard"])
def obtener_estadisticas():
    por_categoria = {r["_id"]: r["total"] for r in bd.incidencias.aggregate([{"$group": {"_id": "$categoria", "total": {"$sum": 1}}}])}
    por_estado = {r["_id"]: r["total"] for r in bd.incidencias.aggregate([{"$group": {"_id": "$estado", "total": {"$sum": 1}}}])}
    return {"total": bd.incidencias.count_documents({}), "por_categoria": por_categoria, "por_estado": por_estado}