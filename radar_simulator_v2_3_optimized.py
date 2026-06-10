import csv, json, math, random, socket, time
import xml.etree.ElementTree as ET
from datetime import datetime, UTC
from geopy.distance import geodesic

# ==========================================================
# CONFIGURATION
# ==========================================================
RADAR_KML_FILE, CAMERAS_KML_FILE = "radar.kml", "cameras.kml"
GENERATE_KML_OUTPUT = True
KML_OUTPUT_FILE, CSV_OUTPUT_FILE = "generated_alerts.kml", "generated_alerts.csv"

RADAR_MIN_RANGE_M,  RADAR_MAX_RANGE_M  = 500, 5000
CAMERA_MIN_RANGE_M, CAMERA_MAX_RANGE_M = 50, 1500
CAMERA_FOV_DEG  = 90
CAMERA_BEARINGS = [0, 72, 144, 216, 288]
RADAR_DEVICE_TYPE, CAMERA_DEVICE_TYPE = 9, 10

NUM_ALERTS = 10
HIGH_PRIORITY_MAX, MEDIUM_PRIORITY_MAX = 1500, 3500
MIN_DELAY_SEC, MAX_DELAY_SEC = 2, 5

UDP_IP, UDP_PORT, UDP_FORMAT = "127.0.0.1", 5005, "spider"

DEVICE_ID, DEVICE_HEIGHT, DEVICE_BEARING = 3, 0, 0
FOV_START, FOV_END = 0, 360
DEFAULT_TARGET_TYPE, DEFAULT_CONFIDENCE = 0, 95
DEFAULT_SPEED, DEFAULT_ELEVATION, DEFAULT_HEIGHT = 0, 0, 0

NS = {"kml": "http://www.opengis.net/kml/2.2"}
ALERT_FIELDS = ["sensor_type", "sensor_name", "alert_id", "priority",
                "latitude", "longitude", "distance_m", "bearing", "timestamp"]
STYLE_MAP = {
    ("RADAR",  "HIGH"): "#radarHighStyle",   ("RADAR",  "MEDIUM"): "#radarMediumStyle",
    ("RADAR",  "LOW"):  "#radarLowStyle",    ("CAMERA", "HIGH"):   "#cameraHighStyle",
    ("CAMERA", "MEDIUM"): "#cameraMediumStyle", ("CAMERA", "LOW"): "#cameraLowStyle",
}

# ==========================================================
# KML PARSERS
# ==========================================================
def read_radar_coordinates(kml_file):
    coords = ET.parse(kml_file).getroot().find(".//kml:Point/kml:coordinates", NS)
    if coords is None:
        raise Exception("No Point coordinates found in KML.")
    values = coords.text.strip().split(",")
    if len(values) < 2:
        raise Exception("Invalid coordinate format in KML.")
    return float(values[1]), float(values[0])  # lat, lon


def read_camera_coordinates(kml_file):
    cameras = []
    for idx, pm in enumerate(ET.parse(kml_file).getroot().findall(".//kml:Placemark", NS)):
        pt = pm.find(".//kml:Point/kml:coordinates", NS)
        if pt is None:
            continue
        name_el = pm.find("kml:name", NS)
        lon, lat = pt.text.strip().split(",")[:2]
        cameras.append((name_el.text if name_el is not None else f"Camera_{idx+1}", float(lat), float(lon)))
    return cameras


# ==========================================================
# ALERT GENERATION
# ==========================================================
def uniform_distance(min_r, max_r):
    return math.sqrt(random.uniform(min_r ** 2, max_r ** 2))


def determine_priority(d):
    return "HIGH" if d <= HIGH_PRIORITY_MAX else "MEDIUM" if d <= MEDIUM_PRIORITY_MAX else "LOW"


def random_destination(lat, lon, min_r, max_r, bearing_range=(0, 360)):
    """Returns (lat, lon, distance_m, bearing) for a random point in the coverage zone."""
    bearing = random.uniform(*bearing_range) % 360
    dist = uniform_distance(min_r, max_r)
    dest = geodesic(meters=dist).destination((lat, lon), bearing)
    return dest.latitude, dest.longitude, dist, bearing


