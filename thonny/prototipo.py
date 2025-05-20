# esp32_direct_to_realtimedb_optimized.py

WIFI_SSID          = "cesar"
WIFI_PASSWORD      = "123456789"
FIREBASE_RTDB_URL  = "https://ezview-a058b-default-rtdb.firebaseio.com"
FIREBASE_DB_SECRET = "AIzaSyBvAMVHOdMhQnWfMsM2JA2P3fyyqNJPPHA"
DEVICE_ID          = "esp32-pulsera-01"
LOCATION           = "pulsera mano derecha"

import network, urequests, ujson, time, gc
from machine import I2C, Pin

# — Conectar a Wi-Fi —
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
if not wlan.isconnected():
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    while not wlan.isconnected():
        time.sleep(0.1)
print("Wi-Fi OK, IP:", wlan.ifconfig()[0])

# — Clase MPU6050 optimizada —
class MPU6050:
    def __init__(self, i2c, addr=0x68):
        self.i2c, self.addr = i2c, addr
        # Salir de modo sleep
        self.i2c.writeto_mem(addr, 0x6B, b'\x00')
        # Configuración de sample rate a 200Hz (SMPLRT_DIV=4)
        self.i2c.writeto_mem(addr, 0x19, b'\x04')
        # Filtro digital DLPF_CFG=1 → ancho de banda 184Hz
        self.i2c.writeto_mem(addr, 0x1A, b'\x01')
        # Rango giróscopo ±250°/s
        self.i2c.writeto_mem(addr, 0x1B, b'\x00')
        # Rango acelerómetro ±2g
        self.i2c.writeto_mem(addr, 0x1C, b'\x00')
        # Buffer único de lectura
        self._buf = bytearray(14)

    def read_scaled(self):
        # Leer 14 bytes de golpe en el buffer
        self.i2c.readfrom_mem_into(self.addr, 0x3B, self._buf)
        d = self._buf
        # Conversión en línea
        ax = (d[0]<<8 | d[1]); ay = (d[2]<<8 | d[3]); az = (d[4]<<8 | d[5])
        tmp= (d[6]<<8 | d[7]); gx = (d[8]<<8 | d[9])
        gy = (d[10]<<8|d[11]); gz = (d[12]<<8|d[13])
        # Ajuste signo
        if ax & 0x8000: ax -= 65536
        if ay & 0x8000: ay -= 65536
        if az & 0x8000: az -= 65536
        if gx & 0x8000: gx -= 65536
        if gy & 0x8000: gy -= 65536
        if gz & 0x8000: gz -= 65536
        # Escalado
        return (
            ax/16384.0, ay/16384.0, az/16384.0,
            tmp/340.0 + 36.53,
            gx/131.0,   gy/131.0,   gz/131.0
        )

# — Inicializar I2C y sensor —
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400_000)
mpu = MPU6050(i2c)

# — Pines LED RGB y helper —
led_r = Pin(18, Pin.OUT); led_g = Pin(19, Pin.OUT); led_b = Pin(23, Pin.OUT)
def set_color(r,g,b):
    led_r.value(r); led_g.value(g); led_b.value(b)

# — Umbrales y tipo de ejercicio —
ACC_MIN, ACC_MAX = 0.3, 1.5
GYRO_TH          = 150.0
ORIENT_TH        = 25.0
exercise_type    = 1  # 1=supinación, 2=martillo, 3=pronación

# — Prepara URL base y payload plantilla —
base_url = FIREBASE_RTDB_URL + "/lecturas_iot/"
payload = {
    "device_id": DEVICE_ID,
    "location": LOCATION,
    "lecturas": {
        "accelerometer": {"x":0,"y":0,"z":0},
        "gyroscope":     {"x":0,"y":0,"z":0},
        "mpu_temp":      0,
        "led_color":     "",
        "led_state":     {"r":False,"g":False,"b":False},
        "mpu_connected": True,
        "led_operational": True,
        "wifi_rssi":     0,
        "free_heap":     0
    }
}

# — Bucle principal rápido —
while True:
    # 1) Lectura MPU y sistema
    ax,ay,az,temp,gx,gy,gz = mpu.read_scaled()
    rssi = wlan.status("rssi")
    free = gc.mem_free()

    # 2) Chequeos de velocidad
    too_fast = any(abs(a)>ACC_MAX for a in (ax,ay,az)) or \
               any(abs(g)>GYRO_TH for g in (gx,gy,gz))
    too_slow = all(abs(a)<ACC_MIN for a in (ax,ay,az))

    # 3) Orientación según ejercicio
    if   exercise_type==1: orient_ok = abs(gy)<ORIENT_TH
    elif exercise_type==2: orient_ok = abs(gx)<ORIENT_TH
    else:                  orient_ok = abs(gz)<ORIENT_TH

    # 4) Color y LED
    if not orient_ok:
        c, rgb = "rojo", (1,0,0)
    elif too_fast or too_slow:
        c, rgb = "amarillo", (1,1,0)
    else:
        c, rgb = "verde", (0,1,0)
    set_color(*rgb)

    # 5) Timestamp y payload
    tm = time.localtime()
    ts = "{}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(*tm[:6])
    l = payload["lecturas"]
    l["accelerometer"] = {"x":round(ax,3),"y":round(ay,3),"z":round(az,3)}
    l["gyroscope"]     = {"x":round(gx,2),"y":round(gy,2),"z":round(gz,2)}
    l["mpu_temp"]      = round(temp,1)
    l["led_color"]     = c
    l["led_state"]     = {"r":bool(rgb[0]),"g":bool(rgb[1]),"b":bool(rgb[2])}
    l["wifi_rssi"]     = rssi
    l["free_heap"]     = free

    # 6) Envío a Firebase (uno cada 0.1s)
    url = f"{base_url}{ts}_{DEVICE_ID}.json?auth={FIREBASE_DB_SECRET}"
    try:
        resp = urequests.put(url, ujson.dumps(payload))
        resp.close()
    except:
        pass  # omitimos errores breves

    # 7) Salida consola (opcional)
    print(ts, c, "AX{:.2f}".format(ax), "GY{:.1f}".format(gx))

    time.sleep(0.1)
