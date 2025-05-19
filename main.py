# main.py
import os
from dotenv import load_dotenv
from uuid import uuid4
from datetime import datetime
from typing import List, Optional

import firebase_admin
from firebase_admin import credentials, firestore

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# ─── 1) Cargar .env y configurar Firebase ────────────────────────────────────────
load_dotenv()

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

cred = credentials.Certificate(service_account)
firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI(title="EzTo IoT-Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 2) Modelos Pydantic ─────────────────────────────────────────────────────────

class MemberBase(BaseModel):
    first_name: str
    last_name:  str
    email:      EmailStr

class MemberCreate(MemberBase):
    password: str

class MemberUpdate(BaseModel):
    first_name: Optional[str]
    last_name:  Optional[str]

class MemberOut(MemberBase):
    id:    str
    nodes: List[str]

class IotDeviceRegistration(BaseModel):
    device_id:  str
    location:   str
    created_at: Optional[datetime] = None

class IotDeviceUpdate(BaseModel):
    location:   Optional[str]
    created_at: Optional[datetime]

class IotDeviceOut(BaseModel):
    id:         str
    device_id:  str
    location:   str
    created_at: datetime

class AppDeviceRegistration(BaseModel):
    location:           Optional[str] = None
    share_camera:       bool                = False
    exercise_variants:  List[str]           = []
    created_at:         Optional[datetime]  = None

class AppDeviceUpdate(BaseModel):
    location:           Optional[str]
    share_camera:       Optional[bool]
    exercise_variants:  Optional[List[str]]
    created_at:         Optional[datetime]

class AppDeviceOut(BaseModel):
    id:                 str
    device_id:          str
    location:           str
    share_camera:       bool
    exercise_variants:  List[str]
    created_at:         datetime


# ─── 3) Helpers ─────────────────────────────────────────────────────────────────

def get_member_doc(member_id: str):
    ref = db.collection("members").document(member_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(404, "Member not found")
    return ref, snap.to_dict()


# ─── 4) CRUD Miembros ───────────────────────────────────────────────────────────

@app.post("/members/", response_model=MemberOut)
def create_member(m: MemberCreate):
    member_id = uuid4().hex
    payload = {
        "first_name": m.first_name,
        "last_name":  m.last_name,
        "email":      m.email,
        "password":   m.password,
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
    ref, _ = get_member_doc(member_id)
    updates = m.dict(exclude_unset=True)
    ref.update(updates)
    data = ref.get().to_dict()
    return MemberOut(id=member_id, **data)

@app.delete("/members/{member_id}", status_code=204)
def delete_member(member_id: str):
    ref, _ = get_member_doc(member_id)
    ref.delete()


# ─── 5) CRUD Dispositivos IoT ───────────────────────────────────────────────────

@app.post("/members/{member_id}/iot_devices", response_model=IotDeviceOut)
def add_iot_device(member_id: str, d: IotDeviceRegistration):
    ref_member, member_data = get_member_doc(member_id)
    ts = d.created_at or datetime.utcnow()
    doc_id = ts.strftime("%Y-%m-%dT%H:%M:%SZ") + "_" + d.device_id
    payload = {
        "device_id":  d.device_id,
        "location":   d.location,
        "created_at": ts
    }
    db.collection("lecturas iot").document(doc_id).set(payload)
    # enlazar nodo
    nodes = set(member_data.get("nodes", []))
    nodes.add(d.device_id)
    ref_member.update({"nodes": list(nodes)})
    return IotDeviceOut(id=doc_id, **payload)

@app.get("/members/{member_id}/iot_devices", response_model=List[IotDeviceOut])
def list_iot_devices(member_id: str):
    _, member_data = get_member_doc(member_id)
    nodes = set(member_data.get("nodes", []))
    out = []
    for doc in db.collection("lecturas iot").stream():
        data = doc.to_dict()
        if data["device_id"] in nodes:
            out.append(IotDeviceOut(id=doc.id, **data))
    return out

@app.get("/members/{member_id}/iot_devices/{doc_id}", response_model=IotDeviceOut)
def get_iot_device(member_id: str, doc_id: str):
    _, member_data = get_member_doc(member_id)
    snap = db.collection("lecturas iot").document(doc_id).get()
    if not snap.exists or snap.to_dict()["device_id"] not in member_data.get("nodes", []):
        raise HTTPException(404, "IoT device not found for this member")
    data = snap.to_dict()
    return IotDeviceOut(id=doc_id, **data)

@app.put("/members/{member_id}/iot_devices/{doc_id}", response_model=IotDeviceOut)
def update_iot_device(member_id: str, doc_id: str, d: IotDeviceUpdate):
    _, member_data = get_member_doc(member_id)
    ref = db.collection("lecturas iot").document(doc_id)
    snap = ref.get()
    if not snap.exists or snap.to_dict()["device_id"] not in member_data.get("nodes", []):
        raise HTTPException(404, "IoT device not found for this member")
    updates = d.dict(exclude_unset=True)
    ref.update(updates)
    data = ref.get().to_dict()
    return IotDeviceOut(id=doc_id, **data)

@app.delete("/members/{member_id}/iot_devices/{doc_id}", status_code=204)
def delete_iot_device(member_id: str, doc_id: str):
    _, member_data = get_member_doc(member_id)
    snap = db.collection("lecturas iot").document(doc_id).get()
    if not snap.exists or snap.to_dict()["device_id"] not in member_data.get("nodes", []):
        raise HTTPException(404, "IoT device not found for this member")
    db.collection("lecturas iot").document(doc_id).delete()


# ─── 6) CRUD Dispositivos App ───────────────────────────────────────────────────

@app.post("/members/{member_id}/app_devices", response_model=AppDeviceOut)
def add_app_device(member_id: str, d: AppDeviceRegistration):
    ref_member, member_data = get_member_doc(member_id)
    ts = d.created_at or datetime.utcnow()
    doc_id = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "device_id":          "app",
        "location":           d.location or "app",
        "share_camera":       d.share_camera,
        "exercise_variants":  d.exercise_variants,
        "created_at":         ts
    }
    db.collection("lecturas app").document(doc_id).set(payload)
    nodes = set(member_data.get("nodes", []))
    nodes.add("app")
    ref_member.update({"nodes": list(nodes)})
    return AppDeviceOut(id=doc_id, **payload)

@app.get("/members/{member_id}/app_devices", response_model=List[AppDeviceOut])
def list_app_devices(member_id: str):
    _, member_data = get_member_doc(member_id)
    if "app" not in member_data.get("nodes", []):
        return []
    out = []
    for doc in db.collection("lecturas app").stream():
        data = doc.to_dict()
        if data["device_id"] == "app":
            out.append(AppDeviceOut(id=doc.id, **data))
    return out

@app.get("/members/{member_id}/app_devices/{doc_id}", response_model=AppDeviceOut)
def get_app_device(member_id: str, doc_id: str):
    _, member_data = get_member_doc(member_id)
    snap = db.collection("lecturas app").document(doc_id).get()
    if not snap.exists or snap.to_dict().get("device_id") != "app":
        raise HTTPException(404, "App device not found for this member")
    data = snap.to_dict()
    return AppDeviceOut(id=doc_id, **data)

@app.put("/members/{member_id}/app_devices/{doc_id}", response_model=AppDeviceOut)
def update_app_device(member_id: str, doc_id: str, d: AppDeviceUpdate):
    _, member_data = get_member_doc(member_id)
    ref = db.collection("lecturas app").document(doc_id)
    snap = ref.get()
    if not snap.exists or snap.to_dict().get("device_id") != "app":
        raise HTTPException(404, "App device not found for this member")
    updates = d.dict(exclude_unset=True)
    ref.update(updates)
    data = ref.get().to_dict()
    return AppDeviceOut(id=doc_id, **data)

@app.delete("/members/{member_id}/app_devices/{doc_id}", status_code=204)
def delete_app_device(member_id: str, doc_id: str):
    _, member_data = get_member_doc(member_id)
    snap = db.collection("lecturas app").document(doc_id).get()
    if not snap.exists or snap.to_dict().get("device_id") != "app":
        raise HTTPException(404, "App device not found for this member")
    db.collection("lecturas app").document(doc_id).delete()