# ==========================================================
# PACKET BUILDER
# ==========================================================
def build_packet(alert, sensor_lat, sensor_lon, device_type):
    fmt = UDP_FORMAT.lower()
    if fmt == "json":
        return json.dumps(alert)
    if fmt == "spider":
        fields = [
            DEVICE_ID, device_type, sensor_lat, sensor_lon,
            DEVICE_HEIGHT, DEVICE_BEARING, FOV_START, FOV_END,
            alert["alert_id"], alert["latitude"], alert["longitude"],
            round(alert["distance_m"], 2), round(alert["bearing"], 2),
            DEFAULT_TARGET_TYPE, DEFAULT_CONFIDENCE, int(time.time()),
            0, "", DEFAULT_SPEED, DEFAULT_ELEVATION, DEFAULT_HEIGHT,
        ]
        return ",".join(map(str, fields))
    raise ValueError(f"Unsupported UDP_FORMAT: {UDP_FORMAT}")


# ==========================================================
# UDP
# ==========================================================
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_udp(packet):
    udp_socket.sendto(packet.encode("utf-8"), (UDP_IP, UDP_PORT))


# ==========================================================
# KML OUTPUT
# ==========================================================
def _circle_coords(lat, lon, radius_m):
    pts = [geodesic(meters=radius_m).destination((lat, lon), a) for a in range(361)]
    return " ".join(f"{p.longitude},{p.latitude},0" for p in pts)


def generate_output_kml(radar_lat, radar_lon, cameras, alerts, output_file):
    outer = _circle_coords(radar_lat, radar_lon, RADAR_MAX_RANGE_M)
    inner = _circle_coords(radar_lat, radar_lon, RADAR_MIN_RANGE_M)

    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
    <name>Radar Simulation Output</name>
    <Style id="radarStyle"><IconStyle><color>ff0000ff</color><scale>1.4</scale></IconStyle></Style>
    <Style id="cameraStyle"><IconStyle><color>ffff0000</color><scale>1.4</scale></IconStyle></Style>
    <Style id="radarHighStyle"><IconStyle><color>ff0000ff</color><scale>1.2</scale></IconStyle></Style>
    <Style id="radarMediumStyle"><IconStyle><color>ff00ffff</color><scale>1.2</scale></IconStyle></Style>
    <Style id="radarLowStyle"><IconStyle><color>ff00ff00</color><scale>1.2</scale></IconStyle></Style>
    <Style id="cameraHighStyle"><IconStyle><color>ffffffff</color><scale>1.2</scale></IconStyle></Style>
    <Style id="cameraMediumStyle"><IconStyle><color>ff808080</color><scale>1.2</scale></IconStyle></Style>
    <Style id="cameraLowStyle"><IconStyle><color>ff000000</color><scale>1.2</scale></IconStyle></Style>
    <Placemark><name>Radar</name><styleUrl>#radarStyle</styleUrl>
        <Point><coordinates>{radar_lon},{radar_lat},0</coordinates></Point></Placemark>
    <Placemark><name>Coverage Boundary ({RADAR_MAX_RANGE_M}m)</name>
        <LineString><coordinates>{outer}</coordinates></LineString></Placemark>
    <Placemark><name>Exclusion Zone ({RADAR_MIN_RANGE_M}m)</name>
        <LineString><coordinates>{inner}</coordinates></LineString></Placemark>
