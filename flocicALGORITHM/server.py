from pathlib import Path
import time
import cv2
import paho.mqtt.client as mqtt
import numpy as np
import tensorflow as tf
import os
import sys
import slidingwindow
from ultralytics import YOLO
from collections import deque, defaultdict
import queue, threading
import json
from prometheus_client import start_http_server, Counter, Gauge
import subprocess


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         '..',    # up from tempServer
                                         '..',    # up from server
                                         'sleep3-volvo'))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FLOCIC_EXE = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "floCIC", "cmake-build-mscv","floCIC.exe"))



# Prepend it to sys.path so Python can find sortn.py there
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Now this will work
from sortn import *


#TODO: fix the path to slep3volvo
base_path = Path.cwd()
sleep3volvo_path = base_path / 'sleep3-volvo'
print(sleep3volvo_path)

# TODO: And add a GPU check (physical_devices) but dunno if here or if in the routine


import sys
print("sys.executable =", sys.executable)
print("sys.path:", "\n  ".join(sys.path))



""" PRIPRAVA ZA PROMETHEUS """


num_tracked_people = Gauge('num_tracked_people', 'Number of people tracked')

num_actual_crossings = Gauge('num_actual_crossings', 'Number of people who crossed the middle line') # št ljudi, ki prečka
num_detected_crossings = Gauge('num_detected_cross', 'Number of people who were detected crossing')
avg_detected_people_per_frame = Gauge('avg_detected_people_per_frame', 'Average number of people detected per frame')
cur_detected_people_on_frame = Gauge('cur_detected_people_on_frame', 'Number of people detected on frame currently')
cur_crossing_prediction_accuracy = Gauge('cur_crossing_prediction_accuracy', 'Current prediction accuracy, based on ')

avg_track_duration_gauge = Gauge('avg_track_duration', 'Average duration of tracking people, in seconds')



### DONE
detection_time = Gauge('detection_time', 'Time needed for YOLOv8 to detect humans, in seconds')
tracking_time = Gauge('tracking_time', 'Time needed for SORT to track humans, in seconds')
pose_time = Gauge('pose_time', 'Time needed for openpose to detect skeletons, in seconds')
intent_time = Gauge('intent_time', 'Time needed for intent detection, in seconds')
process_frame_time = Gauge('process_frame_time', 'Time needed for processing a frame, in seconds')


def parse_flocic_header(payload: bytes):
    if len(payload) < 14:
        raise ValueError("payload too small for flocic header")

    height = int.from_bytes(payload[0:2], "big", signed=False)
    # c0, cLast not needed for reshape
    n = int.from_bytes(payload[10:14], "big", signed=False)

    if height <= 0 or n <= 0 or (n % height) != 0:
        raise ValueError(f"invalid header: height={height}, n={n}")

    width = n // height
    return width, height

