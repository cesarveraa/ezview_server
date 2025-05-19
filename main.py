# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from uuid import uuid4
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
import os
# 1) Carga variables de entorno
load_dotenv()

# 2) Construye el dict de credenciales
service_account = {
    "type":                        os.getenv("FIREBASE_TYPE"),
    "project_id":                  os.getenv("FIREBASE_PROJECT_ID"),
    "private_key_id":              os.getenv("FIREBASE_PRIVATE_KEY_ID"),
    "private_key":                 os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
    "client_email":                os.getenv("FIREBASE_CLIENT_EMAIL"),
    "client_id":                   os.getenv("FIREBASE_CLIENT_ID"),
    "auth_uri":                    os.getenv("FIREBASE_AUTH_URI"),
    "token_uri":                   os.getenv("FIREBASE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("FIREBASE_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url":        os.getenv("FIREBASE_CLIENT_CERT_URL"),
}

# 3) Inicializar Firebase Admin
cred = credentials.Certificate(service_account)
firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI(title="EzTo IoT-Backend")

# ─── MODELOS MEMBER ─────────────────────────────────────────────────────────────

class MemberBase(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr

class MemberCreate(MemberBase):
    password: str

class MemberUpdate(BaseModel):
    first_name: Optional[str]
    last_name:  Optional[str]

class MemberOut(MemberBase):
    id:    str
    nodes: List[str]  # lista de device_id registrados


# ─── MODELOS DEVICE REGISTRATION ────────────────────────────────────────────────

class IotDeviceRegistration(BaseModel):
    device_id: str
    location:  str
    created_at: Optional[datetime] = None  # si no viene, usamos ahora

class IotDeviceOut(IotDeviceRegistration):
    id: str
    created_at: datetime  # garantizado en la salida

class AppDeviceRegistration(BaseModel):
    location:           Optional[str] = None  # e.j. "app" o "pulsera mano derecha"
    share_camera:       bool                = False
    exercise_variants:  List[str]           = []  # e.j. ["curl_palma_arriba","curl_martillo"]
    created_at:         Optional[datetime]  = None

class AppDeviceOut(AppDeviceRegistration):
    id: str
    created_at: datetime


# ─── HELPERS ───────────────────────────────────────────────────────────────────

def get_member_doc(member_id: str):
    ref = db.collection("members").document(member_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(404, "Member not found")
    return ref, snap.to_dict()


# ─── CRUD MEMBERS ───────────────────────────────────────────────────────────────

@app.post("/members/", response_model=MemberOut)
def create_member(m: MemberCreate):
    member_id = uuid4().hex
    payload = {
        "first_name": m.first_name,
        "last_name":  m.last_name,
        "email":      m.email,
        "password":   m.password,   # → aquí deberías hashear
        "nodes":      []
    }
    db.collection("members").document(member_id).set(payload)
    return MemberOut(id=member_id, **payload)

@app.get("/members/", response_model=List[MemberOut])
def list_members():
    docs = db.collection("members").stream()
    return [MemberOut(id=d.id, **d.to_dict()) for d in docs]

@app.get("/members/{member_id}", response_model=MemberOut)
def get_member(member_id: str):
    _, data = get_member_doc(member_id)
    return MemberOut(id=member_id, **data)

@app.put("/members/{member_id}", response_model=MemberOut)
def update_member(member_id: str, m: MemberUpdate):
    ref, data = get_member_doc(member_id)
    updates = m.dict(exclude_unset=True)
    ref.update(updates)
    new = ref.get().to_dict()
    return MemberOut(id=member_id, **new)

@app.delete("/members/{member_id}", status_code=204)
def delete_member(member_id: str):
    ref, _ = get_member_doc(member_id)
    ref.delete()


# ─── REGISTRO DISPOSITIVO IoT ──────────────────────────────────────────────────

@app.post("/members/{member_id}/iot_devices", response_model=IotDeviceOut)
def add_iot_device(member_id: str, d: IotDeviceRegistration):
    # valida miembro
    ref_member, member_data = get_member_doc(member_id)

    # timestamp y ID de documento
    ts = d.created_at or datetime.utcnow()
    doc_id = ts.strftime("%Y-%m-%dT%H:%M:%SZ") + "_" + d.device_id

    payload = {
        "device_id":  d.device_id,
        "created_at": ts,
        "location":   d.location,
    }
    # guarda en la colección "lecturas iot"
    db.collection("lecturas iot").document(doc_id).set(payload)

    # enlaza el device_id al miembro
    nodes = set(member_data.get("nodes", []))
    nodes.add(d.device_id)
    ref_member.update({"nodes": list(nodes)})

    return IotDeviceOut(id=doc_id, **payload)


# ─── REGISTRO DISPOSITIVO APP ──────────────────────────────────────────────────

@app.post("/members/{member_id}/app_devices", response_model=AppDeviceOut)
def add_app_device(member_id: str, d: AppDeviceRegistration):
    # valida miembro
    ref_member, member_data = get_member_doc(member_id)

    # timestamp y ID de documento (solo timestamp)
    ts = d.created_at or datetime.utcnow()
    doc_id = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "device_id":         "app",
        "created_at":        ts,
        "location":          d.location or "app",
        "share_camera":      d.share_camera,
        "exercise_variants": d.exercise_variants,
    }
    # guarda en la colección "lecturas app"
    db.collection("lecturas app").document(doc_id).set(payload)

    # enlaza "app" al miembro
    nodes = set(member_data.get("nodes", []))
    nodes.add("app")
    ref_member.update({"nodes": list(nodes)})

    return AppDeviceOut(id=doc_id, **payload)