'''
    for name, lat, lon in cameras[:5]:
        kml += f'    <Placemark><name>{name}</name><styleUrl>#cameraStyle</styleUrl><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>\n'

    for a in alerts:
        style = STYLE_MAP.get((a["sensor_type"], a["priority"]), "#radarLowStyle")
        kml += (f'    <Placemark><name>{a["sensor_name"]}_{a["alert_id"]}</name>\n'
                f'        <description>Priority: {a["priority"]}\nDistance: {a["distance_m"]}m\nTimestamp: {a["timestamp"]}</description>\n'
                f'        <styleUrl>{style}</styleUrl>\n'
                f'        <Point><coordinates>{a["longitude"]},{a["latitude"]},0</coordinates></Point></Placemark>\n')

    kml += "</Document>\n</kml>"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(kml)


# ==========================================================
# MAIN SIMULATION
# ==========================================================
def run_simulation():
    radar_lat, radar_lon = read_radar_coordinates(RADAR_KML_FILE)
    cameras = read_camera_coordinates(CAMERAS_KML_FILE)

    print("\n===================================")
    print("RADAR ALERT SIMULATOR")
    print("===================================")
    print(f"Radar Lat : {radar_lat}")
    print(f"Radar Lon : {radar_lon}")
    print(f"Format    : {UDP_FORMAT}")
    print("===================================\n")

    all_alerts = []

    for alert_id in range(1, NUM_ALERTS + 1):
        # --- Radar alert ---
        lat, lon, dist, bear = random_destination(radar_lat, radar_lon, RADAR_MIN_RANGE_M, RADAR_MAX_RANGE_M)
        alert = {
            "sensor_type": "RADAR", "sensor_name": "RADAR", "alert_id": alert_id,
            "priority": determine_priority(dist),
            "latitude": round(lat, 8), "longitude": round(lon, 8),
            "distance_m": round(dist, 2), "bearing": round(bear, 2),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        send_udp(build_packet(alert, radar_lat, radar_lon, RADAR_DEVICE_TYPE))
        all_alerts.append(alert)

        # --- Camera alerts ---
        for idx, (cam_name, cam_lat, cam_lon) in enumerate(cameras[:5]):
            half = CAMERA_FOV_DEG / 2
            clat, clon, cdist, cbear = random_destination(
                cam_lat, cam_lon, CAMERA_MIN_RANGE_M, CAMERA_MAX_RANGE_M,
                (CAMERA_BEARINGS[idx] - half, CAMERA_BEARINGS[idx] + half)
            )
            cam_alert = {
                "sensor_type": "CAMERA", "sensor_name": cam_name, "alert_id": alert_id,
                "priority": determine_priority(cdist),
                "latitude": round(clat, 8), "longitude": round(clon, 8),
                "distance_m": round(cdist, 2), "bearing": round(cbear, 2),
                "timestamp": datetime.now(UTC).isoformat(),
            }
            send_udp(build_packet(cam_alert, cam_lat, cam_lon, CAMERA_DEVICE_TYPE))
            all_alerts.append(cam_alert)
            print(f"[{cam_name}] [{alert_id}/{NUM_ALERTS}] {cam_alert['priority']:<6} {cdist:8.2f}m ({clat:.6f}, {clon:.6f})")

        # FIX 1: RADAR line printed AFTER camera loop, matching original behaviour
        print(f"[RADAR] [{alert_id}/{NUM_ALERTS}] {alert['priority']:<6} {dist:8.2f}m ({lat:.6f}, {lon:.6f})")

        if alert_id < NUM_ALERTS:
            delay = random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC)
            print(f"Waiting {delay:.2f} seconds...\n")
            time.sleep(delay)

    # --- CSV Export ---
    with open(CSV_OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ALERT_FIELDS)
        writer.writeheader()
        writer.writerows(all_alerts)

    # FIX 2: End-of-simulation output matches original exactly (two separator blocks,
    # KML Saved printed twice when enabled)
    print("\n===================================")
    if GENERATE_KML_OUTPUT:
        generate_output_kml(radar_lat, radar_lon, cameras, all_alerts, KML_OUTPUT_FILE)
        print(f"KML Saved: {KML_OUTPUT_FILE}")
    print("\n===================================")
    print("SIMULATION COMPLETE")
    print(f"CSV Saved: {CSV_OUTPUT_FILE}")
    if GENERATE_KML_OUTPUT:
        print(f"KML Saved: {KML_OUTPUT_FILE}")
    print("===================================")


if __name__ == "__main__":
    run_simulation()