def flocic_decompress(payload: bytes) -> np.ndarray:
    w, h = parse_flocic_header(payload)

    p = subprocess.Popen(
        [FLOCIC_EXE, "--decompress"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    raw, err = p.communicate(input=payload)

    if p.returncode != 0:
        raise RuntimeError(f"flocic failed rc={p.returncode}: {err.decode('utf-8', errors='replace')}")

    if len(raw) != w * h:
        raise RuntimeError(f"bad decompressed size: got={len(raw)} expected={w*h}")

    gray = np.frombuffer(raw, dtype=np.uint8).reshape((h, w))
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return bgr

def flocic_compress_bgr(frame_bgr: np.ndarray) -> bytes:
    if frame_bgr is None or frame_bgr.size == 0:
        raise ValueError("empty frame")

    h, w = frame_bgr.shape[:2]

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

    raw = gray.tobytes()
    if len(raw) != w * h:
        raise RuntimeError(f"bad raw gray size: got={len(raw)} expected={w*h}")

    p = subprocess.Popen(
        [FLOCIC_EXE, "--compress", str(w), str(h)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out, err = p.communicate(input=raw)

    if p.returncode != 0:
        raise RuntimeError(f"flocic compress failed rc={p.returncode}: {err.decode('utf-8', errors='replace')}")

    if len(out) < 14:
        raise RuntimeError(f"compressed output too small: {len(out)} bytes")

    return out


def flocic_roundtrip_check(compressed: bytes, frame_bgr_original: np.ndarray, max_abs_diff=0):
    """
    compress -> decompress -> compare grayscale.
    max_abs_diff=0 means bit-exact grayscale
    """
    back = flocic_decompress(compressed)  # returns BGR from decompressed gray
    g0 = cv2.cvtColor(frame_bgr_original, cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(back, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(g0, g1)
    m = int(diff.max())
    if m > max_abs_diff:
        raise RuntimeError(f"roundtrip mismatch: max_abs_diff={m}")


""" STATISTICS CLASS """


CENTER_LINE_X = None  # Will be set based on video width
crossing_records = {}  # track_id: {'last_side': 'left'|'right', 'crossed': bool}

last_trackers_global = np.zeros((0, 5), dtype=int)
last_frame_idx_global = 0




class Statistics:
    def __init__(self):
        self.start_time = time.time()
        self.frame_count = 0
        self.total_detections = 0  # Total people detections (bounding boxes)
        self.total_crossing_events = 0  # Actual crossing events
        self.track_data = defaultdict(lambda: {
            'first_seen': None,
            'last_seen': None,
            'crossing_frames': 0,
            'total_frames': 0,
            'has_crossed': False  # Track if this person completed a crossing
        })
        self.per_frame_stats = []
        self.timing_data = []
        self.unsure_crossing_events = 0

    def getPredictionAccuracy(self, actual_crossings):
        curSum = 0
        print(f"TRACK DATA:\n {self.track_data}")
        for t in self.track_data.values():
            #print("in track_data.vvalue()")
            if t['has_crossed'] and t['crossing_frames'] > 0:
                curSum += t['crossing_frames']
                #curSum += 1
        # for t in self.track_data.values():
        #     #print("in track_data.vvalue()")
        #     if t['crossing_frames'] > 0:
        #         #curSum += t['crossing_frames']
        #         curSum += 1

        print(f"curSum = {curSum}")
        print(f"crossing events = {self.unsure_crossing_events}")
        #print(f"actualCrossings = {actual_crossings}")
        if self.unsure_crossing_events > 0 and curSum > 0:
            res = curSum / self.unsure_crossing_events
            return res
        # if actual_crossings > 0 and curSum > 0:
        #     res = (actual_crossings / curSum) * 100
        #     return res
        else:
            return 0


    def update_track(self, track_id, frame_idx, bbox, is_crossing_pred):
        track = self.track_data[track_id]
        if track['first_seen'] is None:
            track['first_seen'] = frame_idx

        track['last_seen'] = frame_idx
        track['total_frames'] += 1

        # Update crossing status based on actual position
        x1, y1, x2, y2 = bbox
        center_x = (x1 + x2) / 2

        print(f"TRACK DATA:\n {track}")
        print(f"CROSSING RECORDS = {crossing_records}")


        # Initialize crossing record for new track
        if track_id not in crossing_records:
            crossing_records[track_id] = {
                'last_side': 'left' if center_x < CENTER_LINE_X else 'right',
                'crossed': False
            }



        current_side = 'left' if center_x < CENTER_LINE_X else 'right'
        last_side = crossing_records[track_id]['last_side']
        print(f"Last side: {current_side}, current side: {last_side}")

        # Detect crossing event
        if not crossing_records[track_id]['crossed'] and current_side != last_side:
            # Only count crossing if prediction was crossing at some point
            if is_crossing_pred:
                self.total_crossing_events += 1
                track['has_crossed'] = True
                crossing_records[track_id]['crossed'] = True
            # Update side regardless of prediction
            crossing_records[track_id]['last_side'] = current_side

        # Update crossing frames only when prediction says crossing
        if is_crossing_pred:
            track['crossing_frames'] += 1

    def update_frame(self, frame_idx, num_people, num_crossing_pred):
        global cur_detected_people_on_frame
        self.frame_count += 1
        self.total_detections += num_people

        cur_detected_people_on_frame.set(num_people)

        self.per_frame_stats.append({
            'frame_idx': frame_idx,
            'num_people': num_people,
            'num_crossing_pred': num_crossing_pred,
            'timestamp': time.time()
        })

    def update_timing(self, frame_idx, detection, tracking, pose, intent, other, total):
        global detection_time, tracking_time, pose_time, intent_time, process_frame_time
        detection_time.set(detection)
        tracking_time.set(tracking)
        pose_time.set(pose)
        intent_time.set(intent)
        process_frame_time.set(total)
        self.timing_data.append({
            'frame_idx': frame_idx,
            'detection': detection,
            'tracking': tracking,
            'pose': pose,
            'intent': intent,
            'other': other,
            'total': total
        })

    def get_summary(self):

        global num_tracked_people, num_actual_crossings, avg_detected_people_per_frame, num_detected_crossings, cur_crossing_prediction_accuracy, avg_track_duration_gauge

        #print("GETTING SUMMARY")
        elapsed = time.time() - self.start_time
        unique_tracks = len(self.track_data)
        num_tracked_people.set(unique_tracks)

        # Calculate actual crossings (people who completed crossing)
        actual_crossings = sum(1 for t in self.track_data.values() if t['has_crossed'])
        num_actual_crossings.set(actual_crossings)

        #print("here1")

        # Calculate various metrics
        avg_people_per_sec = self.total_detections / elapsed if elapsed > 0 else 0
        avg_detected_people_per_frame.set(avg_people_per_sec)


        num_detected_crossings.set(self.total_crossing_events)

        avg_crossings_per_sec = actual_crossings / elapsed if elapsed > 0 else 0

        #print("here2")

        track_durations = [t['total_frames'] for t in self.track_data.values()]
        avg_track_duration = sum(track_durations) / len(track_durations) if track_durations else 0

        #print("here3")


        # Calculate crossing percentage based on prediction accuracy
        if self.total_detections > 0:
            prediction_accuracy = self.getPredictionAccuracy(actual_crossings)
            ##prediction_accuracy = actual_crossings / self.total_crossing_events * 100
        else:
            prediction_accuracy = 0

        print(f"PREDICTION ACCURACY: {prediction_accuracy}")

        cur_crossing_prediction_accuracy.set(prediction_accuracy)

        #print("here4")

        # Timing metrics
        n = len(self.timing_data)
        if n > 0:
            avg_detection = sum(t['detection'] for t in self.timing_data) / n
            avg_tracking = sum(t['tracking'] for t in self.timing_data) / n
            avg_pose = sum(t['pose'] for t in self.timing_data) / n
            avg_intent = sum(t['intent'] for t in self.timing_data) / n
            avg_other = sum(t['other'] for t in self.timing_data) / n
            avg_total = sum(t['total'] for t in self.timing_data) / n
        else:
            avg_detection = avg_tracking = avg_pose = avg_intent = avg_other = avg_total = 0.0

        avg_track_duration_gauge.set(round(avg_track_duration, 1))

        print(f"AVG DETECTION: {avg_detection}")
        return {
            'elapsed_seconds': round(elapsed, 1),
            'total_frames': self.frame_count,
            'total_people': unique_tracks,
            'total_crossings': actual_crossings,  # Actual crossing events
            'total_detections': self.total_detections,
            'avg_people_per_sec': round(avg_people_per_sec, 2),
            'avg_crossings_per_sec': round(avg_crossings_per_sec, 2),
            'avg_track_duration': round(avg_track_duration, 1),
            'crossing_prediction_accuracy': round(prediction_accuracy, 1),
            'unsure_crossing_events': self.unsure_crossing_events,
            # Timing metrics
            'avg_detection_time': round(avg_detection, 4),
            'avg_tracking_time': round(avg_tracking, 4),
            'avg_pose_time': round(avg_pose, 4),
            'avg_intent_time': round(avg_intent, 4),
            'avg_other_time': round(avg_other, 4),
            'avg_total_time': round(avg_total, 4)
        }


""" YOLO SETUP """

#TODO: add later for gpu
# Load YOLOv8 model and move to CPU
yolo = YOLO('yolov8n.pt')
yolo.to('cpu')
YOLO_CONFIDENCE_THRESHOLD = 0.5

def detect_humans(frame: np.ndarray, conf_thresh=0.5) -> np.ndarray:
    # Convert BGR to RGB and run inference
    results = yolo(frame[..., ::-1])

    # Extract raw detections
    boxes = results[0].boxes
    if boxes is None or boxes.shape[0] == 0:
        return np.zeros((0, 5), dtype=float)

    # Retrieve coordinates, confidence scores, and class IDs
    xyxy = boxes.xyxy.cpu().numpy()       # shape (N,4)
    conf = boxes.conf.cpu().numpy().reshape(-1, 1)  # shape (N,1)
    classes = boxes.cls.cpu().numpy().astype(int)   # shape (N,)

    # COCO class ID for person is 0; keep only human detections
    mask = (classes == 0) & (conf.flatten() >= conf_thresh)
    if not mask.any():
        return np.zeros((0, 5), dtype=float)

    # Stack filtered boxes and confidences
    detections = np.hstack((xyxy[mask], conf[mask]))
    print(f"[YOLO] Filtered {mask.sum()} persons with confidence > {conf_thresh}")
    return detections


""" POSE ESTIMATION SETUP """

# TODO: might have to remove this
os.environ['CUDA_VISIBLE_DEVICES'] = ''    # optional, hides GPUs at OS level

tf_config = tf.compat.v1.ConfigProto(
    allow_soft_placement=True,
    device_count={'GPU': 0},              # <= this kills any GPU device
    gpu_options=tf.compat.v1.GPUOptions(
        allow_growth=True
    )
)

tf_pose_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'sleep3-volvo', 'tf-pose-estimation'))

if tf_pose_path not in sys.path:
    sys.path.insert(0, tf_pose_path)


from tf_pose.estimator import TfPoseEstimator
from tf_pose.networks import get_graph_path

graph_path = get_graph_path('mobilenet_thin', sleep3volvo_path)

pose_model = TfPoseEstimator(
    graph_path,
    target_size=(432,368),
    tf_config=tf_config
)

resize_out_ratio = 4.0 #Adjust based on needs
fps_time = 0
KEYPOINT_CONFIDENCE_THRESHOLD = 0.1


""" SORT SETUP """
mot_tracker = Sort()


""" DENSENET SETUP """
tf.keras.backend.clear_session()
tf.config.run_functions_eagerly(True)

densenet_path = sleep3volvo_path

def load_densenet_model():
    # Try loading with legacy format
    try:
        model = tf.keras.models.load_model(
            f'{sleep3volvo_path}/densenet_2.hdf5',
            compile=False
        )
        model.compile(run_eagerly=True)  # Force eager execution
        return model
    except:
        pass

    # Fallback to JSON loading
    with open(f'{sleep3volvo_path}/densenet_model.json', 'rb') as f:
        model = tf.keras.models.model_from_json(
            f.read(),
            custom_objects={'Model': tf.keras.Model}
        )
    model.load_weights('densenet_2.hdf5')
    model.compile(run_eagerly=True)  # Critical for eager execution
    return model

model_j = load_densenet_model()

# 3. SAFE prediction function
def pred_func(X_test):
  predictions = model_j.predict(X_test[0:1], verbose=0)
  Y = np.argmax(predictions[0], axis=0)

  return Y

def publish_frame_compressed(frame_bgr: np.ndarray):
    try:
        payload = flocic_compress_bgr(frame_bgr)  # bytes
        ret = server.publish(f"{outputChannel}/frames", payload, qos=1, retain=False)
        print(f"Sent COMPRESSED frame: {len(payload)} bytes, rc={ret.rc}")
    except Exception as e:
        print(f"Error compressing/publishing frame: {e}")


""" PROCESIRANJE """


def is_blurry(image, threshold=100.0):
    """Check if an image is blurry using the Laplacian variance method."""
    return cv2.Laplacian(image, cv2.CV_64F).var() < threshold

def sharpen_image(image):
    """
    Advanced image sharpening and resolution enhancement:
    1. High-boost filtering (stronger sharpening)
    2. CLAHE for local contrast
    3. Optional upscaling with Lanczos
    4. Post-CLAHE sharpening
    5. Optional edge enhancement
    """
    # Step 1: High-boost filter
    gaussian = cv2.GaussianBlur(image, (0, 0), sigmaX=2)
    high_boost = cv2.addWeighted(image, 1.8, gaussian, -0.8, 0)

    # Step 2: CLAHE
    lab = cv2.cvtColor(high_boost, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    enhanced_lab = cv2.merge((cl, a, b))
    enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    # Step 3: Optional upscaling
    h, w = enhanced.shape[:2]
    if w < 100 or h < 100:
        upscale_factor = 2
        enhanced = cv2.resize(enhanced, (w * upscale_factor, h * upscale_factor), interpolation=cv2.INTER_LANCZOS4)

    # Step 4: Final sharpening
    sharpen_kernel = np.array([[0, -1, 0],
                               [-1, 5.5, -1],
                               [0, -1, 0]])
    sharpened = cv2.filter2D(enhanced, -1, sharpen_kernel)

    # Step 5: Edge enhancement via Laplacian
    laplacian = cv2.Laplacian(sharpened, cv2.CV_64F)
    laplacian = np.clip(laplacian, -15, 15).astype(np.uint8)
    final = cv2.addWeighted(sharpened, 1.0, laplacian, 0.2, 0)

    return final

def resize_with_padding(image, target_size=(432, 368)):
    """Resize image while keeping aspect ratio and padding to fit target size."""
    target_w, target_h = target_size
    h, w = image.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(image, (new_w, new_h))

    top = (target_h - new_h) // 2
    bottom = target_h - new_h - top
    left = (target_w - new_w) // 2
    right = target_w - new_w - left

    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    return padded

def remove_padding(image, original_shape, target_size=(432, 368)):
    target_w, target_h = target_size
    orig_h, orig_w = original_shape

    scale = min(target_w / orig_w, target_h / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)

    top = (target_h - new_h) // 2
    left = (target_w - new_w) // 2

    cropped = image[top:top+new_h, left:left+new_w]
    return cropped


def annotate_frame(frame, trackers, track_intent):
    """Add bounding boxes, track IDs and intent text to frame"""
    for tracker in trackers.astype(int):
        x1, y1, x2, y2, track_id = tracker
        track_id = int(track_id)  # Ensure integer ID

        intent = track_intent.get(track_id, 0)

        color = (0, 0, 255) if intent == 1 else (0, 255, 0)  # Red for crossing, green for not
        label = "CROSSING" if intent == 1 else "NOT CROSSING"

        if x1 >= x2 or y1 >= y2:
            print(f"Invalid coordinates for track {track_id}: ({x1},{y1})-({x2},{y2})")
            continue

        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)

        cv2.putText(frame, f"ID: {track_id}", (int(x1), int(y1) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        cv2.putText(frame, label, (int(x1), int(y1) - 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    return frame



rolling_buffer = {}                     # current frames
track_intent  = {}                      # track_id → last predicted intent
stats         = Statistics()            # statistics gathering object
video_writer  = None                    # initialized in worker_thread
debug_path    = "debug_output"          # debug path
output_video_path = "output_video.avi"

def init_video_writer(frame):
    """Initialize video writer with first frame's dimensions"""
    global video_writer
    height, width = frame.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    video_writer = cv2.VideoWriter(output_video_path, fourcc, 30.0, (width, height))


def update_video_writer(frames):
    """Append processed frames to output video"""
    global video_writer
    if not frames:
        return

    if video_writer is None:
        height, width = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        video_writer = cv2.VideoWriter(output_video_path, fourcc, 30.0, (width, height))

    for frame in frames:
        video_writer.write(frame)


"""
Funkcija `processFrames` obdela en okvir videoposnetka in izvaja naslednje korake:
1. Detekcija ljudi z uporabo YOLO modela.
2. Posodabljanje sledilnih ID-jev s pomočjo SORT sledilnika.
3. Detekcija skeleta za vsako zaznano osebo.
4. Uporaba denseNet za detekcijo namena.
5. Anotacija okvirja.
6. Posodabljanje statistike in pisanje rezultatov v video.

Vhodi:
- frame (np.ndarray): RGB slika trenutnega video okvirja, ki se obdela.
- frame_ind (int): Indeks trenutnega okvirja znotraj celotnega videa.
- debug (bool): Če je `True`, se dodatno shranijo vmesni rezultati in se vodi dnevnik za odpravljanje napak.

Izhodi:
- annotated (np.ndarray): Okvir z narisanimi rezultati (trackID, skeleti, napovedi ("crossing", "not crossing").
- predictions (dict[int, int]): Slovar napovedi za vsakega sledilnega ID-ja. Ključ je `track_id`, vrednost je:
    - 0 = ne bo prečkal,
    - 1 = bo prečkal.
"""

def processFrames(frame, frame_ind, debug=False):
    global mot_tracker, rolling_buffer, stats, track_intent, video_writer, CENTER_LINE_X

    # Inicializacija sredinske črte, če še ni nastavljena
    if CENTER_LINE_X is None:
        CENTER_LINE_X = frame.shape[1] / 2

    t_start = time.time()
    img_orig = frame.copy()

    # Če je omogočen način za odpravljanje napak, inicializiraj log datoteko
    debug_log = None
    if debug:
        os.makedirs(debug_path, exist_ok=True)
        debug_log = open(f"{debug_path}/frame_{frame_ind:06d}_log.txt", "w")
        print(f"\n=== Frame {frame_ind} ===", file=debug_log)

    # 1) Zaznavanje ljudi v sliki z YOLO modelom
    t0 = time.time()
    detections = detect_humans(img_orig, YOLO_CONFIDENCE_THRESHOLD)
    t_detection = time.time() - t0

    # 2) Posodobitev sledilnika (MOT) z novo zaznanimi osebami
    t0 = time.time()
    trackers = mot_tracker.update(detections).astype(int)
    last_trackers = trackers.copy()
    t_tracking = time.time() - t0

    global last_trackers_global, last_frame_idx_global
    last_trackers_global = last_trackers.copy()
    last_frame_idx_global = frame_ind



    # 3) Ocenjevanje poze za vsako sledeno osebo
    t0 = time.time()
    for x1, y1, x2, y2, tid in trackers:
        crop = img_orig[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        # Če je izrez zamegljen, ga izostri
        if is_blurry(crop):
            crop = sharpen_image(crop)

        # Prilagodi velikost izreza in pošlji v model za oceno poze
        crop_resized = resize_with_padding(crop, (432, 368))
        poses = pose_model.inference(
            crop_resized, resize_to_default=False, upsample_size=resize_out_ratio
        )

        # Odstrani sklepe z nizko zanesljivostjo
        for h in poses:
            for k in list(h.body_parts):
                if h.body_parts[k].score < KEYPOINT_CONFIDENCE_THRESHOLD:
                    del h.body_parts[k]
        poses.sort(key=lambda h: h.score, reverse=True)

        # Nariši skelet na izrez
        padded = TfPoseEstimator.draw_humans(crop_resized, poses, imgcopy=True)
        skeleton = remove_padding(padded, crop.shape[:2], (432, 368))

        # Vstavi skelet nazaj v originalni okvir
        target_slice = img_orig[y1:y2, x1:x2]
        th, tw = target_slice.shape[:2]
        try:
            skeleton_resized = cv2.resize(skeleton, (tw, th))
            img_orig[y1:y2, x1:x2] = skeleton_resized
        except cv2.error as e:
            print(f"Skipping skeleton paste for track {tid}: {e}")

        # Posodobi krožni medpomnilnik s trenutno sliko
        buf_img = cv2.resize(img_orig[y1:y2, x1:x2], (100, 100))
        rolling_buffer.setdefault(tid, deque(maxlen=16)).append(buf_img)

        # DEBUG: Shrani slike izrezov in skeletov
        if debug:
            cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_crop.jpg", crop)
            cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_skeleton.jpg", skeleton)
    t_pose = time.time() - t0

    # 4) Napovedovanje namena (npr. prečkanje) za vsako osebo
    t0 = time.time()
    predictions = {}
    num_crossing_pred = 0

    # Pridobi trenutni namen iz prejšnjih sledi
    for x1, y1, x2, y2, tid in last_trackers:
        current_intent = track_intent.get(tid, 0)
        print(f"Current intent: {current_intent}")
        is_cross_pred = (current_intent == 1)
        if is_cross_pred:
            num_crossing_pred += 1

        # Posodobi statistiko s trenutnimi podatki
        print(f"isCrossingPred {is_cross_pred}")
        stats.update_track(tid, frame_ind, (x1, y1, x2, y2), is_cross_pred)

    # Izvedi napovedi za osebe z dovolj podatki v medpomnilniku
    for x1, y1, x2, y2, tid in last_trackers:
        seq = list(rolling_buffer.get(tid, []))
        if len(seq) == 16:
            arr = np.stack(seq, axis=2)[None, ...]
            pred = int(pred_func(arr))
            predictions[tid] = pred
            track_intent[tid] = pred
            is_cross_pred = (pred == 1)

            # DEBUG: Shrani vhodne podatke in napovedi
            if debug and debug_log:
                np.save(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_input.npy", arr)
                mosaic = np.hstack([cv2.resize(f, (50, 50)) for f in seq])
                cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_track_{tid}_sequence.jpg", mosaic)
                print(f"Track {tid}: {'CROSSING' if is_cross_pred else 'NOT CROSSING'}", file=debug_log)
        else:
            # Privzeta napoved (TODO komentar nakazuje, da je to začasno)
            pred = 0
            predictions[tid] = pred
            track_intent[tid] = pred
            is_cross_pred = (pred == 1)
    t_intent = time.time() - t0

    # 5) Priprava anotiranega okvirja z narisanimi rezultati
    annotated = annotate_frame(img_orig.copy(), last_trackers, track_intent)

    # 6) Posodobi statistiko okvirja
    stats.update_frame(frame_ind, len(last_trackers), num_crossing_pred)
    if debug:
        cv2.imwrite(f"{debug_path}/frame_{frame_ind:06d}_annotated.jpg", annotated)
        summary = {
            'frame': frame_ind,
            'num_tracks': int(len(last_trackers)),
            'num_crossing_pred': int(num_crossing_pred),
            'predictions': predictions,
        }
        if debug_log:
            print("Summary:", summary, file=debug_log)
            debug_log.close()

    # Povzetek napovedi
    summary = {
        'frame': frame_ind,
        'num_tracks': int(len(last_trackers)),
        'num_crossing_pred': int(num_crossing_pred),
        'predictions': predictions,
    }
    print(f"SUMMARY: {summary}")

    # 7) Počisti stare sledi, ki niso več aktivne
    active = {int(t[4]) for t in last_trackers}
    for tid in list(rolling_buffer):
        if tid not in active:
            rolling_buffer.pop(tid, None)
            track_intent.pop(tid, None)
            if tid in crossing_records:
                crossing_records.pop(tid)
            if debug:
                with open(f"{debug_path}/cleanup.log", "a") as lg:
                    print(f"Cleaned track {tid}", file=lg)

    # 8) Zapiši v video
    update_video_writer([annotated])

    # Record timing breakdown
    t_other = time.time() - t_start - (t_detection + t_tracking + t_pose + t_intent)
    stats.update_timing(
        frame_ind,
        t_detection,
        t_tracking,
        t_pose,
        t_intent,
        t_other,
        time.time() - t_start
    )
    print(f"FINAL PREDICTIONS: {predictions}")

    if len(predictions) > 0:
        stats.unsure_crossing_events += len(predictions)

    return annotated, compressed, predictions



""" INICIALIZACIJA MQTT """

broker = "10.241.227.26" #TODO: spremeni za mqtt broker (prev: 10.241.227.26)
port = 1883 #privzeti port za mqtt broker
inputChannel = "/input" # kanal, kjer server pridobiva slike
outputChannel = "/output" # kanal, na katerega server pošilja rezultate

GYRO_TOPIC = "/output/gyro"

gyro_lock = threading.Lock()

last_gyro_g = None        # npr. (gx, gy, gz) ali dict
brake_state = None        # zadnji veljaven B (0/1)
_last_brake_state = None  # interno: za detekcijo spremembe

curFrames = deque(maxlen=16)  # Automatically discards oldest when >16
initialized = False
frame_ind = 0
msg_queue = queue.Queue()
vid_ind = 0


""" PUBLISHING FUNCTIONS """
def publish_frame(frame):
    if isinstance(frame, int):
        payload = frame
        ret = server.publish(f"{outputChannel}/frames_bmp", payload, qos=1, retain=False)
        print(f"Pošiljanje: sporočilo o koncu, rc={ret.rc}, topic: {outputChannel}/frames")
        return

    # 1) Encode to JPEG
    success, buffer = cv2.imencode('.bmp', frame)
    if not success:
        print(f"Failed to encode frame")
        return

    # 2) Convert to bytes
    payload = buffer.tobytes()

    # 3) Publish the bytes
    ret = server.publish(f"{outputChannel}/frames", payload, qos=1, retain=False)

    # 4) Log
    print(f"Pošiljanje: frame rc={ret.rc}, topic: {outputChannel}/frames")


def publish_predictions(predictions):
    """
    Publish crossing predictions as a dictionary {track_id: 1}
    Example: {55: 1, 56: 1} means tracks 55 and 56 are crossing
    """
    try:
        print(f"PREDICTIONS: {predictions}")

        # Handle empty predictions case
        if not predictions:
            predictions = {}  # Ensure empty dict if None or empty

        if not isinstance(predictions, dict):
            raise ValueError("Predictions must be a dictionary {track_id: 1}")

        track_list = [int(track_id) for track_id, crossing_status in predictions.items() if crossing_status == 1]

        payload = json.dumps(track_list)
        ret = server.publish(f"{outputChannel}/preds", payload, qos=1, retain=False)
        print(f"SENT TRACK PREDICTIONS: {payload}")

        if len(track_list) > 0:
            print(f"PREDICTIONS NON 0:  {predictions}")
        print(f"Sent predictions: {predictions}, rc={ret.rc}")
    except Exception as e:
        print(f"Error publishing predictions: {e}")


def publish_statistic():
    """
    Publish tracking statistics using stats.get_summary()
    stats_object: The instance that has get_summary() method
    """
    global stats
    try:
        if not hasattr(stats, 'get_summary'):
            raise ValueError("stats_object must have get_summary() method")

        send_stats = stats.get_summary()
        payload = json.dumps(send_stats)
        ret = server.publish(f"{outputChannel}/stats", payload, qos=1, retain=False)
        print(f"Sent statistics, rc={ret.rc}")
    except Exception as e:
        print(f"Error publishing statistics: {e}")

def publish_bboxes(frame_idx=None, trackers=None, include_intent=True):
    global last_trackers_global, last_frame_idx_global, track_intent
    global brake_state, last_gyro_g, gyro_lock

    try:
        if frame_idx is None:
            frame_idx = int(last_frame_idx_global)
        if trackers is None:
            trackers = last_trackers_global

        if trackers is None:
            trackers = np.zeros((0, 5), dtype=int)

        # preberi gyro/brake atomarno
        with gyro_lock:
            bs = brake_state
            g = last_gyro_g

        tracks_out = []
        for tr in np.asarray(trackers).astype(int):
            if tr.shape[0] < 5:
                continue

            x1, y1, x2, y2, tid = map(int, tr[:5])

            if x2 <= x1 or y2 <= y1:
                continue

            item = {
                "id": int(tid),
                "corners": {
                    "ul": [x1, y1],
                    "ur": [x2, y1],
                    "ll": [x1, y2],
                    "lr": [x2, y2],
                }
            }

            if include_intent:
                # Če brake state obstaja, ga uporabi kot intent, sicer fallback na model
                if bs in (0, 1):
                    item["intent"] = int(bs)
                else:
                    item["intent"] = int(track_intent.get(int(tid), 0))

            # (opcijsko) per-track dodaj brakeState ločeno, če želiš
            item["brakeState"] = None if bs is None else int(bs)

            tracks_out.append(item)

        payload_obj = {
            "frame": int(frame_idx),
            "tracks": tracks_out,
            # (opcijsko) top-level vrednosti (koristno za debug/telemetrijo)
            "brakeState": None if bs is None else int(bs),
            "gyroG": None if g is None else [int(g[0]), int(g[1]), int(g[2])],
        }

        payload = json.dumps(payload_obj)

        ret = server.publish(f"{outputChannel}/bboxes", payload, qos=1, retain=False)
        print(f"Sent bboxes: frame={frame_idx}, n={len(tracks_out)}, rc={ret.rc}")

    except Exception as e:
        print(f"Error publishing bboxes: {e}")



def on_message(client, userdata, msg):
    global curFrames, stats, initialized, frame_ind, msg_queue, output_video_path, video_writer, vid_ind, CENTER_LINE_X
    global last_gyro_g, brake_state, _last_brake_state

    # ------------- GYRO TOPIC HANDLER -------------
    if msg.topic == GYRO_TOPIC:
        try:
            payload = msg.payload.decode("utf-8", errors="replace").strip()
            if not payload:
                return

            # Primeri:
            # "G,-1600,100,-8800"
            # "B,1"
            parts = [p.strip() for p in payload.split(",")]
            if not parts:
                return

            kind = parts[0]

            if kind == "G":
                # Pričakujemo 3 vrednosti
                if len(parts) >= 4:
                    gx = int(parts[1])
                    gy = int(parts[2])
                    gz = int(parts[3])
                    with gyro_lock:
                        last_gyro_g = (gx, gy, gz)
                # (po želji: log)
                # print(f"[GYRO] G={last_gyro_g}")

            elif kind == "B":
                # Pričakujemo 0 ali 1
                if len(parts) >= 2:
                    b = int(parts[1])
                    if b not in (0, 1):
                        return

                    # shrani samo ob spremembi
                    with gyro_lock:
                        if _last_brake_state is None or b != _last_brake_state:
                            brake_state = b
                            _last_brake_state = b
                            print(f"[GYRO] Brake changed -> B={b}")
                        # else: ignoriraj, ker ni spremembe

            else:
                # neznan tip
                return

        except Exception as e:
            print(f"[GYRO] Error parsing gyro payload: {e}")
        return

    # ------------- INPUT FRAMES HANDLER -------------
    # Od tu naprej tvoja obstoječa logika (inputChannel) ostane praktično enaka

    payload = msg.payload  # bytes

    # Handle control messages as bytes (no UTF-8 decoding)
    if payload == b"-1":
        print("\n===================================== END =====================================\n")
        print(f"{stats.get_summary()}")
        return

    if payload == b"0":
        print(f"\n############################  DONE RECEIVING VIDEO #{vid_ind}   ##############################\n")
        print(f"{stats.get_summary()}")
        print("##################################################################################")

        vid_ind += 1
        curFrames = deque(maxlen=16)
        stats = Statistics()
        initialized = False
        frame_ind = 0

        while True:
            try:
                msg_queue.get_nowait()
                msg_queue.task_done()
            except queue.Empty:
                break

        video_writer = None
        output_video_path = f"output_video_{vid_ind}.avi"
        CENTER_LINE_X = None
        return

    # Otherwise it's a frame: queue it
    msg_queue.put(msg)




def worker_loop():
    global initialized, frame_ind
    while True:
        msg = msg_queue.get()

        try:
            frame_ind += 1
            print(f"Received message {frame_ind}")

            bmp_img = cv2.imdecode(
                np.frombuffer(msg.payload, dtype=np.uint8),
                cv2.IMREAD_COLOR
            )

            try:
                img = flocic_decompress(msg.payload)
            except Exception as e:
                print(f"Decompression failed on frame {frame_ind}: {e}")
                continue

            if img is None or img.size==0:
                print("Bad frame, skipping")
                continue

            if frame_ind % 50 == 0:
                cv2.imwrite(f"debug_decompressed_{frame_ind}.png", img)

            #if not initialized:
            #    init_video_writer(img)

            # append to your rolling 16-window
            curFrames.append(img)

            # on first 16 messages you still only need to call processFrames on the *one* new frame
            processed, preds = processFrames(img, frame_ind, debug=False)
            print("Publishing predictions")
            try:
                print("Publishing FRAME")
                publish_frame_compressed(processed)
                publish_frame(bmp_img)
            except Exception as e:
                pass

            try:
                print("Publishing PREDS")
                publish_predictions(preds)
            except Exception as e:
                pass

            try:
                print("Publishing STATS")
                publish_statistic()
            except Exception as e:
                pass

            try:
                print("Publishing BBOXES")
                publish_bboxes()
            except Exception as e:
                pass

            initialized = True

        except Exception as e:
            print("Error in worker_loop:", e)
        finally:
            msg_queue.task_done()

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully")
        client.subscribe(inputChannel, qos=1)
        client.subscribe(GYRO_TOPIC, qos=1)
        print(f"Subscribed to {inputChannel} and {GYRO_TOPIC}")
    else:
        print(f"Connection failed with code {rc}")




server = mqtt.Client(client_id="server", clean_session=True, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

server.connect(broker, port, 32000)
server.on_connect = on_connect
server.on_message = on_message
print("Came to here :)")
threading.Thread(target=worker_loop, daemon=True).start()
start_http_server(8000)
print("Started prometheous http server")
server.loop_forever()

